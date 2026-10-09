"""Offline failures and scope changes that matter for real acquisition jobs."""

import gzip
import io
import json
import urllib.error
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock

import pytest

from tests.raw_fixture import generate
from unikegg import cli, tsv
from unikegg.acquire import common, kegg, uniprot
from unikegg.acquire.reviewed import reviewed_rows
from unikegg.dataset import BY_NAME, rows, sha256, validate
from unikegg.kegg_data import check_payload, detail_records
from unikegg.organisms import BY_CODE, CATALOG, DEFAULT_CODES, recorded_selection, select, selection
from unikegg.transforms import entities, pipeline, relations


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(common.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        common.urllib.request, "urlopen", Mock(side_effect=AssertionError("Unexpected HTTP"))
    )


def configure(tmp_path, monkeypatch):
    monkeypatch.setattr(uniprot, "RAW_ROOT", tmp_path)
    monkeypatch.setattr(uniprot, "RAW", tmp_path / "uniprot")
    return uniprot.RAW


class Response(io.BytesIO):
    def __init__(self, payload, total=1, release="2026_04", following=None):
        super().__init__(payload)
        self.headers = {"X-Total-Results": str(total), "X-UniProt-Release": release}
        if following:
            self.headers["Link"] = f'<{following}>; rel="next"'


def page(accessions=("P00001",), taxid="9606", reviewed="reviewed"):
    fields = sorted(uniprot.REQUIRED_COLUMNS)
    stream = io.StringIO()
    writer = tsv.writer(stream)
    writer.writerow(fields)
    for accession in accessions:
        row = dict.fromkeys(fields, "")
        row.update(
            {
                "Entry": accession,
                "Reviewed": reviewed,
                "Organism (ID)": taxid,
                "Entry Name": accession + "_TEST",
                "Protein names": "Synthetic",
                "Sequence": "MACK",
                "Length": "4",
                "Mass": "400",
                "Protein existence": "Evidence at protein level",
                "Sequence version": "1",
                "KEGG": "hsa:demo1;",
            }
        )
        writer.writerow([row[f] for f in fields])
    return stream.getvalue().encode()


def test_retry_after_seconds_date_and_permanent_failure(monkeypatch):
    delays = []
    monkeypatch.setattr(common.time, "sleep", delays.append)
    errors = [
        urllib.error.HTTPError(
            "https://example.invalid", 429, "limit", {"Retry-After": "120"}, None
        ),
        Response(b"ok"),
    ]
    network = Mock(side_effect=errors)
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    assert common.HttpClient().get("https://example.invalid", lambda r: r.read()) == b"ok"
    assert 120 in delays
    date = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=120), usegmt=True)
    assert 118 <= common.retry_after(date) <= 120
    assert common.retry_after("invalid") == 0
    assert common.retry_after("-1") == 0
    network.side_effect = urllib.error.HTTPError("https://example.invalid", 400, "bad", {}, None)
    network.reset_mock()
    with pytest.raises(urllib.error.HTTPError):
        common.HttpClient().get("https://example.invalid", lambda r: r.read())
    assert network.call_count == 1


def test_acquisition_lock_released_on_failure(tmp_path):
    path = tmp_path / "download.lock"
    with pytest.raises(ValueError):
        with common.file_lock(path):
            with pytest.raises(RuntimeError, match="already running"):
                with common.file_lock(path):
                    pytest.fail("second writer admitted")
            raise ValueError("interrupted")
    with common.file_lock(path):
        pass


@pytest.mark.parametrize(
    "interval,attempts", [(0, 4), (0.1, 4), (1, 0), (1, 21), (float("nan"), 4)]
)
def test_invalid_http_settings(interval, attempts):
    with pytest.raises(ValueError):
        common.HttpClient(interval, attempts)


def test_curated_selection_and_stable_ids():
    assert len(CATALOG) == 16
    assert select() == DEFAULT_CODES
    assert select(limit=12) == tuple(o.code for o in CATALOG[:12])
    assert select("eco,hsa") == ("hsa", "eco")
    assert BY_CODE["eco"].id == 9
    assert BY_CODE["eco"].taxid == "83333"
    assert BY_CODE["spo"].taxid == "284812"
    assert len({o.taxid for o in CATALOG}) == 16
    for codes in ["", "hsa,hsa", "osa", "hsa,unknown"]:
        with pytest.raises(ValueError):
            select(codes)
    for limit in [0, -1, 17]:
        with pytest.raises(ValueError):
            select(limit=limit)


