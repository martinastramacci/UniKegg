"""Strict KEGG raw parsing and shared acquisition/transform selection rules."""

import io
import json
import re
from pathlib import Path

from unikegg.dataset import CODES, sha256


def strip_prefix(value):
    return value.split(":", 1)[-1]


def tabular_lines(lines, source, columns=2, allow_empty=True):
    count = 0
    for number, line in enumerate(lines, 1):
        # KEGG tabular responses are plain TSV, not CSV-quoted text.
        fields = line.rstrip("\r\n").split("\t")
        if len(fields) != columns or not fields[0]:
            raise ValueError(f"Malformed KEGG TSV: {source}:{number}; expected {columns} columns")
        count += 1
        yield fields
    if not count and not allow_empty:
        raise ValueError(f"Empty KEGG source: {source}")


def tabular_rows(path, columns=2, allow_empty=True):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        yield from tabular_lines(stream, str(path), columns, allow_empty)


def flat_records(lines, source):
    record, field = {}, None
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        if line.rstrip("\r\n") == "///":
            if not record.get("ENTRY") or not record["ENTRY"][0].split():
                raise ValueError(f"Missing KEGG ENTRY: {source}:{number}")
            yield record
            record, field = {}, None
            continue
        name, value = line[:12].strip(), line[12:].rstrip("\r\n")
        if not record and name != "ENTRY":
            raise ValueError(f"Expected KEGG ENTRY: {source}:{number}")
        if name == "ENTRY" and record:
            raise ValueError(f"Unterminated KEGG record: {source}:{number}")
        if name:
            field = name
            record.setdefault(field, []).append(value)
        elif field:
            record[field].append(value)
    if record:
        raise ValueError(f"Unterminated KEGG record at EOF: {source}")


def detail_records(directory, expected=None):
    """Require complete, unique records; empty details are valid only when selected so."""
    directory = Path(directory)
    paths = sorted(directory.glob("*.txt"))
    if not paths and (expected is None or expected):
        raise FileNotFoundError(f"Missing KEGG detail files: {directory}")
    seen = set()
    for path in paths:
        count = 0
        with path.open(encoding="utf-8") as stream:
            for record in flat_records(stream, str(path)):
                identifier = record["ENTRY"][0].split()[0]
                if identifier in seen:
                    raise ValueError(f"Duplicate KEGG ENTRY {identifier}: {path}")
                seen.add(identifier)
                count += 1
                yield record
        if not count:
            raise ValueError(f"Empty KEGG detail file: {path}")
    if expected is not None and (missing := set(expected) - seen):
        raise ValueError(f"Missing KEGG details in {directory}: {', '.join(sorted(missing)[:10])}")


def requests(codes=CODES):
    tasks = [
        ("/list/genome", "organism/organism_list.tsv"),
        ("/list/ko", "ko/ko_list.tsv"),
        ("/list/pathway", "pathway/pathway_reference.tsv"),
        ("/link/reaction/ko", "relations/ko_reaction.tsv"),
        ("/link/reaction/pathway", "relations/pathway_reaction.tsv"),
        ("/link/compound/reaction", "relations/reaction_compound.tsv"),
    ]
    for code in sorted(codes):
        tasks.extend(
            [
                (f"/list/{code}", f"genes/{code}_genes.tsv"),
                (f"/list/pathway/{code}", f"pathway/{code}_pathways.tsv"),
                (f"/link/pathway/{code}", f"relations/{code}_gene_pathway.tsv"),
                (f"/link/ko/{code}", f"relations/{code}_gene_ko.tsv"),
                (f"/conv/uniprot/{code}", f"relations/{code}_uniprot.tsv"),
            ]
        )
    return tasks


def check_payload(endpoint, payload):
    text = payload.decode("utf-8")
    if endpoint.startswith("/get/"):
        wanted = {strip_prefix(value) for value in endpoint.removeprefix("/get/").split("+")}
        found = [
            record["ENTRY"][0].split()[0] for record in flat_records(io.StringIO(text), endpoint)
        ]
        if len(found) != len(set(found)) or set(found) != wanted:
            raise ValueError(f"Incomplete/duplicate KEGG record batch: {endpoint}")
    else:
        genes = endpoint in {f"/list/{code}" for code in CODES}
        allow_empty = endpoint.startswith(("/link/", "/conv/", "/list/pathway/"))
        # Exhaust the generator so malformed trailing rows cannot go unnoticed.
        for _ in tabular_lines(io.StringIO(text), endpoint, 4 if genes else 2, allow_empty):
            pass


