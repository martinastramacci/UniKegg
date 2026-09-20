"""Real-MySQL regressions, run explicitly against a NEW disposable CI database.

Not collected by pytest. Refuses any database name other than the explicit test
name and refuses a schema that already contains tables. Never downloads biology.
Run: UNIKEGG_MYSQL_TEST_DATABASE=UniKeggRegression python -m tests.mysql_integration
The CI workflow creates/grants the empty database; this script never drops one.
"""

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import mysql.connector

from tests.make_fixture import generate
from unikegg import loader
from unikegg.dataset import BY_NAME, TABLES, manifest, rows

ROOT = Path(__file__).resolve().parents[1]


def statements(path):
    for sql in re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8")).split(";"):
        if sql.strip():
            yield sql


def query(sql, params=None):
    connection = loader.connect()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            cursor.close()
    finally:
        connection.close()


def initialize():
    connection = loader.connect()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()"
            )
            if cursor.fetchone()[0]:
                raise RuntimeError("Refusing to touch a nonempty integration-test schema")
            for path in sorted((ROOT / "db/init").glob("*.sql")):
                for sql in statements(path):
                    cursor.execute(sql)
        finally:
            cursor.close()
    finally:
        connection.close()


def expect_error(call, kind):
    try:
        call()
    except kind as error:
        return error
    raise AssertionError(f"Expected {kind.__name__}")


def typed(table, column, value):
    if not value and column in table["nullable"]:
        return None
    if table["specs"][column].startswith("INT UNSIGNED"):
        return int(value)
    if table["specs"][column].startswith("DECIMAL"):
        return Decimal(value)
    return value


def duplicate_warning_connection(connect, directory, protein):
    """Inject a real INSERT into the same transaction before a real LOAD DATA.

    The server, not a mock, emits the duplicate-key warning. No triggers or
    SUPER privileges are needed. Rollback must undo the injected row as well.
    """
    connection = connect(directory)
    table = BY_NAME["PROTEIN_UNIPROT"]
    columns = ",".join(f"`{c}`" for c in table["columns"])
    insert = f"INSERT INTO PROTEIN_UNIPROT ({columns}) VALUES ({','.join(['%s'] * len(table['columns']))})"

    class Cursor:
        def __init__(self, real):
            self.real = real

        def execute(self, statement, params=None):
            if "INTO TABLE PROTEIN_UNIPROT" in statement:
                self.real.execute(insert, protein)
            return self.real.execute(statement, params)

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Connection:
        def cursor(self):
            return Cursor(connection.cursor())

        def __getattr__(self, name):
            return getattr(connection, name)

    return Connection()


def run():
    database = os.environ.get("UNIKEGG_MYSQL_TEST_DATABASE")
    if database != "UniKeggRegression":
        raise RuntimeError("Explicit disposable database opt-in required; use the CI workflow")
    os.environ["MYSQL_DATABASE"] = database
    os.environ["UNIKEGG_DATASET_KIND"] = "synthetic"
    initialize()
    with TemporaryDirectory(prefix="unikegg-mysql-test-") as temporary:
        directory = generate(Path(temporary) / "processed", edge_cases=True, legacy_quoting=True)
        loader.PROCESSED, loader.PROJECT = directory, ROOT
        expected = {
            table["name"]: [
                tuple(typed(table, c, row[c]) for c in table["columns"])
                for row in rows(directory, table)
            ]
            for table in TABLES
        }
        original = {p.name: p.read_bytes() for p in directory.iterdir()}
        expect_error(lambda: loader.run(verify_only=True), ValueError)
        connect = loader.connect
        with patch.object(
            loader,
            "connect",
            lambda d: duplicate_warning_connection(connect, d, expected["PROTEIN_UNIPROT"][0]),
        ):
            warning = expect_error(loader.run, mysql.connector.Error)
        assert warning.errno == 1062, (
            f"Unexpected SQL failure instead of duplicate warning: {warning}"
        )
        for table in [*(t["name"] for t in TABLES), "ETL_LOAD_STATE"]:
            assert query(f"SELECT COUNT(*) FROM `{table}`")[0][0] == 0, f"Rollback failed: {table}"
        print(
            "Real MySQL warning rejected; all domain rows and load state rolled back.", flush=True
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(loader.run) for _ in range(2)]
            results = [future.result(timeout=120) for future in futures]
        assert sorted(result["action"] for result in results) == ["loaded", "verified"]
        assert loader.run(verify_only=True)["action"] == "verified"
        assert loader.run()["action"] == "verified"
        for table in TABLES:
            columns = ",".join(f"`{c}`" for c in table["columns"])
            actual = query(f"SELECT {columns} FROM `{table['name']}`")
            assert set(actual) == set(expected[table["name"]]), (
                f"Round-trip mismatch: {table['name']}"
            )
        assert original == {p.name: p.read_bytes() for p in directory.iterdir()}, (
            "Source bundle was mutated"
        )
        print(
            "All fields round-trip: NULL text, empty NULLs, quotes, multiline, UTF-8, 200k sequence.",
            flush=True,
        )

        connection = loader.connect()
        try:
            cursor = connection.cursor()
            try:
                count = 0
                for count, sql in enumerate(statements(ROOT / "db/queries/integration.sql"), 1):
                    cursor.execute(sql)
                    data = cursor.fetchall()
                    if "REGEXP_LIKE" in sql and "ec_number" in cursor.column_names:
                        index = cursor.column_names.index("ec_number")
                        assert all(
                            re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", row[index]) for row in data
                        )
                assert count == 30
            finally:
                cursor.close()
        finally:
            connection.close()
        print(
            "Thirty integration queries executed; preliminary ECs excluded from complete-EC results.",
            flush=True,
        )

        path = directory / "protein_uniprot.tsv"
        path.write_text(
            path.read_text(encoding="utf-8").replace("Line one", "Different annotation"),
            encoding="utf-8",
        )
        manifest(directory, "synthetic")
        mismatch = expect_error(loader.run, ValueError)
        assert "different dataset" in str(mismatch)
        for filename, content in original.items():
            (directory / filename).write_bytes(content)
        assert loader.run(verify_only=True)["action"] == "verified"
    print(json.dumps({"event": "mysql_regressions_passed", "database": database}), flush=True)


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        # Preserve useful diagnostics in GitHub Checks even when full runner logs
        # are unavailable to a client. No connection credentials are included.
        message = (
            f"{type(error).__name__}: {error}".replace("%", "%25")
            .replace("\r", "%0D")
            .replace("\n", "%0A")
        )
        print(f"::error title=MySQL regression::{message}", file=sys.stderr, flush=True)
        raise
