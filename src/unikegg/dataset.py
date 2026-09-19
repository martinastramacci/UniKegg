"""Dataset contracts, provenance manifests and pre-ingestion validation."""

import csv
import hashlib
import json
import re
from pathlib import Path

TABLES = json.loads(Path(__file__).with_name("schema.json").read_text(encoding="utf-8"))
CODES = {"hsa", "mmu", "rno", "dre", "dme", "cel", "ath", "sce", "eco", "bsu"}


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rows(directory, table):
    with (Path(directory) / table["file"]).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != table["columns"]:
            raise ValueError(f"Header mismatch: {table['file']}")
        yield from reader


def manifest(directory, kind, reviewed=None):
    """Verify the accession scope before declaring Swiss-Prot provenance."""
    if kind not in {"swissprot", "synthetic"}:
        raise ValueError("Unknown dataset kind")
    if kind == "swissprot" and reviewed is None:
        raise ValueError("Swiss-Prot manifests require reviewed upstream records")
    directory = Path(directory)
    counts = {}
    for table in TABLES:
        count = 0
        for row in rows(directory, table):
            if table["name"] == "PROTEIN_UNIPROT" and kind == "swissprot":
                if row["accession"] not in reviewed:
                    raise ValueError(
                        f"Protein outside verified Swiss-Prot scope: {row['accession']}"
                    )
            count += 1
        counts[table["file"]] = {"rows": count, "sha256": sha256(directory / table["file"])}
    content = {
        "format_version": 1,
        "dataset_kind": kind,
        "reviewed_only": kind == "swissprot",
        "files": counts,
    }
    (directory / "manifest.json").write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    return content


def validate(directory, expected_kind="swissprot"):
    directory = Path(directory).resolve()
    report = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if report.get("format_version") != 1 or report.get("dataset_kind") != expected_kind:
        raise ValueError("Manifest version or dataset kind mismatch")
    if expected_kind == "swissprot" and report.get("reviewed_only") is not True:
        raise ValueError("Swiss-Prot provenance declaration is required")
    if set(report["files"]) != {t["file"] for t in TABLES}:
        raise ValueError("Expected twenty dataset files")
    parent_columns = {(fk["parent"], fk["target"]) for t in TABLES for fk in t["fk"]}
    values = {key: set() for key in parent_columns}
    references, organisms, codes = [], {}, set()
    for table in TABLES:
        name, path = table["name"], directory / table["file"]
        if sha256(path) != report["files"][table["file"]]["sha256"]:
            raise ValueError(f"Checksum mismatch: {path.name}")
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                if b"\r" in chunk:
                    raise ValueError(f"Expected LF line endings: {path.name}")
        primary = set()
        reference_values = {fk["column"]: set() for fk in table["fk"]}
        parent_keys = [key for key in parent_columns if key[0] == name]
        widths = {
            c: int(m.group(1))
            for c, s in table["specs"].items()
            if (m := re.match(r"(?:VAR)?CHAR\((\d+)\)", s))
        }
        integers = [c for c, s in table["specs"].items() if s.startswith("INT UNSIGNED")]
        enums = {
            c: re.findall(r"'([^']+)'", s)
            for c, s in table["specs"].items()
            if s.startswith("ENUM")
        }
        required = set(table["columns"]) - set(table["nullable"])
        count = 0
        for row in rows(directory, table):
            count += 1
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"Invalid column count: {path.name}:{count + 1}")
            key = tuple(row[c] for c in table["pk"])
            if any(not v for v in key) or key in primary:
                raise ValueError(f"Missing/duplicate key: {name}:{count + 1}")
            primary.add(key)
            if any(not row[c] for c in required):
                raise ValueError(f"Required value missing: {name}")
            if any(len(row[c]) > n for c, n in widths.items()):
                raise ValueError(f"Value exceeds column width: {name}")
            if any(not row[c].isdigit() or int(row[c]) > 4294967295 for c in integers):
                raise ValueError(f"Invalid unsigned integer: {name}")
            if any(row[c] not in domain for c, domain in enums.items()):
                raise ValueError(f"Invalid enum: {name}")
            if name == "PROTEIN_UNIPROT":
                seq = row["amino_acid_sequence"]
                if len(seq) != int(row["sequence_length"]) or not re.fullmatch(r"[A-Z]+", seq):
                    raise ValueError(f"Invalid protein sequence: {row['accession']}")
                if int(row["molecular_mass"]) <= 0:
                    raise ValueError("Protein mass must be positive")
            if name == "ORGANISMO":
                codes.add(row["kegg_code"])
            if name in {"GENE_KEGG", "PROTEIN_UNIPROT", "PATHWAY_ORGANISMO"}:
                organisms[(name, row[table["pk"][0]])] = row["organism_id"]
            if name == "PROTEIN_ISOFORM" and not row["isoform_id"].startswith(
                row["accession"] + "-"
            ):
                raise ValueError("Isoform parent mismatch")
            if name in {"GENE_PROTEINA", "GENE_PATHWAY"}:
                other = (
                    ("PROTEIN_UNIPROT", row["accession"])
                    if name == "GENE_PROTEINA"
                    else ("PATHWAY_ORGANISMO", row["pathway_id"])
                )
                if organisms.get(("GENE_KEGG", row["kegg_gene_id"])) != organisms.get(other):
                    raise ValueError(f"Organism mismatch: {name}")
            for parent_key in parent_keys:
                values[parent_key].add(row[parent_key[1]])
            for column in reference_values:
                reference_values[column].add(row[column])
        if count != report["files"][table["file"]]["rows"]:
            raise ValueError(f"Row count mismatch: {name}")
        for fk in table["fk"]:
            references.append((name, fk, reference_values[fk["column"]]))
    if codes != CODES:
        raise ValueError("Dataset must cover the configured ten organisms")
    for name, fk, child_values in references:
        if child_values - values[(fk["parent"], fk["target"])]:
            raise ValueError(f"Orphan reference: {name}.{fk['column']}")
    print(
        json.dumps({"event": "dataset_validated", "tables": 20, "kind": expected_kind}), flush=True
    )
    return report, sha256(directory / "manifest.json")
