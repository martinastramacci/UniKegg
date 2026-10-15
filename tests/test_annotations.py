"""Enzyme enrichment and selective name cleanup preserve biological annotations."""

import json
import lzma
from unittest.mock import Mock

import pytest

from tests.make_fixture import generate
from tests.raw_fixture import ENZYME_RDF
from tests.raw_fixture import generate as generate_raw
from tests.test_contracts import rewrite
from tests.test_english_names import legacy_bundle
from tests.test_transform import command
from tools.migrate_annotations import run
from tools.migrate_dataset_names import run as rename_bundle
from unikegg import cli, tsv
from unikegg.acquire import enzymes
from unikegg.dataset import BY_NAME, rows, sha256, validate
from unikegg.enzymes import read_catalog
from unikegg.identifiers import without_ec_annotations


@pytest.mark.parametrize("source, expected", [
    ("Alcohol (NAD(+)) (EC 1.1.1.1) (ADH)", "Alcohol (NAD(+)) (ADH)"),
    ("Protein (EC 3.5.1.n3) (EC 1.1.-.-)", "Protein"),
    ("Protein [EC:1.1.1.1 2.7.1.1]", "Protein"),
    ("Protein (EC 1.1.1.1; 2.7.1.1)", "Protein"),
    ("Protein (EC 1.1.1.-, EC 1.1.1.232)", "Protein"),
    ("Transcription factor EC (TFE-C)", "Transcription factor EC (TFE-C)"),
    ("Protein (EC 1.1.1.1junk)", "Protein (EC 1.1.1.1junk)"),
    ("Protein (EC 1.1.1.1 inhibitor)", "Protein (EC 1.1.1.1 inhibitor)"),
    ("[Cleaved into: A (EC 1.1.1.1); B]", "[Cleaved into: A; B]"),
])
def test_only_ec_blocks_are_removed(source, expected):
    assert without_ec_annotations(source) == expected
    assert without_ec_annotations(expected) == expected


def test_catalog_resolves_activity_references_and_rejects_damage(tmp_path):
    path = tmp_path / "enzyme.rdf.xz"
    path.write_bytes(lzma.compress(ENZYME_RDF))
    assert read_catalog(path) == {"1.1.1.1": ["Synthetic enzyme", "A = B", "Synthetic comment."]}
    path.write_bytes(lzma.compress(ENZYME_RDF.replace(b'rdf:resource="1.1.1.1#activity"', b'rdf:resource="missing"')))
    with pytest.raises(ValueError, match="Unresolved"):
        read_catalog(path)
    path.write_bytes(lzma.compress(b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>'))
    with pytest.raises(ValueError, match="Empty"):
        read_catalog(path)


def test_enzyme_acquisition_cache_and_failed_refresh_preserve_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(enzymes, "ROOT", tmp_path)
    client = Mock()
    client.get.return_value = lzma.compress(ENZYME_RDF)
    monkeypatch.setattr(enzymes, "HttpClient", Mock(return_value=client))
    enzymes.run()
    before = (tmp_path / "enzyme.rdf.xz").read_bytes()
    enzymes.run()
    assert client.get.call_count == 1
    client.get.return_value = b"invalid"
    with pytest.raises(lzma.LZMAError):
        enzymes.run(refresh=True)
    assert (tmp_path / "enzyme.rdf.xz").read_bytes() == before
    assert not list(tmp_path.glob("*.part"))
    (tmp_path / "enzyme.rdf.xz").write_bytes(before + b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        read_catalog(tmp_path / "enzyme.rdf.xz")


def test_enzyme_cli_dry_run_is_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(enzymes, "ROOT", tmp_path / "absent")
    network = Mock()
    monkeypatch.setattr(enzymes, "HttpClient", network)
    cli.main(["download-enzymes", "--dry-run"])
    network.assert_not_called()
    assert not (tmp_path / "absent").exists()


def test_transform_enriches_known_ec_and_preserves_unknown(tmp_path):
    generate_raw(tmp_path)
    result = command(tmp_path, "transform")
    assert result.returncode == 0, result.stderr
    output = tmp_path / "data/processed"
    ecs = {r["ec_number"]: r for r in rows(output, BY_NAME["EC_NUMBER"])}
    assert ecs["1.1.1.1"]["catalytic_activity"] == "A = B"
    assert ecs["3.5.1.n3"]["name"] == ""
    assert next(rows(output, BY_NAME["PROTEIN_UNIPROT"]))["protein_name"] == "Synthetic protein (NAD(+))"
    assert all(set(r) == {"accession", "go_id"} for r in rows(output, BY_NAME["PROTEIN_GO"]))


def test_bundle_migration_preserves_source_and_links(tmp_path):
    source = generate(tmp_path / "source")
    rewrite(source, "protein_uniprot.tsv", lambda r: r[1].__setitem__(3, "Protein (NAD(+)) (EC 1.1.1.1)"))
    metadata = json.loads((source / "manifest.json").read_text())
    for filename in ["ec_number.tsv", "protein_go.tsv"]:
        path = source / filename
        with path.open() as stream:
            data = list(tsv.reader(stream))
        if filename == "ec_number.tsv":
            data = [[r[0]] for r in data]
        else:
            data = [data[0] + ["evidence_code", "evidence_source"],
                    *[r + ["", "UniProt export"] for r in data[1:]]]
        with path.open("w", newline="") as stream:
            tsv.writer(stream).writerows(data)
        metadata["files"][filename]["sha256"] = sha256(path)
    (source / "manifest.json").write_text(json.dumps(metadata))
    catalog = tmp_path / "enzyme.rdf.xz"
    catalog.write_bytes(lzma.compress(ENZYME_RDF))
    before = {p.name: sha256(p) for p in source.iterdir()}
    output = tmp_path / "output"
    changes = run(source, output, catalog)
    validate(output, "synthetic")
    assert changes["PROTEIN_UNIPROT"] == 1
    assert next(rows(output, BY_NAME["PROTEIN_UNIPROT"]))["protein_name"] == "Protein (NAD(+))"
    assert (source / "protein_ec.tsv").read_bytes() == (output / "protein_ec.tsv").read_bytes()
    assert before == {p.name: sha256(p) for p in source.iterdir()}
    with pytest.raises(ValueError, match="absent or empty"):
        run(source, output, catalog)
    (source / "protein_go.tsv").write_text("corrupt")
    with pytest.raises(ValueError, match="checksum"):
        run(source, tmp_path / "failed", catalog)
    assert not (tmp_path / "failed").exists()


def test_italian_bundle_also_upgrades_old_annotation_columns(tmp_path):
    source = tmp_path / "legacy"
    legacy_bundle(source)
    ec = source / "numero_ec.tsv"
    ec.write_text('"ec_number"\n"1.1.1.1"\n')
    metadata = json.loads((source / "manifest.json").read_text())
    metadata["files"][ec.name]["sha256"] = sha256(ec)
    (source / "manifest.json").write_text(json.dumps(metadata))
    catalog = tmp_path / "enzyme.rdf.xz"
    catalog.write_bytes(lzma.compress(ENZYME_RDF))
    output = tmp_path / "english"
    rename_bundle(source, output, catalog)
    validate(output, "synthetic")
    assert next(rows(output, BY_NAME["EC_NUMBER"]))["name"] == "Synthetic enzyme"
    assert ec.read_text() == '"ec_number"\n"1.1.1.1"\n'
