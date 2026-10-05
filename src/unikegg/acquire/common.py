"""Bounded HTTP retries, process locks and atomic acquisition metadata."""

import gzip
import hashlib
import http.client
import json
import os
import random
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path


@contextmanager
def file_lock(path, blocking=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            stream.write(b"\0")
            stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise RuntimeError(f"Acquisition already running: {path}") from error
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError as error:
                raise RuntimeError(f"Acquisition already running: {path}") from error
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".metadata-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def selection_state(root, codes, status, **extra):
    atomic_json(
        Path(root) / "selection.json",
        {
            "version": 1,
            "codes": list(codes),
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **extra,
        },
    )


def retry_after(value):
    if value is None:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0, (date - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0


class HttpClient:
    def __init__(self, interval=1.0, attempts=4, timeout=120):
        if not 0.34 <= interval <= 3600 or not 1 <= attempts <= 20:
            raise ValueError("interval must be 0.34..3600 seconds; attempts must be 1..20")
        self.interval, self.attempts, self.timeout = interval, attempts, timeout

    def get(self, url, consume):
        host = urllib.parse.urlsplit(url).hostname or "unknown"
        # Same-user processes, including different dataset directories, serialize
        # requests to each host. The OS releases the lock even after a crash.
        uid = str(os.getuid()) if hasattr(os, "getuid") else os.environ.get("USERNAME", "user")
        key = hashlib.sha256((uid + host).encode()).hexdigest()[:24]
        lock = Path(tempfile.gettempdir()) / f"unikegg-http-{key}.lock"
        cooldown = lock.with_suffix(".json")
        with file_lock(lock, blocking=True):
            if cooldown.exists():
                remaining = json.loads(cooldown.read_text())["not_before"] - time.time()
                if remaining > 0:
                    print(f"HTTP server cooldown: wait {remaining:.1f}s", flush=True)
                    time.sleep(remaining)
                cooldown.unlink()
            for attempt in range(self.attempts):
                try:
                    time.sleep(self.interval)
                    request = urllib.request.Request(url, headers={"User-Agent": "UniKegg/0.2"})
                    with urllib.request.urlopen(request, timeout=self.timeout) as response:
                        result = consume(response)
                    cooldown.unlink(missing_ok=True)
                    return result
                except urllib.error.HTTPError as error:
                    delay = retry_after(error.headers.get("Retry-After"))
                    if delay:
                        atomic_json(cooldown, {"not_before": time.time() + delay})
                    error.close()
                    if error.code not in {408, 429, 500, 502, 503, 504}:
                        raise
                    failure = error
                except (
                    urllib.error.URLError,
                    TimeoutError,
                    ConnectionError,
                    http.client.HTTPException,
                    EOFError,
                    gzip.BadGzipFile,
                    zlib.error,
                    ValueError,
                ) as error:
                    delay, failure = 0, error
                if attempt == self.attempts - 1:
                    raise failure
                delay = max(delay, min(300, 2 ** (attempt + 1)) + random.uniform(0, 1))
                print(
                    f"HTTP retry {attempt + 1}/{self.attempts}: {failure}; wait {delay:.1f}s",
                    flush=True,
                )
                time.sleep(delay)
