"""Reviewed downloads by organism, numbered batch and cumulative selection."""

import gzip
import json
from unittest.mock import Mock

import pytest

from tests.test_download_resilience import Response, configure, page
from unikegg import cli
from unikegg.acquire import common, uniprot
from unikegg.acquire.reviewed import reviewed_rows
from unikegg.organisms import CATALOG, recorded_selection, select, selection


@pytest.fixture
def download(tmp_path, monkeypatch):
    raw = configure(tmp_path, monkeypatch)
    monkeypatch.setattr(common.time, "sleep", lambda _: None)
    monkeypatch.setattr(common.tempfile, "gettempdir", lambda: str(tmp_path))
    network = Mock(side_effect=AssertionError("Unexpected HTTP request"))
    monkeypatch.setattr(common.urllib.request, "urlopen", network)
    return raw, network


@pytest.mark.parametrize("size", [1, 3, 4, 16])
def test_all_organisms_are_partitioned_without_loss_or_duplicates(size):
    codes = select(all_organisms=True)
    groups = uniprot.plan_batches(codes, size)
    assert tuple(code for _, group in groups for code in group) == codes
    assert all(len(group) == size for _, group in groups[:-1])
    assert 1 <= len(groups[-1][1]) <= size


@pytest.mark.parametrize(
    "arguments",
    [
        ["--batch-size", "0"],
        ["--batch-size", "17"],
        ["--batch-size", "abc"],
        ["--batch", "1"],
        ["--batch-size", "4", "--batch", "0"],
        ["--batch-size", "4", "--batch", "5"],
    ],
)
def test_invalid_batches_fail_before_files_or_network(download, arguments):
    raw, network = download
    with pytest.raises(SystemExit) as error:
        cli.main(["download-uniprot", "--all-organisms", *arguments])
    assert error.value.code == 2
    network.assert_not_called()
    assert not raw.exists()


@pytest.mark.parametrize("command", ["download-kegg", "transform", "list-organisms", "update"])
@pytest.mark.parametrize("option", [["--batch-size", "4"], ["--batch", "1"], ["--append"]])
def test_uniprot_only_options_are_never_silently_ignored(download, command, option):
    raw, network = download
    with pytest.raises(SystemExit) as error:
        cli.main([command, *option])
    assert error.value.code == 2
    network.assert_not_called()
    assert not raw.exists()


def test_dry_run_selects_only_requested_batch_and_remains_read_only(download, capsys):
    raw, network = download
    cli.main([
        "download-uniprot", "--all-organisms", "--batch-size", "4", "--batch", "4", "--dry-run",
    ])
    output = capsys.readouterr().out
    assert "UniProt batch 4/4: gga,xtr,mtu,pae" in output
    assert output.count("GET ") == 4
    assert output.count("reviewed%3Atrue") == 4
    assert "9606_hsa" not in output
    network.assert_not_called()
    assert not raw.exists()


@pytest.mark.parametrize("codes", [("hsa",), ("eco", "spo", "pae")])
def test_single_and_manual_groups_download_only_selected_reviewed_exports(download, codes):
    raw, network = download
    network.side_effect = [
        Response(page([f"P{index:05d}"], taxid=organism.taxid))
        for index, organism in enumerate(CATALOG, 1) if organism.code in codes
    ]
    cli.main(["download-uniprot", "--organisms", ",".join(codes)])
    assert network.call_count == len(codes)
    assert recorded_selection(raw)["codes"] == codes
    with selection(codes):
        assert len(list(reviewed_rows(raw))) == len(codes)


