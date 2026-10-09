"""Network-free acquisition and CLI safety regression tests."""

import http.client
import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.raw_fixture import generate, raw_tsv
from unikegg import cli, loader
from unikegg.acquire import common, kegg, uniprot
from unikegg.dataset import sha256
from unikegg.kegg_data import check_payload
from unikegg.organisms import DEFAULT_CODES
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
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    kegg.run(dry_run=True)
    network.assert_not_called()
    assert not root.exists()


def test_uniprot_entry_points_share_plan(tmp_path, monkeypatch, capsys):
    network = Mock()
    monkeypatch.setattr(uniprot, "RAW", tmp_path)
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    cli.main(["download-uniprot", "--dry-run"])
    cli_plan = capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["uniprot", "--dry-run"])
    uniprot.main()
    assert cli_plan == capsys.readouterr().out
    assert cli_plan.count("GET ") == len(DEFAULT_CODES)
    assert "9606_hsa.tsv.gz" in cli_plan
    network.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_legacy_uniprot_name_reused_without_creating_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(uniprot, "RAW", tmp_path)
    legacy = tmp_path / "9606_hsa.index.tsv.gz"
    legacy.write_bytes(b"synthetic placeholder; no network in this test")
    assert uniprot.planned_requests()[0][1] == legacy
    (tmp_path / "9606_hsa.tsv.gz").write_bytes(b"other")
    download = Mock()
    monkeypatch.setattr(uniprot, "download", download)
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


@pytest.mark.parametrize("repair", ["gene", "pathway", "deleted-gene", "none"])
def test_organism_catalog_reconciliation_refreshes_only_inconsistent_sources(
    tmp_path, monkeypatch, repair,
):
    generate(tmp_path)
    root = tmp_path / "data/raw/kegg"
    monkeypatch.setattr(kegg, "ROOT", root)
    relation = root / "relations/hsa_gene_pathway.tsv"
    gene = "hsa:demo1" if repair == "pathway" else "hsa:missing"
    pathway = "path:hsa00020" if repair == "pathway" else "path:hsa00010"
    raw_tsv(relation, [[gene, pathway]])
    original = relation.read_bytes()
    calls = []

    def fetch(endpoint, relative, **kwargs):
        assert kwargs["refresh"]
        calls.append(endpoint)
        if endpoint == "/list/hsa" and repair == "gene":
            with (root / relative).open("a") as stream:
                stream.write("hsa:missing\tCDS\t1..3\tRecovered gene\n")
        if endpoint == "/list/pathway/hsa" and repair == "pathway":
            raw_tsv(root / relative, [["path:hsa00010", "Old"], ["path:hsa00020", "New"]])
        if endpoint == "/link/pathway/hsa" and repair == "deleted-gene":
            raw_tsv(root / relative, [["hsa:demo1", "path:hsa00010"]])

    monkeypatch.setattr(kegg, "fetch", fetch)
    client = Mock()
    client.get.return_value = b"ENTRY       missing Gene\nNAME        Still exists\n///\n"
    if repair == "none":
        with pytest.raises(ValueError, match="after targeted refresh"):
            kegg.reconcile_organism_catalogs(["hsa"], client, {})
        assert relation.read_bytes() == original
    else:
        kegg.reconcile_organism_catalogs(["hsa"], client, {})
    assert calls[:2] == ["/list/hsa", "/list/pathway/hsa"]
    assert ("/link/pathway/hsa" in calls) == (repair in {"deleted-gene", "none"})


def test_consistent_organism_catalogs_need_no_refresh(tmp_path, monkeypatch):
    generate(tmp_path)
    monkeypatch.setattr(kegg, "ROOT", tmp_path / "data/raw/kegg")
    fetch = Mock()
    monkeypatch.setattr(kegg, "fetch", fetch)
    kegg.reconcile_organism_catalogs(["hsa"], Mock(), {})
    fetch.assert_not_called()


