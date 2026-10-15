"""Migrate an existing English TSV bundle without changing its source directory."""

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from unikegg import tsv
from unikegg.dataset import TABLES, sha256, validate
from unikegg.enzymes import EC_FIELDS, read_catalog
from unikegg.identifiers import without_ec_annotations
from unikegg.transforms.pipeline import output_lock, publish


def run(source, destination, enzyme_catalog):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents:
        raise ValueError("Destination must be separate from the source bundle")
    if destination.exists() and any(
        p.name != ".gitkeep" or not p.is_file() for p in destination.iterdir()
    ):
        raise ValueError("Destination must be absent or empty")
    catalog = read_catalog(enzyme_catalog)
    metadata = json.loads((source / "manifest.json").read_text())
    if set(metadata.get("files", {})) != {t["file"] for t in TABLES}:
        raise ValueError("Expected a complete English bundle with its manifest")
    destination.parent.mkdir(parents=True, exist_ok=True)
    changes = {}
    with output_lock(destination), TemporaryDirectory(dir=destination.parent) as temporary:
        stage = Path(temporary) / "processed"
        stage.mkdir()
        if (destination / ".gitkeep").is_file():
            shutil.copyfile(destination / ".gitkeep", stage / ".gitkeep")
        for table in TABLES:
            filename = table["file"]
            entry = metadata["files"][filename]
            shutil.copyfile(source / filename, stage / filename)
            if sha256(stage / filename) != entry["sha256"]:
                raise ValueError(f"Source checksum mismatch: {filename}")
            if table["name"] not in {"EC_NUMBER", "PROTEIN_GO", "PROTEIN_UNIPROT"}:
                continue
            original = stage / filename
            target = stage / (filename + ".part")
            changed = count = 0
            with original.open(newline="") as stream, target.open("w", newline="") as output:
                reader, writer = tsv.dict_reader(stream), tsv.writer(output)
                accepted = [table["columns"]]
                if table["name"] == "EC_NUMBER":
                    accepted.append(["ec_number"])
                elif table["name"] == "PROTEIN_GO":
                    accepted.append(["accession", "go_id", "evidence_code", "evidence_source"])
                if reader.fieldnames not in accepted:
                    raise ValueError(f"Unexpected source header: {filename}")
                writer.writerow(table["columns"])
                for row in reader:
                    if None in row or any(v is None for v in row.values()):
                        raise ValueError(f"Malformed source row: {filename}:{reader.line_num}")
                    previous = dict(row)
                    if table["name"] == "EC_NUMBER":
                        row.update(zip(EC_FIELDS, catalog.get(row["ec_number"], ["", "", ""])))
                    elif table["name"] == "PROTEIN_UNIPROT":
                        row["protein_name"] = without_ec_annotations(row["protein_name"])
                    else:
                        row.pop("evidence_code", None)
                        row.pop("evidence_source", None)
                    changed += row != previous
                    writer.writerow([row[c] for c in table["columns"]])
                    count += 1
            if count != entry["rows"]:
                raise ValueError(f"Source row count mismatch: {filename}")
            target.replace(original)
            metadata["files"][filename] = {"rows": count, "sha256": sha256(original)}
            changes[table["name"]] = changed
        metadata["enzyme_catalog_sha256"] = sha256(enzyme_catalog)
        (stage / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
        validate(stage, metadata["dataset_kind"])
        publish(stage, destination)
    return changes

