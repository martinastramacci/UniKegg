"""Convert a complete 22-file Italian-name bundle into a separate English bundle."""

import argparse
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from unikegg.dataset import TABLES, sha256, validate
from unikegg.legacy_names import LEGACY_TABLE_NAMES
from unikegg.transforms.pipeline import output_lock, publish


def run(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents:
        raise ValueError("Destination must be separate from the source bundle")
    if destination.exists():
        raise ValueError("Destination already exists; choose an unused directory")
    metadata = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    reverse = {new: old for old, new in LEGACY_TABLE_NAMES.items()}
    filenames = {
        table["file"]: reverse.get(table["name"], table["name"]).lower() + ".tsv"
        for table in TABLES
    }
    if set(metadata.get("files", {})) != set(filenames.values()):
        raise ValueError("Expected a complete 22-file legacy bundle with its manifest")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with output_lock(destination), TemporaryDirectory(
        prefix=".unikegg-english-", dir=destination.parent,
    ) as temporary:
        stage = Path(temporary) / "processed"
        stage.mkdir()
        converted = {}
        for new, old in filenames.items():
            entry = metadata["files"][old]
            if sha256(source / old) != entry.get("sha256"):
                raise ValueError(f"Legacy checksum mismatch: {old}")
            shutil.copyfile(source / old, stage / new)
            converted[new] = entry
        metadata["files"] = converted
        (stage / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
        # Validate headers, row counts, identifiers, biological constraints and
        # every foreign key before publishing. Reviewed declarations are retained.
        validate(stage, metadata.get("dataset_kind"))
        publish(stage, destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.source, args.output))


if __name__ == "__main__":
    main()