def test_cli_extended_dry_run_no_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(kegg, "ROOT", tmp_path / "absent")
    cli.main(["download-kegg", "--all-organisms", "--dry-run"])
    text = capsys.readouterr().out
    assert "16 organisms, 88 base requests" in text
    assert "/list/spo" in text
    assert not list(tmp_path.iterdir())
    cli.main(["list-organisms", "--search", "pombe"])
    assert "284812" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["validate", "--organisms", "hsa"])


def test_curated_gene_payloads():
    for organism in CATALOG:
        check_payload("/list/" + organism.code, f"{organism.code}:1\tCDS\t1..3\tExample\n".encode())


def test_uniprot_unverified_cache_is_replaced(tmp_path, monkeypatch):
    raw = configure(tmp_path, monkeypatch)
    raw.mkdir()
    url, destination = uniprot.planned_requests(["hsa"])[0]
    destination.write_bytes(gzip.compress(page(["WRONG"])))
    network = Mock(return_value=Response(page()))
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    uniprot.run(codes=["hsa"])
    assert network.call_count == 1
    with selection(["hsa"]):
        assert [row["Entry"] for row in reviewed_rows(raw)] == ["P00001"]
    network.reset_mock()
    uniprot.run(codes=["hsa"])
    network.assert_not_called()
    metadata = uniprot.acquisition_manifest()
    assert metadata["uniprot/" + destination.name]["sha256"] == sha256(destination)
    assert recorded_selection(raw)["codes"] == ("hsa",)


def test_resume_after_failure_does_not_redownload_first_page(tmp_path, monkeypatch):
    raw = configure(tmp_path, monkeypatch)
    following = "https://rest.uniprot.org/uniprotkb/search?cursor=second"
    network = Mock(
        side_effect=[Response(page(), total=2, following=following), TimeoutError("interrupt")]
    )
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    with pytest.raises(TimeoutError):
        uniprot.run(codes=["hsa"], attempts=1)
    assert not (raw / "9606_hsa.tsv.gz").exists()
    with pytest.raises(ValueError, match="Incomplete"):
        recorded_selection(raw)
    network.reset_mock()
    network.side_effect = [Response(page(["P00002"]), total=2)]
    uniprot.run(codes=["hsa"], attempts=1)
    assert network.call_count == 1
    assert network.call_args.args[0].full_url == following
    with selection(["hsa"]):
        assert {r["Entry"] for r in reviewed_rows(raw)} == {"P00001", "P00002"}


@pytest.mark.parametrize("completed_pages", [0, 1, 2])
def test_interrupted_refresh_resumes_new_pages_and_unvisited_exports(
    tmp_path, monkeypatch, completed_pages
):
    raw = configure(tmp_path, monkeypatch)
    network = Mock(
        side_effect=[
            Response(page(["OLD001"])),
            Response(page(["OLD002"], taxid="10090")),
        ]
    )
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    uniprot.run(codes=["hsa", "mmu"], attempts=1)
    following = "https://rest.uniprot.org/uniprotkb/search?cursor=refresh-second"

    def new_pages():
        return [
            Response(page(["NEW001"]), total=2, release="2026_05", following=following),
            Response(page(["NEW002"]), total=2, release="2026_05"),
            Response(page(["NEW003"], taxid="10090"), release="2026_05"),
        ]

    network.side_effect = new_pages()[:completed_pages] + [TimeoutError("interrupt refresh")]
    with pytest.raises(TimeoutError):
        uniprot.run(codes=["hsa", "mmu"], refresh=True, attempts=1)
    network.reset_mock()
    network.side_effect = new_pages()[completed_pages:]
    uniprot.run(codes=["hsa", "mmu"], attempts=1)
    assert network.call_count == 3 - completed_pages
    if completed_pages == 1:
        assert network.call_args_list[0].args[0].full_url == following
    with selection(["hsa", "mmu"]):
        assert {r["Entry"] for r in reviewed_rows(raw)} == {"NEW001", "NEW002", "NEW003"}
    assert recorded_selection(raw)["release"] == "2026_05"
    network.reset_mock()
    uniprot.run(codes=["hsa", "mmu"], attempts=1)
    network.assert_not_called()