def test_inconsistent_organism_links_fail_before_detail_batches(tmp_path, monkeypatch):
    generate(tmp_path)
    root = tmp_path / "data/raw/kegg"
    monkeypatch.setattr(kegg, "ROOT", root)
    raw_tsv(root / "relations/hsa_gene_pathway.tsv", [["hsa:missing", "path:hsa00010"]])
    monkeypatch.setattr(kegg, "fetch", Mock())
    client = Mock()
    client.get.return_value = b"ENTRY       missing Gene\nNAME        Still exists\n///\n"
    monkeypatch.setattr(kegg, "HttpClient", Mock(return_value=client))
    details = Mock()
    monkeypatch.setattr(kegg, "selected_details", details)
    with pytest.raises(ValueError, match="after targeted refresh"):
        kegg.run(codes=["hsa"])
    details.assert_not_called()
    assert json.loads((root / "selection.json").read_text())["status"] == "incomplete"


@pytest.mark.parametrize("status", [404, 403, 503])
def test_stale_gene_pathway_requires_independent_404(tmp_path, monkeypatch, status):
    generate(tmp_path)
    root = tmp_path / "data/raw/kegg"
    monkeypatch.setattr(kegg, "ROOT", root)
    monkeypatch.setattr(kegg, "fetch", Mock())
    relation = root / "relations/hsa_gene_pathway.tsv"
    raw_tsv(relation, [["hsa:missing", "path:hsa00010"]])
    original = relation.read_bytes()
    client = Mock()
    client.get.side_effect = urllib.error.HTTPError(
        "https://rest.kegg.jp/get/hsa:missing", status, "failure", {}, None,
    )
    if status == 404:
        kegg.reconcile_organism_catalogs(["hsa"], client, {})
        evidence = json.loads((root / "missing_gene_checks.json").read_text())
        assert evidence["hsa:missing"]["status"] == 404
        assert evidence["hsa:missing"]["url"] == "https://rest.kegg.jp/get/hsa:missing"
    else:
        with pytest.raises(urllib.error.HTTPError):
            kegg.reconcile_organism_catalogs(["hsa"], client, {})
        assert not (root / "missing_gene_checks.json").exists()
    assert original == relation.read_bytes()


def test_kegg_reconciles_new_gene_ko_and_quarantines_verified_ec_orphan(tmp_path, monkeypatch):
    generate(tmp_path)
    root = tmp_path / "data/raw/kegg"
    monkeypatch.setattr(kegg, "ROOT", root)
    raw_tsv(root / "relations/hsa_gene_ko.tsv", [["hsa:demo1", "ko:K29269"]])
    raw_tsv(root / "relations/ko_ec.tsv", [["ko:K10658", "ec:2.3.2.27"]])
    client = Mock()
    client.get.side_effect = urllib.error.HTTPError(
        "https://rest.kegg.jp/get/K10658", 404, "missing", {}, None,
    )

    def refresh(endpoint, relative, **kwargs):
        assert endpoint == "/list/ko" and kwargs["refresh"]
        raw_tsv(root / relative, [["K00001", "Old KO"], ["K29269", "New KO"]])

    monkeypatch.setattr(kegg, "fetch", refresh)
    kegg.reconcile_ko_catalog(["hsa"], client, {})
    evidence = json.loads((root / "missing_ko_checks.json").read_text())
    assert evidence["K10658"]["status"] == 404
    assert evidence["K10658"]["url"] == "https://rest.kegg.jp/get/K10658"
    assert "K10658" in (root / "relations/ko_ec.tsv").read_text()
    assert client.get.call_count == 1


@pytest.mark.parametrize("failure", [403, 503, "timeout", "exists"])
def test_kegg_never_records_network_failures_or_existing_kos_as_deleted(
    tmp_path, monkeypatch, failure,
):
    generate(tmp_path)
    root = tmp_path / "data/raw/kegg"
    monkeypatch.setattr(kegg, "ROOT", root)
    monkeypatch.setattr(kegg, "fetch", Mock())
    raw_tsv(root / "relations/ko_ec.tsv", [["ko:K10658", "ec:2.3.2.27"]])
    client = Mock()
    if failure == "exists":
        client.get.return_value = b"ENTRY       K10658 KO\nNAME        Existing\n///\n"
        error = ValueError
    elif failure == "timeout":
        client.get.side_effect = TimeoutError("offline")
        error = TimeoutError
    else:
        client.get.side_effect = urllib.error.HTTPError("url", failure, "failure", {}, None)
        error = urllib.error.HTTPError
    with pytest.raises(error):
        kegg.reconcile_ko_catalog(["hsa"], client, {})
    assert not (root / "missing_ko_checks.json").exists()


