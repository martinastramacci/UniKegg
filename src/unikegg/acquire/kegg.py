"""Rate-limited KEGG acquisition with verified, selection-specific details."""

import json
import urllib.error
from datetime import datetime, timezone

from unikegg.acquire.common import HttpClient, atomic_json, file_lock, selection_state
from unikegg.config import RAW
from unikegg.dataset import sha256
from unikegg.kegg_data import (
    acquisition_manifest,
    check_payload,
    flat_records,
    pairs,
    requests,
    selected_details,
    strip_prefix,
    tabular_rows,
)
from unikegg.organisms import select

ROOT = RAW / "kegg"
BASE_URL = "https://rest.kegg.jp"


def reconcile_organism_catalogs(codes, client, metadata):
    """Refresh catalog and link files that disagree, before downloading details."""
    evidence = {}
    def refresh(endpoint, relative):
        fetch(endpoint, relative, client=client, metadata=metadata, refresh=True)

    for code in codes:
        gene_file = f"genes/{code}_genes.tsv"
        pathway_file = f"pathway/{code}_pathways.tsv"
        sources = {
            "gene_ko": f"/link/ko/{code}",
            "gene_pathway": f"/link/pathway/{code}",
            "uniprot": f"/conv/uniprot/{code}",
        }

        def unresolved():
            genes = {row[0] for row in tabular_rows(ROOT / gene_file, columns=4)}
            pathways = {p for p, _ in pairs(ROOT, pathway_file)}
            bad = {}
            for suffix in sources:
                path = ROOT / f"relations/{code}_{suffix}.tsv"
                entries = [
                    (gene, target) for gene, target in tabular_rows(path)
                    if gene not in genes or (
                        suffix == "gene_pathway" and strip_prefix(target) not in pathways
                    )
                ]
                if entries:
                    bad[suffix] = entries
            return bad

        bad = unresolved()
        if not bad:
            continue
        print(f"KEGG {code}: inconsistent gene/pathway links; refreshing catalogs", flush=True)
        refresh(f"/list/{code}", gene_file)
        if "gene_pathway" in bad:
            refresh(f"/list/pathway/{code}", pathway_file)
        # A deleted gene can remain in an older relation export even after the
        # gene catalog is refreshed. Refresh only relations still unresolved.
        for suffix in unresolved():
            refresh(sources[suffix], f"relations/{code}_{suffix}.tsv")
        if remaining := unresolved():
            genes = {row[0] for row in tabular_rows(ROOT / gene_file, columns=4)}
            pathways = {p for p, _ in pairs(ROOT, pathway_file)}
            for gene, target in remaining.get("gene_pathway", []):
                if (
                    gene in genes or not gene.startswith(code + ":")
                    or strip_prefix(target) not in pathways or gene in evidence
                ):
                    continue
                url = BASE_URL + f"/get/{gene}"
                print(f"Verifying absent KEGG gene: {url}", flush=True)
                try:
                    payload = client.get(url, lambda response: response.read())
                except urllib.error.HTTPError as error:
                    if error.code != 404:
                        raise
                    evidence[gene] = {
                        "url": url, "status": 404,
                        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                else:
                    check_payload(f"/get/{gene}", payload)
            remaining = {
                suffix: [
                    (gene, target) for gene, target in entries
                    if not (suffix == "gene_pathway" and gene in evidence
                            and strip_prefix(target) in pathways)
                ]
                for suffix, entries in remaining.items()
            }
            if any(remaining.values()):
                sample = {suffix: entries[:5] for suffix, entries in remaining.items() if entries}
                raise ValueError(
                    f"Inconsistent KEGG {code} relationships after targeted refresh: {sample}. "
                    "Upstream catalogs and links still disagree; retry download-kegg later."
                )
    atomic_json(ROOT / "missing_gene_checks.json", evidence)


def reconcile_ko_catalog(codes, client, metadata):
    """Refresh stale catalogs, then independently verify dangling KO/EC links."""
    def missing():
        kos = {ko for ko, _ in pairs(ROOT, "ko/ko_list.tsv")}
        genes = {
            ko for code in codes for _, ko in pairs(ROOT, f"relations/{code}_gene_ko.tsv")
        }
        direct = {
            ko for kind in ("pathway", "ec", "reaction")
            for ko, _ in pairs(ROOT, f"relations/ko_{kind}.tsv")
        }
        return (genes | direct) - kos, genes - kos

    absent, gene_orphans = missing()
    if absent:
        print("KEGG relationships reference missing KOs; refreshing the KO catalog", flush=True)
        fetch("/list/ko", "ko/ko_list.tsv", client=client, metadata=metadata, refresh=True)
        absent, gene_orphans = missing()
    if gene_orphans:
        raise ValueError(
            "KEGG gene assignments still reference missing KOs after catalog refresh: "
            + ", ".join(sorted(gene_orphans))
            + ". Retry download-kegg --refresh with the same organism selection."
        )
    ec_kos = {ko for ko, _ in pairs(ROOT, "relations/ko_ec.tsv")}
    evidence = {}
    for ko in sorted(absent & ec_kos):
        url = BASE_URL + f"/get/{ko}"
        print(f"Verifying absent KEGG KO: {url}", flush=True)
        try:
            payload = client.get(url, lambda response: response.read())
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            evidence[ko] = {
                "url": url, "status": 404,
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        else:
            check_payload(f"/get/{ko}", payload)
            raise ValueError(
                f"KEGG KO {ko} exists but is absent from the refreshed catalog. "
                "Retry download-kegg later; the upstream exports are inconsistent."
            )
    atomic_json(ROOT / "missing_ko_checks.json", evidence)


def fetch(endpoint, relative, dry_run=False, *, client=None, metadata=None, refresh=False):
    path = ROOT / relative
    url = BASE_URL + endpoint
    print(f"GET {url} -> {relative}", flush=True)
    if dry_run:
        return
    metadata = acquisition_manifest(ROOT) if metadata is None else metadata
    item = metadata.get(relative)
    if not refresh and path.is_file():
        try:
            if not item or item["url"] != url or sha256(path) != item["sha256"]:
                raise ValueError("Missing/mismatched acquisition checksum or request")
            check_payload(endpoint, path.read_bytes())
        except (OSError, ValueError) as error:
            print(f"Invalid KEGG cache: {relative}: {error}", flush=True)
        else:
            return
    client = client or HttpClient()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")

    def consume(response):
        payload = response.read()
        check_payload(endpoint, payload)
        return payload

    try:
        payload = client.get(url, consume)
        temporary.write_bytes(payload)
        temporary.replace(path)
        item = {
            "url": url,
            "file": relative,
            "sha256": sha256(path),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
        with (ROOT / "manifest.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(item) + "\n")
        metadata[relative] = item
    finally:
        temporary.unlink(missing_ok=True)


def run(dry_run=False, codes=None, refresh=False, interval=1.0, attempts=4):
    codes = select(codes)
    client = HttpClient(interval, attempts)
    tasks = requests(codes)
    print(f"KEGG: {len(codes)} organisms, {len(tasks)} base requests plus detail batches.")
    if dry_run:
        for endpoint, relative in tasks:
            fetch(endpoint, relative, True)
        print("Reaction and compound detail batches are derived from these responses.")
        return
    with file_lock(ROOT / ".acquisition.lock"):
        metadata = acquisition_manifest(ROOT)
        selection_state(ROOT, codes, "incomplete")
        for index, (endpoint, relative) in enumerate(tasks, 1):
            print(f"KEGG base {index}/{len(tasks)}", flush=True)
            fetch(endpoint, relative, client=client, metadata=metadata, refresh=refresh)
        reconcile_organism_catalogs(codes, client, metadata)
        reconcile_ko_catalog(codes, client, metadata)
        for category, identifiers in selected_details(ROOT, codes).items():
            identifiers = sorted(identifiers)
            directory = ROOT / "details" / category
            files = []
            for offset in range(0, len(identifiers), 10):
                batch = identifiers[offset : offset + 10]
                relative = f"batches/{category}/{batch[0]}__{batch[-1]}.txt"
                fetch(
                    "/get/" + "+".join(batch),
                    relative,
                    client=client,
                    metadata=metadata,
                    refresh=refresh,
                )
                with (ROOT / relative).open(encoding="utf-8") as stream:
                    for record in flat_records(stream, relative):
                        identifier = record["ENTRY"][0].split()[0]
                        path = directory / "records" / f"{identifier}.txt"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        text = (
                            "".join(
                                f"{field if i == 0 else '':<12}{value}\n"
                                for field, values in record.items()
                                for i, value in enumerate(values)
                            )
                            + "///\n"
                        )
                        temporary = path.with_suffix(".part")
                        temporary.write_text(text, encoding="utf-8")
                        temporary.replace(path)
                        files.append(
                            {"file": path.relative_to(directory).as_posix(), "sha256": sha256(path)}
                        )
                print(
                    f"KEGG {category}: {min(offset + 10, len(identifiers))}/{len(identifiers)}",
                    flush=True,
                )
            atomic_json(directory / "active.json", files)
        selection_state(ROOT, codes, "complete")
