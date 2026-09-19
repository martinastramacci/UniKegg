"""Filesystem configuration shared by local and container execution."""

import os
from pathlib import Path

PROJECT = Path(os.environ.get("UNIKEGG_HOME", Path.cwd())).resolve()
DATA = Path(os.environ.get("UNIKEGG_DATA_DIR", PROJECT / "data")).resolve()
RAW = DATA / "raw"
PROCESSED = Path(os.environ.get("UNIKEGG_PROCESSED_DIR", DATA / "processed")).resolve()
ARTIFACTS = Path(os.environ.get("UNIKEGG_ARTIFACTS_DIR", PROJECT / "artifacts")).resolve()
