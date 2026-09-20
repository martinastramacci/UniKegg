"""Network-free acquisition and CLI safety regression tests."""

import http.client
import io
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from unikegg import cli, loader
from unikegg.acquire import kegg, uniprot
from unikegg.dataset import sha256
from unikegg.kegg_data import check_payload
from unikegg.transforms import entities, relations


@pytest.mark.parametrize("command", ["load", "verify", "validate", "transform", "manifest"])
def test_unsupported_dry_run_rejected_before_dispatch(monkeypatch, command):
    load, entity, relation = Mock(), Mock(), Mock()
    monkeypatch.setattr(loader, "run", load)
    monkeypatch.setattr(entities, "main", entity)
    monkeypatch.setattr(relations, "main", relation)
    monkeypatch.setattr(sys, "argv", ["unikegg", command, "--dry-run"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    load.assert_not_called()
    entity.assert_not_called()
    relation.assert_not_called()


def test_kegg_dry_run_no_network_or_files(tmp_path, monkeypatch):
    root, network = tmp_path / "absent", Mock()
    monkeypatch.setattr(kegg, "ROOT", root)
    monkeypatch.setattr(kegg.urllib.request, "urlopen", network)
    kegg.run(dry_run=True)
    network.assert_not_called()
    assert not root.exists()


def test_uniprot_entry_points_share_plan(tmp_path, monkeypatch):
    download = Mock()
    monkeypatch.setattr(uniprot, "RAW", tmp_path)
    monkeypatch.setattr(uniprot, "scarica", download)
    monkeypatch.setattr(sys, "argv", ["unikegg", "download-uniprot", "--dry-run"])
    cli.main()
    cli_calls = download.call_args_list[:]
    download.reset_mock()
    monkeypatch.setattr(sys, "argv", ["uniprot", "--dry-run"])
    uniprot.main()
    assert cli_calls == download.call_args_list
    assert len(cli_calls) == 20
    assert all(call.args[2] is True for call in cli_calls)
    assert cli_calls[1].args[1].name == "9606_hsa.tsv.gz"
    assert not list(tmp_path.iterdir())


def test_legacy_uniprot_name_reused_without_creating_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(uniprot, "RAW", tmp_path)
    legacy = tmp_path / "9606_hsa.index.tsv.gz"
    legacy.write_bytes(b"synthetic placeholder; no network in this test")
    assert uniprot.planned_requests()[1][1] == legacy
    (tmp_path / "9606_hsa.tsv.gz").write_bytes(b"other")
    download = Mock()
    monkeypatch.setattr(uniprot, "scarica", download)
    with pytest.raises(ValueError, match="Duplicate UniProt exports"):
        uniprot.run()
    download.assert_not_called()


def cache(root, relative, endpoint, payload):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    entry = {"file": relative, "url": kegg.BASE_URL + endpoint, "sha256": sha256(path)}
    (root / "manifest.jsonl").write_text(json.dumps(entry) + "\n")
    return path


GOOD_RECORD = b"ENTRY       R00001 Reaction\nNAME        Synthetic\n///\n"


@pytest.mark.parametrize("damage", ["checksum", "structure", "request", "metadata"])
def test_invalid_kegg_cache_downloaded_again(tmp_path, monkeypatch, damage):
    endpoint, relative = "/get/R00001", "details/reaction/R00001.txt"
    original = GOOD_RECORD.removesuffix(b"///\n") if damage == "structure" else GOOD_RECORD
    path = cache(tmp_path, relative, endpoint if damage != "request" else "/get/R00002", original)
    if damage == "checksum":
        path.write_bytes(original.replace(b"Synthetic", b"Changed"))
    if damage == "metadata":
        (tmp_path / "manifest.jsonl").unlink()
    network = Mock(side_effect=lambda *args, **kwargs: io.BytesIO(GOOD_RECORD))
    monkeypatch.setattr(kegg, "ROOT", tmp_path)
    monkeypatch.setattr(kegg.urllib.request, "urlopen", network)
    monkeypatch.setattr(kegg.time, "sleep", lambda _: None)
    kegg.fetch(endpoint, relative)
    assert network.call_count == 1
    assert path.read_bytes() == GOOD_RECORD
    network.reset_mock()
    kegg.fetch(endpoint, relative)
    network.assert_not_called()


def test_valid_and_empty_relationship_caches_reused(tmp_path, monkeypatch):
    endpoint, relative = "/link/ko/hsa", "relations/hsa_gene_ko.tsv"
    cache(tmp_path, relative, endpoint, b"")
    network = Mock()
    monkeypatch.setattr(kegg, "ROOT", tmp_path)
    monkeypatch.setattr(kegg.urllib.request, "urlopen", network)
    kegg.fetch(endpoint, relative)
    network.assert_not_called()


def test_incomplete_http_response_retried_four_times(tmp_path, monkeypatch):
    response = Mock()
    response.read.side_effect = http.client.IncompleteRead(b"partial", 100)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    network = Mock(return_value=response)
    monkeypatch.setattr(kegg, "ROOT", tmp_path)
    monkeypatch.setattr(kegg.urllib.request, "urlopen", network)
    monkeypatch.setattr(kegg.time, "sleep", lambda _: None)
    with pytest.raises(http.client.IncompleteRead):
        kegg.fetch("/get/R00001", "details/reaction/R00001.txt")
    assert network.call_count == 4
    assert not list(tmp_path.rglob("*.part"))
    assert not (tmp_path / "details/reaction/R00001.txt").exists()


def test_retry_recovers_from_interrupted_transfer(tmp_path, monkeypatch):
    attempts = [http.client.IncompleteRead(b"partial", 5), io.BytesIO(GOOD_RECORD)]
    network = Mock(side_effect=attempts)
    monkeypatch.setattr(kegg, "ROOT", tmp_path)
    monkeypatch.setattr(kegg.urllib.request, "urlopen", network)
    monkeypatch.setattr(kegg.time, "sleep", lambda _: None)
    kegg.fetch("/get/R00001", "details/reaction/R00001.txt")
    assert network.call_count == 2
    assert (tmp_path / "details/reaction/R00001.txt").read_bytes() == GOOD_RECORD


@pytest.mark.parametrize(
    "payload",
    [
        GOOD_RECORD + GOOD_RECORD,
        GOOD_RECORD.replace(b"R00001", b"R00002"),
        GOOD_RECORD.removesuffix(b"///\n"),
        b"",
        b"<html>upstream error</html>",
    ],
)
def test_bad_detail_batches_fail_validation(payload):
    with pytest.raises(ValueError):
        check_payload("/get/R00001", payload)


def test_failed_refresh_preserves_existing_file(tmp_path, monkeypatch):
    path = cache(tmp_path, "ko/ko_list.tsv", "/list/ko", b"K00001\tSynthetic\n")
    path.write_bytes(b"corrupted old cache")
    network = Mock(side_effect=TimeoutError("synthetic timeout"))
    monkeypatch.setattr(kegg, "ROOT", tmp_path)
    monkeypatch.setattr(kegg.urllib.request, "urlopen", network)
    monkeypatch.setattr(kegg.time, "sleep", lambda _: None)
    with pytest.raises(TimeoutError):
        kegg.fetch("/list/ko", "ko/ko_list.tsv")
    assert network.call_count == 4
    assert path.read_bytes() == b"corrupted old cache"


def test_malformed_acquisition_manifest_fails_closed(tmp_path, monkeypatch):
    (tmp_path / "manifest.jsonl").write_text('{"truncated":')
    monkeypatch.setattr(kegg, "ROOT", tmp_path)
    network = Mock()
    monkeypatch.setattr(kegg.urllib.request, "urlopen", network)
    with pytest.raises(ValueError, match="Invalid KEGG manifest"):
        kegg.fetch("/get/R00001", "details/reaction/R00001.txt")
    network.assert_not_called()


def test_reviewed_export_option_not_ignored_for_load(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["unikegg", "load", "--reviewed-export", str(Path("unused"))])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


@pytest.mark.parametrize(
    "header, record",
    [
        ("Entry\tReviewed\tReviewed", "P00001\tunreviewed\treviewed"),
        ("Entry\tReviewed", "P00001"),
        ("Entry\tReviewed", "P00001\treviewed\textra"),
    ],
)
def test_ambiguous_reviewed_export_rejected(tmp_path, header, record):
    import gzip

    from unikegg.acquire.reviewed import reviewed_rows

    with gzip.open(tmp_path / "synthetic.tsv.gz", "wt", encoding="utf-8") as stream:
        stream.write(header + "\n" + record + "\n")
    with pytest.raises(ValueError):
        list(reviewed_rows(tmp_path))


def test_uniprot_download_gzip_integrity_retry_and_cache(tmp_path, monkeypatch):
    import gzip

    monkeypatch.setattr(uniprot, "RAW_ROOT", tmp_path)
    monkeypatch.setattr(uniprot, "RAW", tmp_path / "uniprot")
    monkeypatch.setattr(uniprot.time, "sleep", lambda _: None)
    payload = gzip.compress(b"Entry\tReviewed\nSYN000001\treviewed\n")
    network = Mock(side_effect=[io.BytesIO(payload[:-5]), io.BytesIO(payload)])
    monkeypatch.setattr(uniprot.urllib.request, "urlopen", network)
    destination = uniprot.RAW / "synthetic.tsv.gz"
    uniprot.scarica("https://example.invalid/synthetic", destination, False)
    assert destination.read_bytes() == payload
    assert network.call_count == 2
    network.reset_mock()
    uniprot.scarica("https://example.invalid/synthetic", destination, False)
    network.assert_not_called()
    metadata = json.loads((uniprot.RAW / "manifest.jsonl").read_text())
    assert metadata["sha256"] == sha256(destination)


def test_uniprot_download_dry_run_does_not_create_files(tmp_path, monkeypatch):
    network = Mock()
    monkeypatch.setattr(uniprot.urllib.request, "urlopen", network)
    uniprot.scarica("https://example.invalid/synthetic", tmp_path / "absent/test.gz", True)
    assert not list(tmp_path.iterdir())
    network.assert_not_called()
