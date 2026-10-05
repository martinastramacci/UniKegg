"""Rate-limited KEGG acquisition with verified, selection-specific details."""

import json
from datetime import datetime, timezone

from unikegg.acquire.common import HttpClient, atomic_json, file_lock, selection_state
from unikegg.config import RAW
from unikegg.dataset import sha256
from unikegg.kegg_data import (
    acquisition_manifest,
    check_payload,
    flat_records,
    requests,
    selected_details,
)
from unikegg.organisms import select

ROOT = RAW / "kegg"
BASE_URL = "https://rest.kegg.jp"


def fetch(endpoint, relative, dry_run=False, *, client=None, metadata=None, refresh=False):
    path = ROOT / relative
    url = BASE_URL + endpoint
    print(f"GET {url} -> {relative}", flush=True)
    if dry_run:
        return
    metadata = acquisition_manifest(ROOT) if metadata is None else metadata
    item = metadata.get(relative)
    if not refresh and path.is_file():
        try:
            if not item or item["url"] != url or sha256(path) != item["sha256"]:
                raise ValueError("Missing/mismatched acquisition checksum or request")
            check_payload(endpoint, path.read_bytes())
        except (OSError, ValueError) as error:
            print(f"Invalid KEGG cache: {relative}: {error}", flush=True)
        else:
            return
    client = client or HttpClient()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")

    def consume(response):
        payload = response.read()
        check_payload(endpoint, payload)
        return payload

    try:
        payload = client.get(url, consume)
        temporary.write_bytes(payload)
        temporary.replace(path)
        item = {
            "url": url,
            "file": relative,
            "sha256": sha256(path),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
        with (ROOT / "manifest.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(item) + "\n")
        metadata[relative] = item
    finally:
        temporary.unlink(missing_ok=True)


def run(dry_run=False, codes=None, refresh=False, interval=1.0, attempts=4):
    codes = select(codes)
    client = HttpClient(interval, attempts)
    tasks = requests(codes)
    print(f"KEGG: {len(codes)} organisms, {len(tasks)} base requests plus detail batches.")
    if dry_run:
        for endpoint, relative in tasks:
            fetch(endpoint, relative, True)
        print("Reaction and compound detail batches are derived from these responses.")
        return
    with file_lock(ROOT / ".acquisition.lock"):
        metadata = acquisition_manifest(ROOT)
        selection_state(ROOT, codes, "incomplete")
        for index, (endpoint, relative) in enumerate(tasks, 1):
            print(f"KEGG base {index}/{len(tasks)}", flush=True)
            fetch(endpoint, relative, client=client, metadata=metadata, refresh=refresh)
        for category, identifiers in selected_details(ROOT, codes).items():
            identifiers = sorted(identifiers)
            directory = ROOT / "details" / category
            files = []
            for offset in range(0, len(identifiers), 10):
                batch = identifiers[offset : offset + 10]
                relative = f"batches/{category}/{batch[0]}__{batch[-1]}.txt"
                fetch(
                    "/get/" + "+".join(batch),
                    relative,
                    client=client,
                    metadata=metadata,
                    refresh=refresh,
                )
                with (ROOT / relative).open(encoding="utf-8") as stream:
                    for record in flat_records(stream, relative):
                        identifier = record["ENTRY"][0].split()[0]
                        path = directory / "records" / f"{identifier}.txt"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        text = (
                            "".join(
                                f"{field if i == 0 else '':<12}{value}\n"
                                for field, values in record.items()
                                for i, value in enumerate(values)
                            )
                            + "///\n"
                        )
                        temporary = path.with_suffix(".part")
                        temporary.write_text(text, encoding="utf-8")
                        temporary.replace(path)
                        files.append(
                            {"file": path.relative_to(directory).as_posix(), "sha256": sha256(path)}
                        )
                print(
                    f"KEGG {category}: {min(offset + 10, len(identifiers))}/{len(identifiers)}",
                    flush=True,
                )
            atomic_json(directory / "active.json", files)
        selection_state(ROOT, codes, "complete")
