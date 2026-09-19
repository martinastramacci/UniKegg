"""Command line entry points for the offline demo and explicit acquisition."""

import argparse
import os
from pathlib import Path

from unikegg.config import ARTIFACTS, PROCESSED


def main():
    parser = argparse.ArgumentParser(prog="unikegg")
    parser.add_argument(
        "command",
        choices=[
            "load",
            "verify",
            "validate",
            "transform",
            "manifest",
            "download-uniprot",
            "download-kegg",
        ],
    )
    parser.add_argument("--reviewed-export", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.reviewed_export:
        os.environ["UNIKEGG_REVIEWED_DIR"] = str(args.reviewed_export.resolve())
    if args.command in {"load", "verify"}:
        from unikegg.loader import run

        run(verify_only=args.command == "verify")
    elif args.command == "validate":
        from unikegg.dataset import validate

        validate(PROCESSED, os.environ.get("UNIKEGG_DATASET_KIND", "swissprot"))
    elif args.command in {"transform", "manifest"}:
        from unikegg.acquire.reviewed import reviewed_rows
        from unikegg.dataset import manifest, validate

        if args.command == "transform":
            from unikegg.transforms import entities, relations

            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            entities.main()
            relations.main()
        reviewed = {row["Entry"] for row in reviewed_rows(args.reviewed_export)}
        manifest(PROCESSED, "swissprot", reviewed)
        validate(PROCESSED)
    elif args.command == "download-uniprot":
        from unikegg.acquire.uniprot import CAMPI, ORGANISMI, RAW, crea_url, scarica

        for taxid, code in ORGANISMI:
            query = f"(organism_id:{taxid}) AND (reviewed:true)"
            scarica(crea_url(query, "json"), RAW / f"{taxid}_{code}.json.gz", args.dry_run)
            scarica(crea_url(query, "tsv", CAMPI), RAW / f"{taxid}_{code}.tsv.gz", args.dry_run)
    else:
        from unikegg.acquire.kegg import run

        run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
