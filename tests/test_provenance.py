"""Snapshot identity remains deterministic and never invents source releases."""

import json

import pytest

from tests.make_fixture import generate as processed
from tests.raw_fixture import generate
from tests.test_transform import command
from unikegg.dataset import sha256
from unikegg.provenance import capture, source_snapshot
from unikegg.transforms import entities, pipeline, relations


def test_snapshot_release_and_caches(tmp_path):
    root = tmp_path / "uniprot"
    root.mkdir()
    raw = root / "export.tsv.gz"
    raw.write_bytes(b"test")
    metadata = {"file": "uniprot/export.tsv.gz", "sha256": sha256(raw),
                "release": "test-release", "data_utc": "2026-01-01T00:00:00Z"}
    (root / "manifest.jsonl").write_text(json.dumps(metadata) + "\n")
    before = source_snapshot(root)
    assert before["releases"] == ["test-release"]
    (root / ".pages").mkdir()
    (root / ".pages/page").write_text("cache")
    (root / ".acquisition.lock").touch()
    assert source_snapshot(root) == before
    raw.write_bytes(b"changed")
    after = source_snapshot(root)
    assert after["snapshot_sha256"] != before["snapshot_sha256"]
    assert after["releases"] == []


def test_transform_links_sources_code_and_quality(tmp_path):
    generate(tmp_path)
    result = command(tmp_path, "transform")
    assert result.returncode == 0, result.stderr
    manifest = json.loads((tmp_path / "data/processed/manifest.json").read_text())
    provenance = manifest["provenance"]
    assert provenance == capture(tmp_path / "data/raw/kegg", tmp_path / "data/raw/uniprot")
    assert len(provenance["software"]["source_sha256"]) == 64
    assert provenance["sources"]["uniprot"]["releases"] == []
    assert manifest["quality"]["organisms"]["hsa"]["both_sources"] == 1


def test_changed_source_preserves_previous_bundle(tmp_path, monkeypatch):
    generate(tmp_path)
    destination = processed(tmp_path / "data/processed")
    previous = (destination / "manifest.json").read_bytes()
    raw = tmp_path / "data/raw/kegg"
    monkeypatch.setattr(entities, "RAW_KEGG", raw)
    monkeypatch.setattr(relations, "RAW_KEGG", raw)
    monkeypatch.setattr(relations, "REPORTS", tmp_path / "reports")
    original = relations.main

    def mutate():
        original()
        (raw / "genes/hsa_genes.tsv").write_text("changed during transform")

    monkeypatch.setattr(relations, "main", mutate)
    with pytest.raises(ValueError, match="changed during transformation"):
        pipeline.run(destination, tmp_path / "data/raw/uniprot")
    assert (destination / "manifest.json").read_bytes() == previous