def test_kegg_missing_gene_ko_is_never_quarantined(tmp_path, monkeypatch):
    generate(tmp_path)
    root = tmp_path / "data/raw/kegg"
    monkeypatch.setattr(kegg, "ROOT", root)
    monkeypatch.setattr(kegg, "fetch", Mock())
    raw_tsv(root / "relations/hsa_gene_ko.tsv", [["hsa:demo1", "ko:K29269"]])
    client = Mock()
    with pytest.raises(ValueError, match="gene assignments still reference missing KOs"):
        kegg.reconcile_ko_catalog(["hsa"], client, {})
    client.get.assert_not_called()


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
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    monkeypatch.setattr(common.time, "sleep", lambda _: None)
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
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    kegg.fetch(endpoint, relative)
    network.assert_not_called()


def test_incomplete_http_response_retried_four_times(tmp_path, monkeypatch):
    response = Mock()
    response.read.side_effect = http.client.IncompleteRead(b"partial", 100)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    network = Mock(return_value=response)
    monkeypatch.setattr(kegg, "ROOT", tmp_path)
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    monkeypatch.setattr(common.time, "sleep", lambda _: None)
    with pytest.raises(http.client.IncompleteRead):
        kegg.fetch("/get/R00001", "details/reaction/R00001.txt")
    assert network.call_count == 4
    assert not list(tmp_path.rglob("*.part"))
    assert not (tmp_path / "details/reaction/R00001.txt").exists()


def test_retry_recovers_from_interrupted_transfer(tmp_path, monkeypatch):
    attempts = [http.client.IncompleteRead(b"partial", 5), io.BytesIO(GOOD_RECORD)]
    network = Mock(side_effect=attempts)
    monkeypatch.setattr(kegg, "ROOT", tmp_path)
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    monkeypatch.setattr(common.time, "sleep", lambda _: None)
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
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    monkeypatch.setattr(common.time, "sleep", lambda _: None)
    with pytest.raises(TimeoutError):
        kegg.fetch("/list/ko", "ko/ko_list.tsv")
    assert network.call_count == 4
    assert path.read_bytes() == b"corrupted old cache"


def test_malformed_acquisition_manifest_fails_closed(tmp_path, monkeypatch):
    (tmp_path / "manifest.jsonl").write_text('{"truncated":')
    monkeypatch.setattr(kegg, "ROOT", tmp_path)
    network = Mock()
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
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
    monkeypatch.setattr(common.time, "sleep", lambda _: None)
    payload = gzip.compress(b"Entry\tReviewed\nSYN000001\treviewed\n")
    network = Mock(side_effect=[io.BytesIO(payload[:-5]), io.BytesIO(payload)])
    monkeypatch.setattr(uniprot.urllib.request, "urlopen", network)
    destination = uniprot.RAW / "synthetic.tsv.gz"
    uniprot.download("https://example.invalid/synthetic", destination, False)
    assert destination.read_bytes() == payload
    assert network.call_count == 2
    network.reset_mock()
    uniprot.download("https://example.invalid/synthetic", destination, False)
    network.assert_not_called()
    metadata = json.loads((uniprot.RAW / "manifest.jsonl").read_text())
    assert metadata["sha256"] == sha256(destination)


def test_uniprot_download_dry_run_does_not_create_files(tmp_path, monkeypatch):
    network = Mock()
    monkeypatch.setattr(uniprot.urllib.request, "urlopen", network)
    uniprot.download("https://example.invalid/synthetic", tmp_path / "absent/test.gz", True)
    assert not list(tmp_path.iterdir())
    network.assert_not_called()
