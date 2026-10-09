"""CLI for curated acquisition, transformation and transactional ingestion."""

import argparse
import os
from pathlib import Path

from unikegg.config import PROCESSED
from unikegg.organisms import CATALOG, select, selection


def main(argv=None):
    parser = argparse.ArgumentParser(prog="unikegg")
    parser.add_argument(
        "command",
        choices=[
            "load",
            "update",
            "history",
            "verify",
            "validate",
            "transform",
            "manifest",
            "download-uniprot",
            "download-kegg",
            "list-organisms",
        ],
    )
    parser.add_argument("--version-label", help="optional label for a committed load/update")
    parser.add_argument("--reviewed-export", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--organisms", help="comma-separated curated KEGG codes")
    group.add_argument("--limit", type=int, help="first N organisms in curated catalog order")
    group.add_argument(
        "--all-organisms", action="store_true", help="all curated organisms (not all KEGG)"
    )
    parser.add_argument("--search", help="filter list-organisms by code or scientific name")
    parser.add_argument(
        "--refresh", action="store_true", help="refresh source files; restart UniProt pages"
    )
    parser.add_argument("--include-json", action="store_true", help="also retain UniProt JSON")
    parser.add_argument(
        "--batch-size", type=int, help="UniProt: split selected organisms into groups of N (1..16)"
    )
    parser.add_argument(
        "--batch", type=int, help="UniProt: download only this group (1-based; requires --batch-size)"
    )
    parser.add_argument(
        "--append", action="store_true", help="UniProt: retain and verify previously selected organisms"
    )
    parser.add_argument(
        "--interval", type=float, help="minimum pause per request, default 1s (>=0.34)"
    )
    parser.add_argument("--attempts", type=int, help="HTTP attempts per request, default 4 (1..20)")
    args = parser.parse_args(argv)
    downloading = args.command in {"download-uniprot", "download-kegg"}
    explicit = args.organisms is not None or args.limit is not None or args.all_organisms
    if args.dry_run and not downloading and args.command != "update":
        parser.error("--dry-run is supported only by download-uniprot, download-kegg and update")
    if args.reviewed_export and args.command not in {"transform", "manifest"}:
        parser.error("--reviewed-export is supported only by transform and manifest")
    if explicit and args.command in {"load", "verify", "validate", "update", "history"}:
        parser.error("This command uses the organism selection in the dataset manifest")
    if args.version_label is not None and args.command not in {"load", "update"}:
        parser.error("--version-label is supported only by load and update")
    if args.search and args.command != "list-organisms":
        parser.error("--search is supported only by list-organisms")
    if (args.refresh or args.interval is not None or args.attempts is not None) and not downloading:
        parser.error("HTTP options are supported only by download commands")
    if args.include_json and args.command != "download-uniprot":
        parser.error("--include-json is supported only by download-uniprot")
    if (
        args.batch_size is not None or args.batch is not None or args.append
    ) and args.command != "download-uniprot":
        parser.error("--batch-size, --batch and --append are supported only by download-uniprot")
    try:
        codes = select(args.organisms, args.limit, args.all_organisms) if explicit else None
    except ValueError as error:
        parser.error(str(error))
    if args.command == "list-organisms":
        print("code\tUniProt taxid\tKEGG taxid\tscientific name")
        for organism in CATALOG:
            if codes is not None and organism.code not in codes:
                continue
            if (
                args.search
                and args.search.lower() not in (organism.code + " " + organism.name).lower()
            ):
                continue
            print(f"{organism.code}\t{organism.taxid}\t{organism.kegg_taxid}\t{organism.name}")
    elif args.command == "update":
        from unikegg.updater import run

        run(dry_run=args.dry_run, version_label=args.version_label)
    elif args.command == "history":
        from unikegg.versions import run

        run()
    elif args.command in {"load", "verify"}:
        from unikegg.loader import run

        run(verify_only=args.command == "verify", version_label=args.version_label)
    elif args.command == "validate":
        from unikegg.dataset import validate

        validate(PROCESSED, os.environ.get("UNIKEGG_DATASET_KIND", "swissprot"))
    elif args.command == "transform":
        from unikegg.transforms.pipeline import run

        run(PROCESSED, args.reviewed_export, codes=codes)
    elif args.command == "manifest":
        from unikegg.acquire.reviewed import reviewed_rows
        from unikegg.dataset import BY_NAME, manifest, rows, validate

        actual = select([row["kegg_code"] for row in rows(PROCESSED, BY_NAME["ORGANISM"])])
        if codes is not None and codes != actual:
            parser.error("Selected organisms do not match the processed tables")
        with selection(actual):
            reviewed = {row["Entry"] for row in reviewed_rows(args.reviewed_export)}
            manifest(PROCESSED, "swissprot", reviewed)
            validate(PROCESSED)
    else:
        from unikegg.acquire import kegg, uniprot

        options = {
            "dry_run": args.dry_run,
            "codes": codes,
            "refresh": args.refresh,
            "interval": args.interval if args.interval is not None else 1.0,
            "attempts": args.attempts if args.attempts is not None else 4,
        }
        if args.command == "download-uniprot":
            try:
                uniprot.plan_batches(codes, args.batch_size, args.batch)
            except ValueError as error:
                parser.error(str(error))
            uniprot.run(
                **options,
                include_json=args.include_json,
                batch_size=args.batch_size,
                batch=args.batch,
                append=args.append,
            )
        else:
            kegg.run(**options)


if __name__ == "__main__":
    main()
