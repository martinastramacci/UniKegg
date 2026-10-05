"""Version CLI and read-only history; mutation regressions use actual MySQL."""

import json
from datetime import datetime
from unittest.mock import Mock

import pytest

from unikegg import cli, loader, updater, versions


def test_cli_update_preview_and_label(monkeypatch):
    run = Mock()
    monkeypatch.setattr(updater, "run", run)
    cli.main(["update", "--dry-run", "--version-label", "Release September"])
    run.assert_called_once_with(dry_run=True, version_label="Release September")


def test_cli_load_label(monkeypatch):
    run = Mock()
    monkeypatch.setattr(loader, "run", run)
    cli.main(["load", "--version-label", "Initial snapshot"])
    run.assert_called_once_with(verify_only=False, version_label="Initial snapshot")


@pytest.mark.parametrize(
    "arguments",
    [
        ["update", "--organisms", "hsa"],
        ["update", "--refresh"],
        ["history", "--dry-run"],
        ["history", "--version-label", "wrong"],
        ["history", "--all-organisms"],
    ],
)
def test_invalid_version_cli_options_do_not_connect(monkeypatch, arguments):
    connect = Mock()
    monkeypatch.setattr(loader, "connect", connect)
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2
    connect.assert_not_called()


@pytest.mark.parametrize("label", ["", "   ", "x" * 129])
@pytest.mark.parametrize("run", [loader.run, updater.run])
def test_invalid_label_before_files_or_database(monkeypatch, run, label):
    connect = Mock()
    monkeypatch.setattr(loader, "connect", connect)
    with pytest.raises(ValueError, match="Version label"):
        run(version_label=label)
    connect.assert_not_called()


@pytest.mark.parametrize("mode", ["empty", "legacy", "versioned"])
def test_history_without_local_dataset(monkeypatch, tmp_path, capsys, mode):
    date = datetime(2026, 9, 30, 12, 30)
    cursor = Mock()

    def execute(statement, params=None):
        if statement.startswith("SET time_zone"):
            return
        assert statement.startswith("SELECT"), "History must never mutate metadata"
        if "information_schema" in statement:
            cursor.fetchone.return_value = (mode == "versioned",)
        elif "ORDER BY h.version" in statement:
            cursor.fetchall.return_value = [
                (2, "b" * 64, "swissprot", date, "update", "New", '{"GENE_KEGG":{}}', 1),
                (1, "a" * 64, "swissprot", date, "load", None, None, 0),
            ]
        else:
            cursor.fetchone.return_value = (
                ("a" * 64, "swissprot", date) if mode == "legacy" else None
            )

    cursor.execute.side_effect = execute
    connection = Mock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(loader, "connect", Mock(return_value=connection))
    monkeypatch.setattr(loader, "PROCESSED", tmp_path / "absent")
    cli.main(["history"])
    result = json.loads(capsys.readouterr().out)
    assert result["current_version"] == {"empty": None, "legacy": 1, "versioned": 2}[mode]
    assert len(result["versions"]) == {"empty": 0, "legacy": 1, "versioned": 2}[mode]
    if mode != "empty":
        assert result["versions"][0]["applied_at"] == "2026-09-30T12:30:00+00:00"
    if mode == "legacy":
        assert result["versions"][0]["action"] == "baseline"
    connection.commit.assert_not_called()
    cursor.close.assert_called_once()
    connection.close.assert_called_once()
    assert not (tmp_path / "absent").exists()


def test_label_boundary_and_unicode():
    assert versions.label_value("🧬" * 128) == "🧬" * 128
