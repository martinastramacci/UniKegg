"""Direct KO assertions must survive normalization, publication and validation."""

import re
from pathlib import Path

import pytest

from tests.make_fixture import generate as make_processed
from tests.raw_fixture import generate as make_raw
from tests.raw_fixture import raw_tsv
from tests.test_contracts import rewrite
from tests.test_transform import command, contents
from unikegg.dataset import BY_NAME, rows, validate
from unikegg.kegg_data import requests

ROOT = Path(__file__).resolve().parents[1]


def test_direct_many_to_many_links_and_ec_only_in_ko(tmp_path):
    make_raw(tmp_path)
    raw = tmp_path / "data/raw/kegg"
    raw_tsv(raw / "ko/ko_list.tsv", [[f"K0000{i}", "Synthetic KO"] for i in (1, 2, 3)])
    raw_tsv(
        raw / "pathway/pathway_reference.tsv",
        [["map00010", "First pathway"], ["map00020", "Second pathway"]],
    )
    pathway = [
        ["ko:K00001", "path:map00010"],
        ["ko:K00001", "path:ko00010"],
        ["K00001", "ko00020"],
        ["ko:K00002", "path:ko00010"],
    ]
    ecs = [
        ["ko:K00001", "ec:2.7.1.999"],
        ["ko:K00001", "ec:3.5.1.n3"],
        ["ko:K00002", "ec:2.7.1.999"],
        ["K00002", "1.1.1.-"],
        ["K00001", "2.7.1.999"],
    ]
    raw_tsv(raw / "relations/ko_pathway.tsv", pathway)
    raw_tsv(raw / "relations/ko_ec.tsv", ecs)
    result = command(tmp_path, "transform")
    assert result.returncode == 0, result.stderr
    output = tmp_path / "data/processed"
    validate(output)
    assert list(rows(output, BY_NAME["ORTOLOGIA_PATHWAY"])) == [
        {"ko_id": "K00001", "map_id": "map00010"},
        {"ko_id": "K00001", "map_id": "map00020"},
        {"ko_id": "K00002", "map_id": "map00010"},
    ]
    assert len(list(rows(output, BY_NAME["ORTOLOGIA_EC"]))) == 4
    assert {r["ec_number"] for r in rows(output, BY_NAME["NUMERO_EC"])} == {
        "1.1.1.1", "3.5.1.n3", "2.7.1.999", "1.1.1.-"
    }
    assert "2.7.1.999" not in (output / "reazione_ec.tsv").read_text()
    before = contents(output)
    raw_tsv(raw / "relations/ko_pathway.tsv", reversed(pathway))
    raw_tsv(raw / "relations/ko_ec.tsv", reversed(ecs))
    assert command(tmp_path, "transform").returncode == 0
    assert before == contents(output)


@pytest.mark.parametrize(
    "kind, values",
    [
        ("pathway", None), ("ec", None),
        ("pathway", ["ko:K99999", "path:map00010"]),
        ("pathway", ["ko:K00001", "path:map99999"]),
        ("pathway", ["ko:K00001", "path:hsa00010"]),
        ("pathway", ["ko:K00001", "path:ko00010x"]),
        ("pathway", ["path:ko00010", "ko:K00001"]),
        ("ec", ["ko:K99999", "ec:1.1.1.1"]),
        ("ec", ["ko:K00001", "ec:1.1.1.1junk"]),
        ("ec", ["ko:K00001", "ec:"]),
        ("ec", ["ko:K00001", "ec:1.1.1.1", "extra"]),
        ("ec", ["ec:1.1.1.1", "ko:K00001"]),
    ],
)
def test_bad_direct_links_preserve_previous_bundle(tmp_path, kind, values):
    make_raw(tmp_path)
    output = make_processed(tmp_path / "data/processed")
    before = contents(output)
    path = tmp_path / f"data/raw/kegg/relations/ko_{kind}.tsv"
    if values is None:
        path.unlink()
    else:
        raw_tsv(path, [values])
    assert command(tmp_path, "transform").returncode != 0
    assert before == contents(output)


def test_empty_direct_links_are_valid(tmp_path):
    make_raw(tmp_path)
    for kind in ("pathway", "ec"):
        raw_tsv(tmp_path / f"data/raw/kegg/relations/ko_{kind}.tsv", [])
    result = command(tmp_path, "transform")
    assert result.returncode == 0, result.stderr
    report, _ = validate(tmp_path / "data/processed")
    for kind in ("pathway", "ec"):
        assert report["files"][f"ortologia_{kind}.tsv"]["rows"] == 0


@pytest.mark.parametrize("kind,orphan", [("pathway", "map99999"), ("ec", "9.9.9.9")])
@pytest.mark.parametrize("damage", ["duplicate", "orphan"])
def test_processed_links_reject_duplicates_and_orphans(tmp_path, kind, orphan, damage):
    make_processed(tmp_path)
    rewrite(
        tmp_path, f"ortologia_{kind}.tsv",
        lambda data: data.append(data[1]) if damage == "duplicate" else data[1].__setitem__(1, orphan),
    )
    with pytest.raises(ValueError, match="duplicate key|Orphan reference"):
        validate(tmp_path, "synthetic")


def test_migration_matches_fresh_schema_and_acquisition_direction():
    fresh = (ROOT / "db/init/001_schema.sql").read_text()
    migration = (ROOT / "db/migrations/004_orthology_links.sql").read_text()
    blocks = re.findall(r"CREATE TABLE IF NOT EXISTS .*?;", migration, re.S)
    assert len(blocks) == 2
    for block in blocks:
        assert block.replace("IF NOT EXISTS ", "") in fresh
    assert ("/link/pathway/ko", "relations/ko_pathway.tsv") in requests()
    assert ("/link/enzyme/ko", "relations/ko_ec.tsv") in requests()
