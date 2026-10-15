"""Download and validate the complete EC catalog before publishing it."""

import json
from datetime import datetime, timezone

from unikegg.acquire.common import HttpClient, atomic_json, file_lock
from unikegg.config import RAW
from unikegg.dataset import sha256
from unikegg.enzymes import URL, read_catalog

ROOT = RAW / "enzyme"


def run(dry_run=False, refresh=False, interval=1.0, attempts=4):
    path = ROOT / "enzyme.rdf.xz"
    print(f"GET {URL} -> {path}", flush=True)
    if dry_run:
        return
    with file_lock(ROOT / ".acquisition.lock"):
        metadata = ROOT / "manifest.json"
        if not refresh and path.exists() and metadata.exists():
            item = json.loads(metadata.read_text())
            if item.get("url") == URL and item.get("sha256") == sha256(path):
                read_catalog(path)
                return
        temporary = path.with_suffix(".xz.part")
        try:
            payload = HttpClient(interval, attempts).get(URL, lambda response: response.read())
            temporary.write_bytes(payload)
            catalog = read_catalog(temporary)
            temporary.replace(path)
            atomic_json(metadata, {
                "url": URL, "sha256": sha256(path), "records": len(catalog),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            })
        finally:
            temporary.unlink(missing_ok=True)
