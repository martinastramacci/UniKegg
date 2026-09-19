"""Exercise rejection paths before SQL ingestion."""

import csv
import gzip
import json
from pathlib import Path

import pytest

from tests.make_fixture import generate
from unikegg.acquire.reviewed import reviewed_rows
from unikegg.dataset import manifest, validate
from unikegg.loader import load_statements


def test_path_with_apostrophe_and_semicolon():
    sql = "LOAD DATA LOCAL INFILE '{{DATA_DIR}}/organismo.tsv' INTO TABLE ORGANISMO;"
    result = list(load_statements(sql, Path("/data/owner's;files")))
    assert len(result) == 1
    assert 'INFILE "/data/owner\'s;files/organismo.tsv"' in result[0]


def rewrite(directory, filename, mutate):
    path = directory / filename
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream, delimiter="\t"))
    mutate(rows)
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)
    manifest(directory, "synthetic")


def test_complete_fixture(tmp_path):
    report, fingerprint = validate(generate(tmp_path), "synthetic")
    assert len(report["files"]) == 20
    assert len(fingerprint) == 64


def test_synthetic_cannot_claim_swissprot(tmp_path):
    generate(tmp_path)
    with pytest.raises(ValueError, match="kind mismatch"):
        validate(tmp_path)
    with pytest.raises(ValueError, match="require reviewed"):
        manifest(tmp_path, "swissprot")
    with pytest.raises(ValueError, match="outside verified"):
        manifest(tmp_path, "swissprot", set())


def test_sequence_mismatch(tmp_path):
    generate(tmp_path)
    rewrite(tmp_path, "protein_uniprot.tsv", lambda rows: rows[1].__setitem__(-1, "M"))
    with pytest.raises(ValueError, match="Invalid protein sequence"):
        validate(tmp_path, "synthetic")


def test_cross_species_mapping(tmp_path):
    generate(tmp_path)
    rewrite(tmp_path, "gene_proteina.tsv", lambda rows: rows[1].__setitem__(1, "SYN000002"))
    with pytest.raises(ValueError, match="Organism mismatch"):
        validate(tmp_path, "synthetic")


def test_orphan(tmp_path):
    generate(tmp_path)
    rewrite(tmp_path, "reazione_ec.tsv", lambda rows: rows[1].__setitem__(1, "9.9.9.9"))
    with pytest.raises(ValueError, match="Orphan reference"):
        validate(tmp_path, "synthetic")


def test_duplicate_key(tmp_path):
    generate(tmp_path)
    rewrite(tmp_path, "numero_ec.tsv", lambda rows: rows.append(rows[1]))
    with pytest.raises(ValueError, match="duplicate key"):
        validate(tmp_path, "synthetic")


def test_checksum_mismatch(tmp_path):
    generate(tmp_path)
    path = tmp_path / "numero_ec.tsv"
    with path.open("a", encoding="utf-8") as stream:
        stream.write("9.9.9.9\n")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        validate(tmp_path, "synthetic")


@pytest.mark.parametrize("status", ["unreviewed", "", "TrEMBL"])
def test_reviewed_gate(tmp_path, status):
    with gzip.open(tmp_path / "source.tsv.gz", "wt", encoding="utf-8") as stream:
        stream.write(f"Entry\tReviewed\nP00001\t{status}\n")
    with pytest.raises(ValueError):
        list(reviewed_rows(tmp_path))


def test_reviewed_source(tmp_path):
    with gzip.open(tmp_path / "source.tsv.gz", "wt", encoding="utf-8") as stream:
        stream.write("Entry\tReviewed\nP00001\treviewed\n")
    assert list(reviewed_rows(tmp_path))[0]["Entry"] == "P00001"


def test_large_upstream_annotation(tmp_path):
    with gzip.open(tmp_path / "source.tsv.gz", "wt", encoding="utf-8") as stream:
        stream.write("Entry\tReviewed\tAnnotation\nP00001\treviewed\t" + "A" * 200000 + "\n")
    assert len(list(reviewed_rows(tmp_path))[0]["Annotation"]) == 200000


def test_mixed_snapshots_rejected(tmp_path):
    for name in ["first.tsv.gz", "second.tsv.gz"]:
        with gzip.open(tmp_path / name, "wt", encoding="utf-8") as stream:
            stream.write("Entry\tReviewed\nP00001\treviewed\n")
    with pytest.raises(ValueError, match="duplicate upstream"):
        list(reviewed_rows(tmp_path))


def test_manifest_version(tmp_path):
    generate(tmp_path)
    path = tmp_path / "manifest.json"
    report = json.loads(path.read_text())
    report["format_version"] = 0
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="version"):
        validate(tmp_path, "synthetic")
