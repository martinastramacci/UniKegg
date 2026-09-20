"""Command line entry points for the offline demo and explicit acquisition."""

import argparse
import os
from pathlib import Path

from unikegg.config import PROCESSED


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
    parser.add_argument(
        "--reviewed-export", type=Path, help="reviewed source directory (transform/manifest only)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="plan requests without downloads (download commands only)",
    )
    args = parser.parse_args()
    if args.dry_run and args.command not in {"download-uniprot", "download-kegg"}:
        parser.error("--dry-run is supported only by download-uniprot and download-kegg")
    if args.reviewed_export and args.command not in {"transform", "manifest"}:
        parser.error("--reviewed-export is supported only by transform and manifest")
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
            from unikegg.transforms.pipeline import run

            run(PROCESSED, args.reviewed_export)
        else:
            reviewed = {row["Entry"] for row in reviewed_rows(args.reviewed_export)}
            manifest(PROCESSED, "swissprot", reviewed)
            validate(PROCESSED)
    elif args.command == "download-uniprot":
        from unikegg.acquire.uniprot import run

        run(dry_run=args.dry_run)
    else:
        from unikegg.acquire.kegg import run

        run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
