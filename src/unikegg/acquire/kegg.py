"""Explicit, rate-limited KEGG acquisition; never executed by the demo."""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from unikegg.config import RAW
from unikegg.dataset import CODES, sha256

ROOT = RAW / "kegg"
BASE_URL = "https://rest.kegg.jp"


def fetch(endpoint, relative, dry_run=False):
    path = ROOT / relative
    url = BASE_URL + endpoint
    print(f"GET {url} -> {relative}", flush=True)
    if dry_run:
        return
    if path.is_file() and path.stat().st_size:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    for attempt in range(4):
        try:
            time.sleep(0.4)
            request = urllib.request.Request(url, headers={"User-Agent": "UniKegg/0.1"})
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = response.read()
            if not payload.strip():
                raise ValueError(f"Empty response: {endpoint}")
            if endpoint.startswith("/get/"):
                wanted = set(endpoint.removeprefix("/get/").split("+"))
                found = {
                    line.split()[1]
                    for line in payload.decode().splitlines()
                    if line.startswith("ENTRY ")
                }
                if found != wanted or not payload.rstrip().endswith(b"///"):
                    raise ValueError(f"Incomplete KEGG record batch: {endpoint}")
            temporary.write_bytes(payload)
            temporary.replace(path)
            with (ROOT / "manifest.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "url": url,
                            "file": relative,
                            "sha256": sha256(path),
                            "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    + "\n"
                )
            return
        except (OSError, urllib.error.URLError, ValueError):
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))


def pairs(relative):
    for line in (ROOT / relative).read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) >= 2:
            yield tuple(value.split(":", 1)[-1] for value in fields[:2])


def linked(relative, selected, prefix):
    result = set()
    for left, right in pairs(relative):
        if left in selected and right.startswith(prefix):
            result.add(right)
        if right in selected and left.startswith(prefix):
            result.add(left)
    return result


def run(dry_run=False):
    tasks = [
        ("/list/genome", "organism/organism_list.tsv"),
        ("/list/ko", "ko/ko_list.tsv"),
        ("/list/pathway", "pathway/pathway_reference.tsv"),
        ("/link/reaction/ko", "relations/ko_reaction.tsv"),
        ("/link/reaction/pathway", "relations/pathway_reaction.tsv"),
        ("/link/compound/reaction", "relations/reaction_compound.tsv"),
    ]
    for code in sorted(CODES):
        tasks.extend(
            [
                (f"/list/{code}", f"genes/{code}_genes.tsv"),
                (f"/list/pathway/{code}", f"pathway/{code}_pathways.tsv"),
                (f"/link/pathway/{code}", f"relations/{code}_gene_pathway.tsv"),
                (f"/link/ko/{code}", f"relations/{code}_gene_ko.tsv"),
                (f"/conv/uniprot/{code}", f"relations/{code}_uniprot.tsv"),
            ]
        )
    for endpoint, relative in tasks:
        fetch(endpoint, relative, dry_run)
    if dry_run:
        print("Reaction and compound detail batches are derived from these responses.")
        return
    orthologies, pathways = set(), set()
    for code in CODES:
        orthologies.update(right for _, right in pairs(f"relations/{code}_gene_ko.tsv"))
        pathways.update(left for left, _ in pairs(f"pathway/{code}_pathways.tsv"))
    pathways.update("map" + value[-5:] for value in list(pathways))
    reactions = linked("relations/ko_reaction.tsv", orthologies, "R")
    reactions |= linked("relations/pathway_reaction.tsv", pathways, "R")
    compounds = linked("relations/reaction_compound.tsv", reactions, "C")
    for category, identifiers in [("reaction", reactions), ("compound", compounds)]:
        identifiers = sorted(identifiers)
        for offset in range(0, len(identifiers), 10):
            batch = identifiers[offset : offset + 10]
            fetch("/get/" + "+".join(batch), f"details/{category}/{batch[0]}__{batch[-1]}.txt")
