"""Reproducible identities for source snapshots and the installed transformer."""

import hashlib
import json
import os
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from unikegg.dataset import sha256


def source_snapshot(root):
    root = Path(root)
    files = {}
    # Snapshot scope includes inactive exports, but excludes resumable transport caches.
    for directory, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "batches")
        for name in sorted(names):
            if name.startswith(".") or name.endswith((".part", ".lock")):
                continue
            path = Path(directory) / name
            files[path.relative_to(root).as_posix()] = {
                "sha256": sha256(path), "bytes": path.stat().st_size,
            }
    records = []
    if (root / "manifest.jsonl").exists():
        latest = {}
        for line in (root / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            name = record["file"]
            if name not in files and name.startswith("uniprot/"):
                name = name.removeprefix("uniprot/")
            latest[name] = record
        for name, record in sorted(latest.items()):
            if name in files and record.get("sha256") == files[name]["sha256"]:
                records.append({"file": name, **{
                    key: record[key] for key in ("release", "retrieved_at", "data_utc")
                    if key in record
                }})
    elif (root / "manifest.json").exists():
        record = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if record.get("sha256") == files.get("enzyme.rdf.xz", {}).get("sha256"):
            records.append({"file": "enzyme.rdf.xz", **{
                key: record[key] for key in ("release", "retrieved_at") if key in record
            }})
    return {
        "snapshot_sha256": hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "files": files,
        "acquisition_records": records,
        "releases": sorted({r["release"] for r in records if r.get("release")}),
    }


def capture(kegg, reviewed):
    package = Path(__file__).parent
    code = {p.relative_to(package).as_posix(): sha256(p) for p in sorted(package.rglob("*.py"))}
    code["schema.json"] = sha256(package / "schema.json")
    try:
        software_version = version("unikegg")
    except PackageNotFoundError:
        software_version = None
    return {
        "format_version": 1,
        "scope": "raw directory snapshots excluding hidden files, batches, partials and locks",
        "software": {
            "version": software_version,
            "python": platform.python_version(),
            "source_sha256": hashlib.sha256(
                json.dumps(code, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "files": code,
        },
        "sources": {
            "kegg": source_snapshot(kegg),
            "uniprot": source_snapshot(reviewed),
            "enzyme": source_snapshot(Path(kegg).parent / "enzyme"),
        },
    }
