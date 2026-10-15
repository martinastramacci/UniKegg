"""Migrate existing TSV annotation fields; retain the source bundle."""

import argparse
import json
from pathlib import Path

from unikegg.transforms.annotations import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enzyme-catalog", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.output, args.enzyme_catalog)))
