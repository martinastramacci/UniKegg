"""Fail closed when an upstream TSV is not explicitly marked reviewed."""

import gzip
import os
from pathlib import Path

from unikegg import tsv
from unikegg.config import RAW


def reviewed_rows(directory: Path | None = None):
    directory = Path(directory or os.environ.get("UNIKEGG_REVIEWED_DIR", RAW / "uniprot"))
    files = sorted(directory.rglob("*.tsv.gz"))
    if not files:
        raise FileNotFoundError(f"No UniProt TSV gzip exports in {directory}")
    seen = set()
    for path in files:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
            reader = tsv.dict_reader(stream)
            if not reader.fieldnames or not {"Entry", "Reviewed"} <= set(reader.fieldnames):
                raise ValueError(f"Reviewed status is required: {path.name}")
            if len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError(f"Duplicate upstream header: {path.name}")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(
                        f"Invalid upstream column count: {path.name}:{reader.line_num}"
                    )
                row["Entry"] = row["Entry"].strip()
                if row["Reviewed"].strip().lower() != "reviewed":
                    raise ValueError(f"Non-Swiss-Prot record rejected: {row.get('Entry')}")
                if not row["Entry"] or row["Entry"] in seen:
                    raise ValueError(f"Missing or duplicate upstream accession: {row['Entry']}")
                seen.add(row["Entry"])
                yield row
