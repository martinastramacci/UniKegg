"""No legacy migration may silently drop a source assertion or fabricate a KO."""

import json

import pytest

from tests.raw_fixture import generate, raw_tsv
from tools.migrate_legacy_dump import direct_links


@pytest.mark.parametrize(
    "status,url",
    [(200, "https://rest.kegg.jp/get/K99999"), (404, "https://rest.kegg.jp/get/K00001")],
)
def test_missing_ko_requires_matching_not_found_evidence(tmp_path, status, url):
    generate(tmp_path)
    raw = tmp_path / "data/raw/kegg"
    raw_tsv(raw / "relations/ko_ec.tsv", [["ko:K99999", "ec:1.1.1.1"]])
    with pytest.raises(ValueError, match="independent KEGG verification"):
        direct_links(raw)
    (raw / "missing_ko_checks.json").write_text(
        json.dumps({"K99999": {"url": url, "status": status}})
    )
    with pytest.raises(ValueError, match="independent KEGG verification"):
        direct_links(raw)


def test_verified_orphan_is_quarantined_and_valid_links_preserved(tmp_path):
    generate(tmp_path)
    raw = tmp_path / "data/raw/kegg"
    raw_tsv(
        raw / "relations/ko_ec.tsv",
        [
            ["ko:K99999", "ec:1.1.1.1"],
            ["ko:K00001", "ec:3.5.1.n3"],
            ["ko:K00001", "ec:3.5.1.n3"],
        ],
    )
    (raw / "missing_ko_checks.json").write_text(
        json.dumps({"K99999": {"url": "https://rest.kegg.jp/get/K99999", "status": 404}})
    )
    links, excluded = direct_links(raw)
    assert links == {"pathway": [("K00001", "map00010")], "ec": [("K00001", "3.5.1.n3")]}
    assert len(excluded) == 1
    assert excluded[0]["ko_id"] == "K99999"
    assert excluded[0]["verification"]["status"] == 404
    assert "K99999" in (raw / "relations/ko_ec.tsv").read_text()


def test_malformed_relationship_is_never_quarantined(tmp_path):
    generate(tmp_path)
    raw = tmp_path / "data/raw/kegg"
    raw_tsv(raw / "relations/ko_ec.tsv", [["ko:K00001", "ec:1.1.1.1junk"]])
    with pytest.raises(ValueError, match="Malformed"):
        direct_links(raw)
