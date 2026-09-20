"""Explicit, rate-limited KEGG acquisition; never executed by the demo."""

import http.client
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from unikegg.config import RAW
from unikegg.dataset import sha256
from unikegg.kegg_data import acquisition_manifest, check_payload, requests, selected_details

ROOT = RAW / "kegg"
BASE_URL = "https://rest.kegg.jp"


def fetch(endpoint, relative, dry_run=False):
    path = ROOT / relative
    url = BASE_URL + endpoint
    print(f"GET {url} -> {relative}", flush=True)
    if dry_run:
        return
    metadata = acquisition_manifest(ROOT).get(relative)
    if path.is_file():
        try:
            if not metadata or metadata["url"] != url or sha256(path) != metadata["sha256"]:
                raise ValueError("Missing/mismatched acquisition checksum or request")
            check_payload(endpoint, path.read_bytes())
        except (OSError, ValueError) as error:
            print(f"Invalid KEGG cache, downloading again: {relative}: {error}", flush=True)
        else:
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        for attempt in range(4):
            try:
                time.sleep(0.4)
                request = urllib.request.Request(url, headers={"User-Agent": "UniKegg/0.1"})
                with urllib.request.urlopen(request, timeout=120) as response:
                    payload = response.read()
                check_payload(endpoint, payload)
                temporary.write_bytes(payload)
                temporary.replace(path)
                with (ROOT / "manifest.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "url": url,
                                "file": relative,
                                "sha256": sha256(path),
                                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                        + "\n"
                    )
                return
            except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError):
                if attempt == 3:
                    raise
                time.sleep(2 ** (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def run(dry_run=False):
    for endpoint, relative in requests():
        fetch(endpoint, relative, dry_run)
    if dry_run:
        print("Reaction and compound detail batches are derived from these responses.")
        return
    for category, identifiers in selected_details(ROOT).items():
        identifiers = sorted(identifiers)
        for offset in range(0, len(identifiers), 10):
            batch = identifiers[offset : offset + 10]
            fetch("/get/" + "+".join(batch), f"details/{category}/{batch[0]}__{batch[-1]}.txt")
