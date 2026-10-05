"""Reviewed UniProt acquisition with verified caches and resumable TSV pages."""

from __future__ import annotations

import gzip
import io
import json
import re
import urllib.parse
import urllib.request
import uuid
import zlib
from contextlib import nullcontext
from datetime import datetime, timezone

from unikegg import tsv
from unikegg.acquire.common import HttpClient, atomic_json, file_lock, selection_state
from unikegg.config import RAW as RAW_ROOT
from unikegg.dataset import sha256
from unikegg.organisms import BY_CODE, CATALOG, DEFAULT_CODES, select

RAW = RAW_ROOT / "uniprot"
URL = "https://rest.uniprot.org/uniprotkb/stream"
ORGANISMI = tuple((BY_CODE[c].taxid, c) for c in DEFAULT_CODES)
CAMPI = (
    "accession",
    "id",
    "reviewed",
    "protein_name",
    "gene_primary",
    "gene_synonym",
    "organism_name",
    "organism_id",
    "length",
    "mass",
    "protein_existence",
    "sequence",
    "sequence_version",
    "version",
    "date_created",
    "date_modified",
    "date_sequence_modified",
    "cc_alternative_products",
    "ft_var_seq",
    "go",
    "go_id",
    "go_p",
    "go_f",
    "go_c",
    "ec",
    "xref_kegg",
    "xref_pdb",
    "rhea",
    "keyword",
    "cc_function",
    "cc_catalytic_activity",
    "cc_pathway",
    "cc_subunit",
    "cc_subcellular_location",
    "cc_ptm",
    "cc_disease",
    "cc_interaction",
    "ft_signal",
    "ft_transmem",
    "ft_domain",
    "ft_act_site",
    "ft_binding",
    "ft_mod_res",
    "ft_carbohyd",
    "ft_disulfid",
    "ft_variant",
)

REQUIRED_COLUMNS = {
    "Entry",
    "Reviewed",
    "Organism (ID)",
    "Entry Name",
    "Protein names",
    "Sequence",
    "Length",
    "Mass",
    "Protein existence",
    "Sequence version",
    "KEGG",
    "Alternative products (isoforms)",
    "Gene Ontology IDs",
    "EC number",
    "Gene Ontology (biological process)",
    "Gene Ontology (molecular function)",
    "Gene Ontology (cellular component)",
}


def crea_url(query: str, formato: str, campi=()) -> str:
    parameters = {"query": query, "format": formato, "compressed": "true"}
    if campi:
        parameters["fields"] = ",".join(campi)
    return URL + "?" + urllib.parse.urlencode(parameters)


def controlla_gzip(path):
    size = 0
    with gzip.open(path, "rb") as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
    if not size:
        raise ValueError("Empty gzip archive")


def validate_tsv(stream, taxid=None):
    reader = tsv.dict_reader(stream)
    required = REQUIRED_COLUMNS if taxid else {"Entry", "Reviewed"}
    if not reader.fieldnames or not required <= set(reader.fieldnames):
        raise ValueError("Missing UniProt TSV columns")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("Duplicate UniProt TSV columns")
    seen = set()
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("Malformed UniProt TSV row")
        accession = row["Entry"]
        if not accession or accession in seen or row["Reviewed"] != "reviewed":
            raise ValueError("Missing/duplicate accession or non-reviewed UniProt record")
        if taxid and row["Organism (ID)"] != taxid:
            raise ValueError("Wrong UniProt organism")
        seen.add(accession)
    return reader.fieldnames, len(seen)


def query_taxid(url):
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("query", [""])[0]
    match = re.search(r"organism_id:(\d+)", query)
    return match[1] if match else None


def validate_export(path, url):
    controlla_gzip(path)
    if ".tsv.gz" in path.name:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
            return validate_tsv(stream, query_taxid(url))[1]
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        result = json.load(stream)
    if not isinstance(result, dict) or not isinstance(result.get("results"), list):
        raise ValueError("Invalid UniProt JSON export")
    taxid = query_taxid(url)
    for row in result["results"]:
        if row.get("entryType") != "UniProtKB reviewed (Swiss-Prot)" or (
            taxid and str(row.get("organism", {}).get("taxonId")) != taxid
        ):
            raise ValueError("Wrong organism or non-reviewed UniProt JSON record")
    return len(result["results"])


