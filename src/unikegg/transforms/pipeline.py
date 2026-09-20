"""Stage and validate a complete transformation before replacing an output bundle."""

import json
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory, mkdtemp

from unikegg.acquire.reviewed import reviewed_rows
from unikegg.dataset import TABLES, manifest, validate
from unikegg.transforms import entities, relations


@contextmanager
def output_lock(directory):
    """Portable exclusive writer lock; a crashed writer requires explicit recovery."""
    path = directory.parent / f".unikegg-{directory.name}.lock"
    try:
        stream = path.open("x", encoding="utf-8")
    except FileExistsError as error:
        raise RuntimeError(
            f"Transformation lock exists: {path}. Check for a running writer or interrupted "
            "publication before removing a stale lock."
        ) from error
    try:
        with stream:
            stream.write(f"pid={os.getpid()}\n")
        yield
    finally:
        path.unlink(missing_ok=True)


def check_destination(directory):
    # Do not turn a misconfigured path into deletion of unrelated user files.
    allowed = {table["file"] for table in TABLES} | {"manifest.json", ".gitkeep"}
    if directory.exists():
        unexpected = [
            p.name for p in directory.iterdir() if p.name not in allowed or not p.is_file()
        ]
        if unexpected:
            raise ValueError(
                f"Output directory contains unrelated files: {directory}: {unexpected}"
            )


def publish(stage, directory):
    """Recover the previous directory on rename failure, retaining it if recovery fails.

    This is a recoverable two-rename publication, not a cross-platform crash-atomic
    exchange. The backup is outside the staging context so failed recovery never
    deletes the only remaining copy. Readers use validated private snapshots.
    """
    backup_root = Path(mkdtemp(prefix=".unikegg-previous-", dir=directory.parent))
    previous = backup_root / directory.name
    try:
        if directory.exists():
            os.replace(directory, previous)
        try:
            os.replace(stage, directory)
        except BaseException:
            if previous.exists():
                try:
                    os.replace(previous, directory)
                except OSError as error:
                    raise RuntimeError(
                        f"Publication/restore failed. Previous dataset retained at {previous}"
                    ) from error
            raise
    except BaseException:
        if not previous.exists():
            backup_root.rmdir()
        raise
    else:
        try:
            shutil.rmtree(backup_root)
        except OSError as error:
            print(f"Dataset published; old backup retained at {previous}: {error}", file=sys.stderr)


def run(directory, reviewed_export=None):
    directory = Path(directory).resolve()
    directory.parent.mkdir(parents=True, exist_ok=True)
    old_output, old_relations, old_reports = entities.OUTPUT, relations.OUTPUT, relations.CONTROLLI
    previous_reviewed = os.environ.get("UNIKEGG_REVIEWED_DIR")
    report_copy = None
    with (
        output_lock(directory),
        TemporaryDirectory(prefix=f".unikegg-{directory.name}-", dir=directory.parent) as temporary,
    ):
        check_destination(directory)
        stage, reports = Path(temporary) / "processed", Path(temporary) / "reports"
        entities.OUTPUT = relations.OUTPUT = stage
        relations.CONTROLLI = reports
        if reviewed_export is not None:
            os.environ["UNIKEGG_REVIEWED_DIR"] = str(Path(reviewed_export).resolve())
        try:
            entities.main()
            relations.main()
            reviewed = {row["Entry"] for row in reviewed_rows(reviewed_export)}
            manifest(stage, "swissprot", reviewed)
            _, fingerprint = validate(stage)
            if (directory / ".gitkeep").is_file():
                shutil.copyfile(directory / ".gitkeep", stage / ".gitkeep")
            # Detect unwritable report locations before replacing the dataset.
            old_reports.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=old_reports, delete=False) as stream:
                report_copy = Path(stream.name)
            shutil.copyfile(reports / "report_gene_proteina.tsv", report_copy)
            publish(stage, directory)
            try:
                os.replace(report_copy, old_reports / "report_gene_proteina.tsv")
            except OSError as error:
                # Domain publication is complete; do not misreport it as rolled back.
                print(
                    f"Dataset published, but the report could not be updated: {error}",
                    file=sys.stderr,
                )
            print(
                json.dumps(
                    {
                        "event": "transformed",
                        "directory": str(directory),
                        "dataset_sha256": fingerprint,
                    }
                ),
                flush=True,
            )
        finally:
            entities.OUTPUT, relations.OUTPUT, relations.CONTROLLI = (
                old_output,
                old_relations,
                old_reports,
            )
            if previous_reviewed is None:
                os.environ.pop("UNIKEGG_REVIEWED_DIR", None)
            else:
                os.environ["UNIKEGG_REVIEWED_DIR"] = previous_reviewed
            if report_copy is not None:
                report_copy.unlink(missing_ok=True)