def test_refresh_resumes_after_last_page_before_publication(tmp_path, monkeypatch):
    from pathlib import Path

    raw = configure(tmp_path, monkeypatch)
    network = Mock(return_value=Response(page(["OLD001"])))
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    uniprot.run(codes=["hsa"], attempts=1)
    replace = Path.replace

    def fail_publication(path, target):
        if target == raw / "9606_hsa.tsv.gz":
            raise OSError("interrupted publication")
        return replace(path, target)

    network.return_value = Response(page(["NEW001"]), release="2026_05")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_publication)
        with pytest.raises(OSError, match="publication"):
            uniprot.run(codes=["hsa"], refresh=True, attempts=1)
    network.reset_mock()
    uniprot.run(codes=["hsa"], attempts=1)
    network.assert_not_called()
    with selection(["hsa"]):
        assert [r["Entry"] for r in reviewed_rows(raw)] == ["NEW001"]


def test_refresh_resume_restarts_optional_json_export(tmp_path, monkeypatch):
    raw = configure(tmp_path, monkeypatch)

    def export(accession, release):
        payload = {
            "results": [
                {
                    "primaryAccession": accession,
                    "entryType": "UniProtKB reviewed (Swiss-Prot)",
                    "organism": {"taxonId": 9606},
                }
            ]
        }
        return Response(gzip.compress(json.dumps(payload).encode()), release=release)

    network = Mock(side_effect=[export("OLD001", "2026_04"), Response(page(["OLD001"]))])
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    uniprot.run(codes=["hsa"], include_json=True, attempts=1)
    network.side_effect = [TimeoutError("interrupt JSON refresh")]
    with pytest.raises(TimeoutError):
        uniprot.run(codes=["hsa"], include_json=True, refresh=True, attempts=1)
    network.reset_mock()
    network.side_effect = [
        export("NEW001", "2026_05"),
        Response(page(["NEW001"]), release="2026_05"),
    ]
    uniprot.run(codes=["hsa"], include_json=True, attempts=1)
    assert network.call_count == 2
    with gzip.open(raw / "9606_hsa.json.gz", "rt") as stream:
        assert json.load(stream)["results"][0]["primaryAccession"] == "NEW001"
    assert recorded_selection(raw)["release"] == "2026_05"


@pytest.mark.parametrize(
    "damage", ["release", "count", "duplicate", "wrong-taxid", "unreviewed", "loop"]
)
def test_bad_pages_never_replace_valid_export(tmp_path, monkeypatch, damage):
    raw = configure(tmp_path, monkeypatch)
    raw.mkdir()
    destination = raw / "9606_hsa.tsv.gz"
    before = gzip.compress(page(["OLD"]))
    destination.write_bytes(before)
    following = "https://rest.uniprot.org/uniprotkb/search?cursor=second"
    second = Response(page(["P00002"]), total=2)
    if damage == "release":
        second.headers["X-UniProt-Release"] = "2026_05"
    elif damage == "count":
        second.headers["X-Total-Results"] = "3"
    elif damage == "duplicate":
        second = Response(page(), total=2)
    elif damage == "wrong-taxid":
        second = Response(page(["P00002"], taxid="10090"), total=2)
    elif damage == "unreviewed":
        second = Response(page(["P00002"], reviewed="unreviewed"), total=2)
    elif damage == "loop":
        second.headers["Link"] = f'<{following}>; rel="next"'
    monkeypatch.setattr(
        common.urllib.request,
        "urlopen",
        Mock(side_effect=[Response(page(), total=2, following=following), second]),
    )
    with pytest.raises(ValueError):
        uniprot.run(codes=["hsa"], attempts=1)
    assert destination.read_bytes() == before
    with pytest.raises(ValueError, match="Incomplete"):
        recorded_selection(raw)
    assert not list(raw.glob("*.part"))


