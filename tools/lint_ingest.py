"""Lint every LOAD DATA assignment despite SQLFluff's multi-SET grammar limitation."""

import re
from pathlib import Path

from sqlfluff.core import FluffConfig, Linter


def projections(sql):
    """Keep each LOAD prefix and check each SET assignment separately, without edits."""
    for statement in re.sub(r"--[^\n]*", "", sql).split(";"):
        if not statement.strip():
            continue
        parts = re.split(r"\nSET\s+", statement.strip(), maxsplit=1)
        if len(parts) == 1:
            yield parts[0] + ";\n"
        else:
            # The executable template uses plain column = NULLIF(@variable, '') pairs.
            assignments = re.split(r",\s*(?=[a-z_]+\s*=)", parts[1], flags=re.IGNORECASE)
            for assignment in assignments:
                if not re.fullmatch(
                    r"[a-z_]+\s*=\s*NULLIF\(@[a-z_]+,\s*''\)", assignment.strip(), re.IGNORECASE
                ):
                    raise ValueError(
                        f"Unsupported assignment; extend the lint projection: {assignment}"
                    )
                yield parts[0] + "\nSET " + assignment.strip() + ";\n"


def main():
    path = Path("db/load/001_ingest.sql")
    config = FluffConfig.from_path(".", overrides={"dialect": "mysql"})
    linter = Linter(config=config)
    count, errors = 0, []
    for count, sql in enumerate(projections(path.read_text(encoding="utf-8")), 1):
        errors.extend(
            linter.lint_string(sql, fname=f"ingest_projection_{count}.sql").check_tuples()
        )
    if errors:
        raise SystemExit(str(errors))
    print(f"MySQL ingestion lint OK: {count} statement/assignment projections")


if __name__ == "__main__":
    main()
