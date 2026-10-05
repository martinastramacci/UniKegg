"""Disk-backed deterministic relationship deduplication with bounded SQLite cache."""

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory


def unique_rows(rows, columns):
    with TemporaryDirectory(prefix="unikegg-sort-") as temporary:
        connection = sqlite3.connect(Path(temporary) / "rows.sqlite")
        try:
            connection.execute("PRAGMA cache_size=-4096")
            connection.execute("PRAGMA temp_store=FILE")
            names = [f"c{index}" for index in range(columns)]
            projection = ",".join(names)
            connection.execute(
                "CREATE TABLE rows ("
                + ",".join(f"{name} TEXT NOT NULL" for name in names)
                + f", PRIMARY KEY ({projection})) WITHOUT ROWID"
            )
            connection.executemany(
                "INSERT INTO rows VALUES ("
                + ",".join("?" for _ in names)
                + ") ON CONFLICT DO NOTHING",
                rows,
            )
            yield from connection.execute(f"SELECT {projection} FROM rows ORDER BY {projection}")
        finally:
            connection.close()