def test_empty_reviewed_result_is_complete_and_readable(tmp_path, monkeypatch):
    raw = configure(tmp_path, monkeypatch)
    monkeypatch.setattr(
        common.urllib.request, "urlopen", Mock(return_value=Response(page([]), total=0))
    )
    uniprot.run(codes=["hsa"])
    with selection(["hsa"]):
        assert list(reviewed_rows(raw)) == []


def test_pagination_rejects_external_host():
    with pytest.raises(ValueError, match="Untrusted"):
        uniprot.next_page('<https://example.invalid/steal>; rel="next"')


def test_changed_query_cannot_reuse_cached_export(tmp_path, monkeypatch):
    raw = configure(tmp_path, monkeypatch)
    raw.mkdir()
    url, destination = uniprot.planned_requests(["hsa"])[0]
    destination.write_bytes(gzip.compress(page()))
    metadata = {}
    uniprot.record(destination, url, metadata)
    assert uniprot.cached(destination, url, metadata)
    assert not uniprot.cached(destination, url + "&different=true", metadata)
    destination.write_bytes(gzip.compress(page(["CHANGED"])))
    assert not uniprot.cached(destination, url, metadata)


def test_legacy_manifest_without_selection_still_valid(tmp_path):
    from tests.make_fixture import generate as processed

    processed(tmp_path)
    path = tmp_path / "manifest.json"
    data = json.loads(path.read_text())
    data.pop("organisms")
    path.write_text(json.dumps(data))
    validate(tmp_path, "synthetic")


def setup_pipeline(home, monkeypatch):
    generate(home)
    monkeypatch.setattr(entities, "RAW_KEGG", home / "data/raw/kegg")
    monkeypatch.setattr(relations, "RAW_KEGG", home / "data/raw/kegg")
    monkeypatch.setattr(relations, "REPORTS", home / "artifacts")


def test_transform_subset_and_repeat_preserve_scope(tmp_path, monkeypatch):
    setup_pipeline(tmp_path, monkeypatch)
    output = tmp_path / "data/processed"
    for codes in [("hsa", "eco"), ("eco",), ("hsa", "eco")]:
        pipeline.run(output, tmp_path / "data/raw/uniprot", codes=codes)
        report, _ = validate(output)
        assert set(report["organisms"]) == set(codes)
        assert len(list(rows(output, BY_NAME["PROTEIN_UNIPROT"]))) == len(codes)
    assert {r["organism_id"] for r in rows(output, BY_NAME["ORGANISM"])} == {"1", "9"}


def test_transform_all_curated_organisms(tmp_path, monkeypatch):
    import tests.raw_fixture as fixture

    monkeypatch.setattr(fixture, "ORGANISMS", [(o.id, o.code) for o in CATALOG])
    setup_pipeline(tmp_path, monkeypatch)
    output = tmp_path / "data/processed"
    pipeline.run(output, tmp_path / "data/raw/uniprot", codes=select(all_organisms=True))
    report, _ = validate(output)
    assert len(report["organisms"]) == 16
    assert report["files"]["gene_protein.tsv"]["rows"] == 32


def test_managed_taxonomy_does_not_require_protein_xrefs(tmp_path, monkeypatch):
    setup_pipeline(tmp_path, monkeypatch)
    raw = tmp_path / "data/raw/uniprot"
    monkeypatch.setattr(uniprot, "RAW_ROOT", tmp_path / "data/raw")
    monkeypatch.setattr(uniprot, "RAW", raw)
    destination = raw / "9606_hsa.tsv.gz"
    destination.write_bytes(gzip.compress(page([])))
    url = uniprot.planned_requests(["hsa"])[0][0]
    uniprot.record(destination, url, {})
    common.selection_state(raw, ["hsa"], "complete", files=[destination.name])
    output = tmp_path / "data/processed"
    pipeline.run(output, raw, codes=["hsa"])
    report, _ = validate(output)
    assert report["files"]["protein_uniprot.tsv"]["rows"] == 0
    assert list(rows(output, BY_NAME["ORGANISM"]))[0]["taxonomy_id"] == "9606"


