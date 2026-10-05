"""Fail closed when an upstream TSV is not explicitly marked reviewed."""

import gzip
import json
import os
from pathlib import Path

from unikegg import tsv
from unikegg.config import RAW
from unikegg.dataset import sha256
from unikegg.organisms import BY_CODE, DEFAULT_CODES, active_codes, recorded_selection


def reviewed_rows(directory: Path | None = None):
    directory = Path(directory or os.environ.get("UNIKEGG_REVIEWED_DIR", RAW / "uniprot"))
    codes = set(active_codes())
    state = recorded_selection(directory)
    if state and not codes <= set(state["codes"]):
        raise ValueError("UniProt acquisition does not cover selected organisms")
    if state:
        filenames = state.get("files", [])
        if any(Path(name).name != name for name in filenames):
            raise ValueError("Invalid UniProt selected file name")
        files = sorted(
            directory / name
            for name in filenames
            if name.endswith(".tsv.gz")
            and any(name.startswith(f"{BY_CODE[c].taxid}_{c}.") for c in codes)
        )
        metadata = {}
        for line in (directory / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            metadata[Path(item["file"]).name] = item
        for path in files:
            if path.name not in metadata or sha256(path) != metadata[path.name]["sha256"]:
                raise ValueError(f"UniProt raw checksum mismatch: {path.name}")
    else:
        files = sorted(directory.rglob("*.tsv.gz"))
    if not files:
        raise FileNotFoundError(f"No UniProt TSV gzip exports in {directory}")
    if state and len(files) != len(codes):
        raise ValueError("Missing/duplicate selected UniProt exports")
    selected_taxids = {BY_CODE[c].taxid for c in codes}
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
                # Manual legacy exports may contain a superset. Preserve the
                # default legacy gate, but scope smaller/extended selections.
                if not state and codes != set(DEFAULT_CODES):
                    taxid = row.get("Organism (ID)", "")
                    references = {
                        value.strip().split(":", 1)[0] for value in row.get("KEGG", "").split(";")
                    }
                    if taxid not in selected_taxids and not references & codes:
                        continue
                if state and row.get("Organism (ID)") != path.name.split("_", 1)[0]:
                    raise ValueError(f"Wrong UniProt organism in {path.name}")
                row["Entry"] = row["Entry"].strip()
                if row["Reviewed"].strip().lower() != "reviewed":
                    raise ValueError(f"Non-Swiss-Prot record rejected: {row.get('Entry')}")
                if not row["Entry"] or row["Entry"] in seen:
                    raise ValueError(f"Missing or duplicate upstream accession: {row['Entry']}")
                seen.add(row["Entry"])
                yield row