@pytest.mark.parametrize("separate_runs", [False, True])
def test_all_sixteen_downloaded_together_or_in_cumulative_batches(download, separate_runs):
    raw, network = download
    network.side_effect = [
        Response(page([f"P{index:05d}"], taxid=organism.taxid))
        for index, organism in enumerate(CATALOG, 1)
    ]
    command = ["download-uniprot", "--all-organisms", "--batch-size", "3"]
    if separate_runs:
        for batch in range(1, 7):
            cli.main([*command, "--batch", str(batch), "--append"])
            assert len(recorded_selection(raw)["codes"]) == min(batch * 3, 16)
    else:
        cli.main(command)
    assert network.call_count == 16
    assert len(list(raw.glob("*.tsv.gz"))) == 16
    assert recorded_selection(raw)["codes"] == select(all_organisms=True)
    with selection(select(all_organisms=True)):
        assert len(list(reviewed_rows(raw))) == 16
    network.reset_mock()
    network.side_effect = AssertionError("Verified exports should be reused")
    cli.main(command)
    network.assert_not_called()


def test_append_dry_run_does_not_modify_previous_selection(download, capsys):
    raw, network = download
    network.side_effect = [Response(page())]
    uniprot.run(codes=["hsa"])
    before = {path: path.read_bytes() for path in raw.rglob("*") if path.is_file()}
    network.reset_mock()
    capsys.readouterr()
    cli.main(["download-uniprot", "--organisms", "mmu", "--append", "--dry-run"])
    output = capsys.readouterr().out
    assert "Retained UniProt organisms: hsa" in output
    assert output.count("GET ") == 2
    assert before == {path: path.read_bytes() for path in raw.rglob("*") if path.is_file()}
    network.assert_not_called()


def test_interrupted_append_resumes_and_rejects_a_different_batch(download):
    raw, network = download
    following = "https://rest.uniprot.org/uniprotkb/search?cursor=second"
    network.side_effect = [
        Response(page()),
        Response(page(["P00002"], taxid="10090"), total=2, following=following),
        TimeoutError("interrupted appended batch"),
    ]
    uniprot.run(codes=["hsa"])
    with pytest.raises(TimeoutError):
        uniprot.run(codes=["mmu"], append=True, attempts=1)
    with pytest.raises(ValueError, match="Incomplete"):
        recorded_selection(raw)
    before = (raw / "selection.json").read_bytes()
    network.reset_mock()
    with pytest.raises(ValueError, match="resume the same selection"):
        uniprot.run(codes=["rno"], append=True)
    network.assert_not_called()
    assert (raw / "selection.json").read_bytes() == before
    network.side_effect = [Response(page(["P00003"], taxid="10090"), total=2)]
    uniprot.run(codes=["mmu"], append=True, attempts=1)
    assert network.call_count == 1
    assert network.call_args.args[0].full_url == following
    assert recorded_selection(raw)["codes"] == ("hsa", "mmu")
    with selection(["hsa", "mmu"]):
        assert {row["Entry"] for row in reviewed_rows(raw)} == {"P00001", "P00002", "P00003"}


def test_mixed_releases_in_separate_batches_require_refresh(download):
    raw, network = download
    network.side_effect = [
        Response(page()),
        Response(page(["P00002"], taxid="10090"), release="2026_05"),
    ]
    uniprot.run(codes=["hsa"])
    with pytest.raises(ValueError, match="Mixed UniProt releases"):
        uniprot.run(codes=["mmu"], append=True)
    with pytest.raises(ValueError, match="Incomplete"):
        recorded_selection(raw)
    network.side_effect = [
        Response(page(), release="2026_05"),
        Response(page(["P00002"], taxid="10090"), release="2026_05"),
    ]
    uniprot.run(codes=["mmu"], append=True, refresh=True)
    assert recorded_selection(raw)["codes"] == ("hsa", "mmu")
    assert recorded_selection(raw)["release"] == "2026_05"


