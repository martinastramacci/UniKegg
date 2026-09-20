"""Dataset contracts, provenance manifests and pre-ingestion validation."""

import csv
import hashlib
import json
import os
import re
import shutil
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from unikegg import tsv

TABLES = json.loads(Path(__file__).with_name("schema.json").read_text(encoding="utf-8"))
BY_NAME = {table["name"]: table for table in TABLES}
CODES = {"hsa", "mmu", "rno", "dre", "dme", "cel", "ath", "sce", "eco", "bsu"}
TEXT_LIMITS = {"TINYTEXT": 255, "TEXT": 65535, "MEDIUMTEXT": 16777215, "LONGTEXT": 4294967295}
UINT_RE = re.compile(r"[0-9]+")
DECIMAL_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
IDENTIFIER_RE = re.compile(r"[!-~]+")


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rows(directory, table):
    path = Path(directory) / table["file"]
    with path.open(encoding="utf-8", newline="") as stream:
        reader = tsv.reader(stream)
        try:
            if next(reader, None) != table["columns"]:
                raise ValueError(f"Header mismatch: {table['file']}")
            for fields in reader:
                if len(fields) != len(table["columns"]):
                    raise ValueError(f"Invalid column count: {path.name}:{reader.line_num}")
                yield dict(zip(table["columns"], fields, strict=True))
        except csv.Error as error:
            raise ValueError(f"Invalid TSV: {path.name}:{reader.line_num}: {error}") from error


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
    temporary = None
    try:
        with NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=directory, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(content, indent=2) + "\n")
        os.replace(temporary, directory / "manifest.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return content


def key_value(table, column, value):
    """Match MySQL integer / case-insensitive ASCII identifier equality.

    Keys and references are restricted to printable, non-space ASCII identifiers.
    Free-text annotations remain UTF-8. This avoids approximating Unicode UCA
    collation rules with Python casefold/normalization, which is not equivalent.
    """
    if table["specs"][column].startswith("INT UNSIGNED"):
        return int(value)
    return value.lower()


def _validators(table):
    widths, integers, enums, texts, decimals = {}, set(), {}, {}, {}
    for column, spec in table["specs"].items():
        if match := re.match(r"(?:VAR)?CHAR\((\d+)\)", spec):
            widths[column] = int(match[1])
        elif spec.startswith("INT UNSIGNED"):
            integers.add(column)
        elif spec.startswith("ENUM"):
            enums[column] = set(re.findall(r"'([^']+)'", spec))
        elif spec.split()[0] in TEXT_LIMITS:
            texts[column] = TEXT_LIMITS[spec.split()[0]]
        elif match := re.match(r"DECIMAL\((\d+),\s*(\d+)\)", spec):
            precision, scale = int(match[1]), int(match[2])
            decimals[column] = (Decimal(10) ** (precision - scale), scale)
    identifiers = set(table["pk"]) | {fk["column"] for fk in table["fk"]}
    identifiers.update(column for key in table.get("unique", []) for column in key)
    identifiers -= integers
    required = set(table["columns"]) - set(table["nullable"])
    patterns = {c: re.compile(p) for c, p in table.get("patterns", {}).items()}

    def check(row, location):
        if any(not row[c] for c in required):
            raise ValueError(f"Required value missing: {location}")
        for column in identifiers:
            if row[column] and not IDENTIFIER_RE.fullmatch(row[column]):
                raise ValueError(f"Expected printable ASCII identifier: {location}.{column}")
        if any(len(row[c]) > width for c, width in widths.items()):
            raise ValueError(f"Value exceeds column width: {location}")
        for column in integers:
            value = row[column]
            if value or column in required:
                if not UINT_RE.fullmatch(value) or len(value.lstrip("0")) > 10:
                    raise ValueError(f"Invalid unsigned integer: {location}.{column}")
                if int(value) > 4294967295:
                    raise ValueError(f"Invalid unsigned integer: {location}.{column}")
        for column, domain in enums.items():
            if (row[column] or column in required) and row[column] not in domain:
                raise ValueError(f"Invalid enum: {location}.{column}")
        for column, limit in texts.items():
            if len(row[column].encode("utf-8")) > limit:
                raise ValueError(f"Value exceeds text byte limit: {location}.{column}")
        for column, (bound, scale) in decimals.items():
            value = row[column]
            if not value and column not in required:
                continue
            try:
                number = Decimal(value)
                valid = (
                    DECIMAL_RE.fullmatch(value)
                    and number.is_finite()
                    and number.copy_abs() < bound
                    and number.as_tuple().exponent >= -scale
                )
            except (InvalidOperation, ValueError):
                valid = False
            if not valid:
                raise ValueError(f"Invalid decimal (range/scale): {location}.{column}")
        for column, minimum in table.get("minimum", {}).items():
            if int(row[column]) < minimum:
                raise ValueError(f"Value below minimum {minimum}: {location}.{column}")
        for column, pattern in patterns.items():
            if not pattern.fullmatch(row[column]):
                raise ValueError(f"Invalid domain: {location}.{column}")

    return check


def validate(directory, expected_kind="swissprot"):
    directory = Path(directory).resolve()
    report = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if (
        expected_kind not in {"swissprot", "synthetic"}
        or not isinstance(report, dict)
        or type(report.get("format_version")) is not int
        or report["format_version"] != 1
        or report.get("dataset_kind") != expected_kind
    ):
        raise ValueError("Manifest version or dataset kind mismatch")
    if expected_kind == "swissprot" and report.get("reviewed_only") is not True:
        raise ValueError("Swiss-Prot provenance declaration is required")
    files = report.get("files")
    if not isinstance(files, dict) or set(files) != {t["file"] for t in TABLES}:
        raise ValueError("Expected twenty dataset files")
    for filename, info in files.items():
        if (
            not isinstance(info, dict)
            or type(info.get("rows")) is not int
            or info["rows"] < 0
            or not isinstance(info.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", info["sha256"])
        ):
            raise ValueError(f"Invalid manifest file metadata: {filename}")
    parent_columns = {(fk["parent"], fk["target"]) for t in TABLES for fk in t["fk"]}
    values = {key: set() for key in parent_columns}
    references, organisms, codes = [], {}, set()
    for table in TABLES:
        name, path = table["name"], directory / table["file"]
        if sha256(path) != files[table["file"]]["sha256"]:
            raise ValueError(f"Checksum mismatch: {path.name}")
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                if b"\r" in chunk:
                    raise ValueError(f"Expected LF line endings: {path.name}")
        keys = [table["pk"], *table.get("unique", [])]
        seen_keys = [set() for _ in keys]
        reference_values = {fk["column"]: set() for fk in table["fk"]}
        parent_keys = [key for key in parent_columns if key[0] == name]
        check = _validators(table)
        count = 0
        for row in rows(directory, table):
            count += 1
            location = f"{name}:{count + 1}"
            check(row, location)
            for columns, seen in zip(keys, seen_keys, strict=True):
                # SQL UNIQUE permits multiple NULLs; primary keys never do.
                if columns != table["pk"] and any(not row[c] for c in columns):
                    continue
                key = tuple(key_value(table, c, row[c]) for c in columns)
                if key in seen:
                    raise ValueError(f"Missing/duplicate key: {location} ({', '.join(columns)})")
                seen.add(key)
            if name == "PROTEIN_UNIPROT":
                seq = row["amino_acid_sequence"]
                if len(seq) != int(row["sequence_length"]) or not re.fullmatch(r"[A-Z]+", seq):
                    raise ValueError(f"Invalid protein sequence: {row['accession']}")
            if name == "ORGANISMO":
                codes.add(row["kegg_code"])
            if name in {"GENE_KEGG", "PROTEIN_UNIPROT", "PATHWAY_ORGANISMO"}:
                identifier = key_value(table, table["pk"][0], row[table["pk"][0]])
                organisms[(name, identifier)] = int(row["organism_id"])
            if name == "PROTEIN_ISOFORM" and not row["isoform_id"].startswith(
                row["accession"] + "-"
            ):
                raise ValueError("Isoform parent mismatch")
            if name in {"GENE_PROTEINA", "GENE_PATHWAY"}:
                other = (
                    ("PROTEIN_UNIPROT", row["accession"].lower())
                    if name == "GENE_PROTEINA"
                    else ("PATHWAY_ORGANISMO", row["pathway_id"].lower())
                )
                if organisms.get(("GENE_KEGG", row["kegg_gene_id"].lower())) != organisms.get(
                    other
                ):
                    raise ValueError(f"Organism mismatch: {name}")
            for parent_key in parent_keys:
                values[parent_key].add(key_value(table, parent_key[1], row[parent_key[1]]))
            for fk in table["fk"]:
                value = row[fk["column"]]
                if value or fk["column"] not in table["nullable"]:
                    reference_values[fk["column"]].add(
                        key_value(BY_NAME[fk["parent"]], fk["target"], value)
                    )
        if count != files[table["file"]]["rows"]:
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


@contextmanager
def verified_snapshot(directory, kind):
    """Validate a private copy, never files the host can change during LOAD DATA."""
    with TemporaryDirectory(prefix="unikegg-load-") as temporary:
        snapshot = Path(temporary)
        for filename in ["manifest.json", *(table["file"] for table in TABLES)]:
            shutil.copyfile(Path(directory) / filename, snapshot / filename)
        report, fingerprint = validate(snapshot, kind)
        yield snapshot, report, fingerprint


def quote_for_mysql(directory):
    """Canonicalize a *private, validated* snapshot, including legacy bundles.

    This is a transport representation: the database fingerprint still identifies
    the original verified manifest, not these rewritten bytes. Never call this on
    the user's source bundle. A quoted copy is replaced one table at a time to
    limit additional temporary storage to the size of the largest table.
    """
    for table in TABLES:
        original = Path(directory) / table["file"]
        temporary = original.with_suffix(".quoted")
        try:
            with temporary.open("w", encoding="utf-8", newline="") as stream:
                writer = tsv.writer(stream)
                writer.writerow(table["columns"])
                for row in rows(directory, table):
                    writer.writerow([row[c] for c in table["columns"]])
            os.replace(temporary, original)
        finally:
            temporary.unlink(missing_ok=True)