def acquisition_manifest(root):
    path = Path(root) / "manifest.jsonl"
    if not path.exists():
        return {}
    result = {}
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            try:
                item = json.loads(line)
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("file"), str)
                    or not isinstance(item.get("url"), str)
                    or not isinstance(item.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                ):
                    raise ValueError("missing acquisition metadata")
            except (ValueError, TypeError) as error:
                raise ValueError(f"Invalid KEGG manifest: {path}:{number}") from error
            result[item["file"]] = item
    return result


def pairs(root, relative):
    for fields in tabular_rows(Path(root) / relative):
        yield tuple(strip_prefix(value) for value in fields)


def linked(root, relative, selected, prefix):
    result = set()
    for left, right in pairs(root, relative):
        if left in selected and right.startswith(prefix):
            result.add(right)
        if right in selected and left.startswith(prefix):
            result.add(left)
    return result


def selected_details(root, codes=CODES):
    orthologies, pathways = set(), set()
    for code in sorted(codes):
        orthologies.update(right for _, right in pairs(root, f"relations/{code}_gene_ko.tsv"))
        pathways.update(left for left, _ in pairs(root, f"pathway/{code}_pathways.tsv"))
    pathways.update("map" + value[-5:] for value in list(pathways))
    reactions = linked(root, "relations/ko_reaction.tsv", orthologies, "R")
    reactions |= linked(root, "relations/pathway_reaction.tsv", pathways, "R")
    compounds = linked(root, "relations/reaction_compound.tsv", reactions, "C")
    return {"reaction": reactions, "compound": compounds}


def preflight(root, codes=CODES):
    """Fail before publishing output when required raw files/records are missing.

    Authorized manual exports need not have an acquisition manifest. If there is
    a recorded checksum, it must match. Shape and selected-ID completeness are
    checked even without acquisition metadata; missing upstream rows that never
    appear in any input cannot be inferred without an authoritative snapshot.
    """
    root = Path(root)
    metadata = acquisition_manifest(root)
    for endpoint, relative in requests(codes):
        path = root / relative
        if relative in metadata and sha256(path) != metadata[relative]["sha256"]:
            raise ValueError(f"KEGG raw checksum mismatch: {relative}")
        check_payload(endpoint, path.read_bytes())

    kos = {strip_prefix(row[0]) for row in tabular_rows(root / "ko/ko_list.tsv")}
    maps = {strip_prefix(row[0]) for row in tabular_rows(root / "pathway/pathway_reference.tsv")}
    for code in sorted(codes):
        gene_file = root / f"genes/{code}_genes.tsv"
        genes = [row[0] for row in tabular_rows(gene_file, columns=4, allow_empty=False)]
        if len(genes) != len(set(genes)) or any(not gene.startswith(code + ":") for gene in genes):
            raise ValueError(f"Duplicate/wrong-organism KEGG genes: {gene_file}")
        genes = set(genes)
        pathways = {
            strip_prefix(row[0]) for row in tabular_rows(root / f"pathway/{code}_pathways.tsv")
        }
        if any(not p.startswith(code) or "map" + p[-5:] not in maps for p in pathways):
            raise ValueError(f"Unresolved KEGG reference pathways: {code}")
        for suffix, valid_targets in [
            ("gene_ko", kos),
            ("gene_pathway", pathways),
            ("uniprot", None),
        ]:
            path = root / f"relations/{code}_{suffix}.tsv"
            for gene, target in tabular_rows(path):
                if gene not in genes or (
                    valid_targets is not None and strip_prefix(target) not in valid_targets
                ):
                    raise ValueError(
                        f"Unresolved KEGG source relationship: {path}: {gene}, {target}"
                    )

    selected = selected_details(root, codes)
    for category, expected in selected.items():
        directory = root / "details" / category
        for path in directory.glob("*.txt"):
            relative = path.relative_to(root).as_posix()
            if relative in metadata and sha256(path) != metadata[relative]["sha256"]:
                raise ValueError(f"KEGG raw checksum mismatch: {relative}")
        for _ in detail_records(directory, expected):
            pass
    return selected
