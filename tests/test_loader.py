"""Loader control-flow tests. Real SQL regressions live in mysql_integration.py."""

import re
from pathlib import Path
from unittest.mock import Mock

import mysql.connector
import pytest

from tests.make_fixture import generate
from unikegg import loader
from unikegg.dataset import TABLES, validate

ROOT = Path(__file__).resolve().parents[1]


class Connection:
    def __init__(
        self, report, *, state=None, nonempty=False, lock=True, warning=False, cursor_error=False
    ):
        self.report, self.state, self.nonempty = report, state, nonempty
        self.lock, self.warning, self.cursor_error = lock, warning, cursor_error
        self.queries = []
        self.commit, self.rollback, self.close = Mock(), Mock(), Mock()

    def cursor(self):
        if self.cursor_error:
            raise mysql.connector.InterfaceError("Synthetic cursor creation failure")
        connection = self

        class Cursor:
            rowcount = 1

            def execute(self, sql, params=None):
                connection.queries.append((sql, params))
                if "GET_LOCK" in sql:
                    self.result = (int(connection.lock),)
                elif "SELECT dataset_sha256" in sql:
                    self.result = (connection.state,) if connection.state else None
                elif "SELECT EXISTS" in sql:
                    self.result = (int(connection.nonempty),)
                elif sql.startswith("SELECT COUNT(*) FROM `") and "LEFT JOIN" not in sql:
                    table_name = re.search(r"FROM `([^`]+)`", sql)[1]
                    table = next(t for t in TABLES if t["name"] == table_name)
                    self.result = (connection.report["files"][table["file"]]["rows"],)
                elif sql.strip().startswith("LOAD DATA") and connection.warning:
                    raise mysql.connector.DatabaseError("Synthetic duplicate warning", errno=1062)
                else:
                    self.result = (0,)

            def fetchone(self):
                return self.result

            def close(self):
                pass

        return Cursor()


@pytest.mark.parametrize(
    "mode",
    [
        "new",
        "repeat",
        "verify-unloaded",
        "different",
        "nonempty",
        "lock-denied",
        "warning",
        "cursor-error",
    ],
)
def test_loader_branches(tmp_path, monkeypatch, mode):
    directory = generate(tmp_path / "processed")
    report, fingerprint = validate(directory, "synthetic")
    connection = Connection(
        report,
        state=fingerprint if mode == "repeat" else "other" if mode == "different" else None,
        nonempty=mode == "nonempty",
        lock=mode != "lock-denied",
        warning=mode == "warning",
        cursor_error=mode == "cursor-error",
    )
    snapshots = []

    def connect(snapshot):
        assert snapshot != directory and snapshot.is_dir()
        snapshots.append(snapshot)
        return connection

    monkeypatch.setattr(loader, "PROCESSED", directory)
    monkeypatch.setattr(loader, "PROJECT", ROOT)
    monkeypatch.setattr(loader, "connect", connect)
    monkeypatch.setenv("UNIKEGG_DATASET_KIND", "synthetic")
    if mode in {"new", "repeat"}:
        result = loader.run()
        assert result["action"] == ("loaded" if mode == "new" else "verified")
        assert result["dataset_sha256"] == fingerprint
        assert connection.commit.call_count == (mode == "new")
        connection.rollback.assert_not_called()
    else:
        with pytest.raises((ValueError, RuntimeError, mysql.connector.Error)):
            loader.run(verify_only=mode == "verify-unloaded")
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once()
    connection.close.assert_called_once()
    releases = sum("RELEASE_LOCK" in sql for sql, _ in connection.queries)
    assert releases == (mode not in {"lock-denied", "cursor-error"})
    loads = sum(sql.strip().startswith("LOAD DATA") for sql, _ in connection.queries)
    assert loads == (20 if mode == "new" else 1 if mode == "warning" else 0)
    assert snapshots and not snapshots[0].exists()


def test_no_db_connection_for_invalid_bundle(tmp_path, monkeypatch):
    directory = generate(tmp_path)
    (directory / "numero_ec.tsv").write_text("modified without updating the manifest\n")
    connect = Mock()
    monkeypatch.setattr(loader, "PROCESSED", directory)
    monkeypatch.setattr(loader, "connect", connect)
    monkeypatch.setenv("UNIKEGG_DATASET_KIND", "synthetic")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        loader.run()
    connect.assert_not_called()


def test_template_order_matches_foreign_keys():
    statements = list(
        loader.load_statements((ROOT / "db/load/001_ingest.sql").read_text(), Path("/data"))
    )
    order = [re.search(r"INTO TABLE (\w+)", sql)[1] for sql in statements]
    assert order == [table["name"] for table in TABLES]
    for table in TABLES:
        for fk in table["fk"]:
            assert order.index(fk["parent"]) < order.index(table["name"])