def test_detail_refresh_uses_only_active_index(tmp_path, monkeypatch):
    generate(tmp_path)
    root = tmp_path / "data/raw/kegg"
    monkeypatch.setattr(kegg, "ROOT", root)
    original = (root / "details/reaction/R00001.txt").read_text()
    (root / "details/reaction/old-overlap.txt").write_text(original)

    def fake_fetch(endpoint, relative, *args, **kwargs):
        if endpoint.startswith("/get/"):
            category = relative.split("/")[1]
            identifier = endpoint.removeprefix("/get/")
            source = root / f"details/{category}/{identifier}.txt"
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())

    monkeypatch.setattr(kegg, "fetch", fake_fetch)
    kegg.run(codes=["hsa"])
    records = list(detail_records(root / "details/reaction", {"R00001"}))
    assert len(records) == 1
    assert list(detail_records(root / "details/reaction", set())) == []
    indexed = root / "details/reaction/records/R00001.txt"
    indexed.write_text(original + "damage")
    with pytest.raises(ValueError, match="checksum"):
        list(detail_records(root / "details/reaction", {"R00001"}))


def test_pagination_link_can_contain_unescaped_field_commas():
    url = "https://rest.uniprot.org/uniprotkb/search?fields=accession,id,reviewed&cursor=second"
    assert uniprot.next_page(f'<{url}>; rel="next"') == url
    assert uniprot.next_page(f'<{url}>; rel="previous", <{url}>; rel="next"') == url


def test_final_rate_limit_preserves_server_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(common.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(common.time, "time", lambda: 1000)
    network = Mock(
        side_effect=urllib.error.HTTPError(
            "https://example.invalid", 429, "limit", {"Retry-After": "120"}, None
        )
    )
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    with pytest.raises(urllib.error.HTTPError):
        common.HttpClient(attempts=1).get("https://example.invalid", lambda r: r.read())
    delays = []
    monkeypatch.setattr(common.time, "sleep", delays.append)
    network.side_effect = [Response(b"ok")]
    assert common.HttpClient().get("https://example.invalid", lambda r: r.read()) == b"ok"
    assert 120 in delays
    assert not list(tmp_path.glob("*.json"))


def test_damaged_checkpoint_page_redownloads_from_that_page(tmp_path, monkeypatch):
    raw = configure(tmp_path, monkeypatch)
    following = "https://rest.uniprot.org/uniprotkb/search?cursor=second"
    network = Mock(side_effect=[Response(page(), total=2, following=following), TimeoutError()])
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    with pytest.raises(TimeoutError):
        uniprot.run(codes=["hsa"], attempts=1)
    directory = raw / ".pages/9606_hsa.tsv.gz"
    state = json.loads((directory / "state.json").read_text())
    (directory / state["pages"][0]["file"]).write_text("damaged")
    network.reset_mock()
    network.side_effect = [
        Response(page(), total=2, following=following),
        Response(page(["P00002"]), total=2),
    ]
    uniprot.run(codes=["hsa"], attempts=1)
    assert network.call_count == 2
    assert network.call_args_list[0].args[0].full_url == state["request"]


def test_mixed_releases_across_organisms_not_published(tmp_path, monkeypatch):
    raw = configure(tmp_path, monkeypatch)
    network = Mock(
        side_effect=[Response(page()), Response(page(["P00002"], taxid="10090"), release="2026_05")]
    )
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    with pytest.raises(ValueError, match="Mixed UniProt releases"):
        uniprot.run(codes=["hsa", "mmu"])
    with pytest.raises(ValueError, match="Incomplete"):
        recorded_selection(raw)


def test_managed_transform_rejects_active_source_writer(tmp_path, monkeypatch):
    setup_pipeline(tmp_path, monkeypatch)
    root = tmp_path / "data/raw/kegg"
    common.selection_state(root, ["hsa"], "complete")
    with common.file_lock(root / ".acquisition.lock"):
        with pytest.raises(RuntimeError, match="already running"):
            pipeline.run(tmp_path / "processed", tmp_path / "data/raw/uniprot")


def test_relationship_disk_sort_does_not_hide_invalid_rows():
    import sqlite3

    from unikegg.transforms.sorting import unique_rows

    assert list(unique_rows(iter([("b", "2"), ("a", "1"), ("a", "1")]), 2)) == [
        ("a", "1"),
        ("b", "2"),
    ]
    with pytest.raises(sqlite3.IntegrityError):
        list(unique_rows([(None, "invalid")], 2))