def test_interrupted_append_refresh_also_refreshes_retained_organisms(download):
    raw, network = download
    network.side_effect = [Response(page())]
    uniprot.run(codes=["hsa"])
    network.side_effect = [
        Response(page(["NEW001"]), release="2026_05"),
        TimeoutError("refresh stopped before new organism"),
    ]
    with pytest.raises(TimeoutError):
        uniprot.run(codes=["mmu"], append=True, refresh=True, attempts=1)
    network.reset_mock()
    network.side_effect = [Response(page(["NEW002"], taxid="10090"), release="2026_05")]
    uniprot.run(codes=["mmu"], append=True, attempts=1)
    assert network.call_count == 1
    assert recorded_selection(raw)["release"] == "2026_05"
    with selection(["hsa", "mmu"]):
        assert {row["Entry"] for row in reviewed_rows(raw)} == {"NEW001", "NEW002"}


def test_append_revalidates_retained_file_before_publishing(download):
    raw, network = download
    network.side_effect = [Response(page())]
    uniprot.run(codes=["hsa"])
    (raw / "9606_hsa.tsv.gz").write_bytes(b"damaged cached export")
    network.reset_mock()
    network.side_effect = [Response(page(["P00002"], taxid="10090"))]
    uniprot.run(codes=["mmu"], append=True)
    # The retained TSV is rebuilt from its verified page cache without HTTP.
    assert network.call_count == 1
    with selection(["hsa", "mmu"]):
        assert len(list(reviewed_rows(raw))) == 2


def test_optional_json_keeps_each_organism_in_its_batch(download):
    raw, network = download
    payload = {"results": [{
        "primaryAccession": "P00001",
        "entryType": "UniProtKB reviewed (Swiss-Prot)",
        "organism": {"taxonId": 9606},
    }]}
    network.side_effect = [Response(gzip.compress(json.dumps(payload).encode())), Response(page())]
    cli.main([
        "download-uniprot", "--all-organisms", "--batch-size", "1", "--batch", "1",
        "--include-json",
    ])
    assert network.call_count == 2
    state = recorded_selection(raw)
    assert state["codes"] == ("hsa",)
    assert set(state["files"]) == {"9606_hsa.json.gz", "9606_hsa.tsv.gz"}


def test_all_batches_resume_after_completed_group_without_redownloading(download):
    raw, network = download
    network.side_effect = [
        Response(page([f"P{index:05d}"], taxid=organism.taxid))
        for index, organism in enumerate(CATALOG[:4], 1)
    ] + [TimeoutError("stopped at next batch")]
    codes = select(all_organisms=True)
    with pytest.raises(TimeoutError):
        uniprot.run(codes=codes, batch_size=4, attempts=1)
    with pytest.raises(ValueError, match="Incomplete"):
        recorded_selection(raw)
    network.reset_mock()
    network.side_effect = [
        Response(page([f"P{index:05d}"], taxid=organism.taxid))
        for index, organism in enumerate(CATALOG[4:], 5)
    ]
    uniprot.run(codes=codes, batch_size=4, attempts=1)
    assert network.call_count == 12
    assert recorded_selection(raw)["codes"] == codes


@pytest.mark.parametrize("invalid", ["unreviewed", "wrong-organism"])
def test_invalid_appended_export_is_never_published(download, invalid):
    raw, network = download
    network.side_effect = [Response(page())]
    uniprot.run(codes=["hsa"])
    network.side_effect = [Response(page(
        ["P00002"], taxid="9606" if invalid == "wrong-organism" else "10090",
        reviewed="unreviewed" if invalid == "unreviewed" else "reviewed",
    ))]
    with pytest.raises(ValueError):
        uniprot.run(codes=["mmu"], append=True, attempts=1)
    assert not (raw / "10090_mmu.tsv.gz").exists()
    with pytest.raises(ValueError, match="Incomplete"):
        recorded_selection(raw)


def test_without_append_selection_can_still_be_narrowed(download):
    raw, network = download
    network.side_effect = [Response(page()), Response(page(["P00002"], taxid="10090"))]
    uniprot.run(codes=["hsa", "mmu"], batch_size=1)
    network.reset_mock()
    uniprot.run(codes=["hsa"])
    network.assert_not_called()
    assert recorded_selection(raw)["codes"] == ("hsa",)
    assert (raw / "10090_mmu.tsv.gz").exists()