def acquisition_manifest():
    path = RAW / "manifest.jsonl"
    result = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if (
                not isinstance(item, dict)
                or not all(isinstance(item.get(key), str) for key in ("file", "url", "sha256"))
                or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
            ):
                raise ValueError("Invalid UniProt acquisition manifest")
            result[item["file"]] = item
    return result


def cached(path, url, metadata):
    key = path.relative_to(RAW_ROOT).as_posix()
    item = metadata.get(key)
    if not path.is_file() or not item or item["url"] != url or sha256(path) != item["sha256"]:
        return False
    try:
        count = validate_export(path, url)
        if item.get("records", count) != count:
            return False
    except (OSError, EOFError, zlib.error, ValueError):
        return False
    return True


def record(path, url, metadata, **extra):
    item = {
        "url": url,
        "file": path.relative_to(RAW_ROOT).as_posix(),
        "sha256": sha256(path),
        "byte": path.stat().st_size,
        "data_utc": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    with (RAW / "manifest.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(item) + "\n")
    metadata[item["file"]] = item


def scarica(
    url, destinazione, dry_run=False, *, client=None, metadata=None, refresh=False, refresh_id=None
):
    print("GET", url, "->", destinazione, flush=True)
    if dry_run:
        return
    client = client or HttpClient(timeout=300)
    metadata = acquisition_manifest() if metadata is None else metadata
    item = metadata.get(destinazione.relative_to(RAW_ROOT).as_posix(), {})
    if (
        not refresh
        and (refresh_id is None or item.get("refresh_id") == refresh_id)
        and cached(destinazione, url, metadata)
    ):
        print("Verified UniProt cache reused", flush=True)
        return
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    temporary = destinazione.with_name(destinazione.name + ".part")

    def consume(response):
        with temporary.open("wb") as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
        # Keep the final extension for format selection while checking a .part file.
        count = validate_export(temporary, url)
        return count, dict(getattr(response, "headers", {}))

    try:
        count, headers = client.get(url, consume)
        temporary.replace(destinazione)
        record(
            destinazione,
            url,
            metadata,
            records=count,
            release=headers.get("X-UniProt-Release", headers.get("x-uniprot-release")),
            refresh_id=refresh_id,
        )
    finally:
        temporary.unlink(missing_ok=True)


def search_url(stream_url):
    parsed = urllib.parse.urlsplit(stream_url)
    parameters = urllib.parse.parse_qs(parsed.query)
    parameters.pop("compressed", None)
    parameters["size"] = ["500"]
    parameters["sort"] = ["accession asc"]
    return "https://rest.uniprot.org/uniprotkb/search?" + urllib.parse.urlencode(
        parameters, doseq=True
    )


def next_page(link):
    # Commas are legal inside the URL (notably the fields parameter).
    # Splitting this header on commas would truncate real UniProt links.
    for match in re.finditer(r'<([^>]+)>\s*;\s*rel="?([^";,\s]+)"?', link):
        if match[2] == "next":
            url = match[1]
            parsed = urllib.parse.urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "rest.uniprot.org"
                or parsed.path != "/uniprotkb/search"
            ):
                raise ValueError("Untrusted UniProt pagination URL")
            return url
    return None


def paginated(url, destination, client, metadata, refresh=False, refresh_id=None):
    item = metadata.get(destination.relative_to(RAW_ROOT).as_posix(), {})
    initial = search_url(url)
    directory = RAW / ".pages" / destination.name
    checkpoint = directory / "state.json"
    state = json.loads(checkpoint.read_text()) if checkpoint.exists() and not refresh else None
    if state and (
        state.get("request") != initial
        or (refresh_id is not None and state.get("refresh_id") != refresh_id)
    ):
        state = None
    if (
        not refresh
        and (refresh_id is None or item.get("refresh_id") == refresh_id)
        # A newer checkpoint takes precedence over a still-valid old export,
        # even if its last page was saved just before publication failed.
        and (state is None or item.get("generation") == state["generation"])
        and item.get("release")
        and "records" in item
        and cached(destination, url, metadata)
    ):
        print(f"Verified UniProt cache reused: {destination.name}", flush=True)
        return
    directory.mkdir(parents=True, exist_ok=True)
    if state:
        # Only a verified contiguous prefix can be resumed. A damaged page is
        # downloaded again, starting from its request URL.
        for index, page in enumerate(state["pages"]):
            path = directory / page["file"]
            if not path.is_file() or sha256(path) != page["sha256"]:
                state["pages"] = state["pages"][:index]
                state["next"] = page["url"]
                break
    if not state:
        state = {
            "request": initial,
            "generation": uuid.uuid4().hex,
            "refresh_id": refresh_id,
            "next": initial,
            "release": None,
            "total": None,
            "pages": [],
        }
    atomic_json(checkpoint, state)
    visited = {p["url"] for p in state["pages"]}
    while state["next"]:
        page_url = state["next"]
        if page_url in visited:
            raise ValueError("Repeated UniProt pagination cursor")

        def consume(response):
            payload = response.read()
            text = payload.decode("utf-8")
            header, count = validate_tsv(io.StringIO(text), query_taxid(url))
            release = response.headers.get("X-UniProt-Release")
            total = response.headers.get("X-Total-Results")
            if not release or total is None or not total.isdigit():
                raise ValueError("Missing UniProt release/count metadata")
            return (
                payload,
                header,
                count,
                release,
                int(total),
                next_page(response.headers.get("Link", "")),
            )

        payload, header, count, release, total, following = client.get(page_url, consume)
        if state["release"] is not None and (
            state["release"] != release or state["total"] != total
        ):
            raise ValueError(
                "UniProt release/count changed during pagination; restart with --refresh"
            )
        if state["pages"] and header != state["header"]:
            raise ValueError("UniProt columns changed during pagination")
        if following and not count:
            raise ValueError("Empty UniProt page with a next cursor")
        state.update(release=release, total=total, header=header)
        name = f"{state['generation']}-{len(state['pages']):06d}.tsv"
        path = directory / name
        path.write_bytes(payload)
        state["pages"].append(
            {"file": name, "url": page_url, "sha256": sha256(path), "records": count}
        )
        state["next"] = following
        atomic_json(checkpoint, state)
        visited.add(page_url)
        print(
            f"{destination.name}: {sum(p['records'] for p in state['pages'])}/{total} proteins",
            flush=True,
        )
    if sum(p["records"] for p in state["pages"]) != state["total"]:
        raise ValueError("Incomplete UniProt pagination: count mismatch")
    temporary = destination.with_name(destination.name + ".part")
    try:
        with gzip.open(temporary, "wt", encoding="utf-8", newline="") as output:
            writer = tsv.writer(output)
            writer.writerow(state["header"])
            for page in state["pages"]:
                with (directory / page["file"]).open(encoding="utf-8", newline="") as stream:
                    reader = tsv.reader(stream)
                    next(reader)
                    writer.writerows(reader)
        count = validate_export(temporary, url)
        if count != state["total"]:
            raise ValueError("UniProt merged record count mismatch")
        temporary.replace(destination)
        record(
            destination,
            url,
            metadata,
            records=count,
            release=state["release"],
            generation=state["generation"],
            refresh_id=state.get("refresh_id"),
        )
    finally:
        temporary.unlink(missing_ok=True)


def planned_requests(codes=None, include_json=False):
    tasks = []
    for code in select(codes):
        taxid = BY_CODE[code].taxid
        query = f"(organism_id:{taxid}) AND (reviewed:true)"
        current = RAW / f"{taxid}_{code}.tsv.gz"
        legacy = RAW / f"{taxid}_{code}.index.tsv.gz"
        if current.exists() and legacy.exists():
            raise ValueError(f"Duplicate UniProt exports: {current.name} and {legacy.name}")
        if include_json:
            tasks.append((crea_url(query, "json"), RAW / f"{taxid}_{code}.json.gz"))
        tasks.append((crea_url(query, "tsv", CAMPI), legacy if legacy.exists() else current))
    return tasks


def plan_batches(codes=None, batch_size=None, batch=None):
    """Return numbered groups in catalog order, optionally selecting just one."""
    codes = select(codes)
    if batch_size is not None and (
        type(batch_size) is not int or not 1 <= batch_size <= len(CATALOG)
    ):
        raise ValueError(f"--batch-size must be between 1 and {len(CATALOG)}")
    if batch is not None and batch_size is None:
        raise ValueError("--batch requires --batch-size")
    size = batch_size or len(codes)
    groups = [codes[start : start + size] for start in range(0, len(codes), size)]
    if batch is not None and (type(batch) is not int or not 1 <= batch <= len(groups)):
        raise ValueError(f"--batch must be between 1 and {len(groups)}")
    return [
        (f"UniProt batch {index}/{len(groups)}: {','.join(group)}", group)
        for index, group in enumerate(groups, 1)
        if batch is None or batch == index
    ]


def run(
    dry_run=False, codes=None, include_json=False, refresh=False, interval=1.0, attempts=4,
    *, batch_size=None, batch=None, append=False,
):
    groups = plan_batches(codes, batch_size, batch)
    requested = tuple(code for _, group in groups for code in group)
    client = HttpClient(interval, attempts, timeout=300)
    with nullcontext() if dry_run else file_lock(RAW / ".acquisition.lock"):
        previous_path = RAW / "selection.json"
        previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
        codes = requested
        if append and previous:
            if (
                previous.get("version") != 1
                or not isinstance(previous.get("codes"), list)
                or previous.get("status") not in {"complete", "incomplete"}
            ):
                raise ValueError("Invalid UniProt selection manifest")
            retained = tuple(code for code in select(previous["codes"]) if code not in requested)
            if previous["status"] == "incomplete" and (
                previous.get("requested_codes", previous["codes"]) != list(requested)
                or previous.get("include_json", False) != include_json
            ):
                raise ValueError(
                    "Incomplete UniProt acquisition; resume the same selection and formats "
                    "before appending another batch"
                )
            codes = select([*retained, *requested])
            if retained:
                groups = [(f"Retained UniProt organisms: {','.join(retained)}", retained), *groups]
        # Build the entire plan before changing the selection manifest. This also
        # catches ambiguous current/legacy exports, including in retained groups.
        task_groups = [(label, planned_requests(group, include_json)) for label, group in groups]
        tasks = [task for _, group in task_groups for task in group]
        if dry_run:
            for label, group in task_groups:
                print(label)
                for url, destination in group:
                    print(
                        "GET", search_url(url) if ".tsv.gz" in destination.name else url,
                        "->", destination,
                    )
            print("TSV uses resumable pages of up to 500 proteins; no requests sent.")
            return
        metadata = acquisition_manifest()
        # Persist the refresh scope so a resumed job also refreshes exports it
        # had not reached, rather than mixing their old caches with new pages.
        refresh_id = (
            uuid.uuid4().hex
            if refresh
            else (
                previous.get("refresh_id")
                if previous.get("status") == "incomplete" and previous.get("codes") == list(codes)
                else None
            )
        )
        selection_state(
            RAW, codes, "incomplete", refresh_id=refresh_id,
            requested_codes=list(requested), include_json=include_json,
        )
        releases = set()
        labels = {group[0][1]: label for label, group in task_groups}
        for index, (url, destination) in enumerate(tasks, 1):
            if destination in labels:
                print(labels[destination], flush=True)
            print(f"UniProt export {index}/{len(tasks)}: {destination.name}", flush=True)
            if ".tsv.gz" in destination.name:
                paginated(url, destination, client, metadata, refresh, refresh_id)
            else:
                scarica(
                    url,
                    destination,
                    client=client,
                    metadata=metadata,
                    refresh=refresh,
                    refresh_id=refresh_id,
                )
            item = metadata[destination.relative_to(RAW_ROOT).as_posix()]
            if item.get("release"):
                releases.add(item["release"])
            if len(releases) > 1:
                raise ValueError(
                    "Mixed UniProt releases; repeat all selected exports with --refresh"
                )
        selection_state(
            RAW,
            codes,
            "complete",
            files=[p.name for _, p in tasks],
            release=next(iter(releases), None),
            requested_codes=list(requested),
            include_json=include_json,
        )


def main():
    import sys

    from unikegg.cli import main as cli_main

    cli_main(["download-uniprot", *sys.argv[1:]])


if __name__ == "__main__":
    main()
