"""Fail closed when an upstream TSV is not explicitly marked reviewed."""

import csv
import gzip
import os
from pathlib import Path

from unikegg.config import RAW


def reviewed_rows(directory: Path | None = None):
    directory = directory or Path(os.environ.get("UNIKEGG_REVIEWED_DIR", RAW / "uniprot"))
    csv.field_size_limit(16 * 1024 * 1024)
    files = sorted(directory.rglob("*.tsv.gz"))
    if not files:
        raise FileNotFoundError(f"No UniProt TSV gzip exports in {directory}")
    seen = set()
    for path in files:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            if not reader.fieldnames or not {"Entry", "Reviewed"} <= set(reader.fieldnames):
                raise ValueError(f"Reviewed status is required: {path.name}")
            for row in reader:
                if row["Reviewed"].strip().lower() != "reviewed":
                    raise ValueError(f"Non-Swiss-Prot record rejected: {row.get('Entry')}")
                if not row["Entry"] or row["Entry"] in seen:
                    raise ValueError(f"Missing or duplicate upstream accession: {row['Entry']}")
                seen.add(row["Entry"])
                yield row
