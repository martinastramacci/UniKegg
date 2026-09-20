"""SQL contract parity, large fields and legacy-bundle transport tests."""

import csv
import json
from pathlib import Path

import pytest

from tests.make_fixture import generate
from tests.test_contracts import rewrite
from unikegg.dataset import (
    BY_NAME,
    TABLES,
    manifest,
    quote_for_mysql,
    rows,
    validate,
    verified_snapshot,
)


@pytest.mark.parametrize(
    "case",
    [
        "duplicate-entry-name",
        "duplicate-taxonomy",
        "duplicate-kegg-code",
        "duplicate-pathway-grain",
        "duplicate-isoform-ordinal",
        "invalid-decimal",
        "zero-taxonomy",
        "oversized-utf8-text",
        "collation-equivalent-pk",
        "numeric-equivalent-pk",
        "unicode-key",
        "space-key",
        "null-byte-key",
    ],
)
def test_sql_contract_violations_rejected(tmp_path, case):
    generate(tmp_path)
    if case == "duplicate-entry-name":
        rewrite(tmp_path, "protein_uniprot.tsv", lambda data: data[2].__setitem__(2, data[1][2]))
    elif case == "duplicate-taxonomy":
        rewrite(tmp_path, "organismo.tsv", lambda data: data[2].__setitem__(2, data[1][2]))
    elif case == "duplicate-kegg-code":
        rewrite(
            tmp_path,
            "organismo.tsv",
            lambda data: data.append([11, data[1][1], 9999999, "Synthetic extra"]),
        )
    elif case == "duplicate-pathway-grain":
        rewrite(
            tmp_path,
            "pathway_organismo.tsv",
            lambda data: data.append(["ath00011", data[1][1], data[1][2]]),
        )
    elif case == "duplicate-isoform-ordinal":
        rewrite(
            tmp_path,
            "protein_isoform.tsv",
            lambda data: data.append(
                [
                    data[1][1] + "-2",
                    data[1][1],
                    data[1][2],
                    "Synthetic second",
                    "DESCRIBED",
                    "",
                ]
            ),
        )
    elif case == "invalid-decimal":
        rewrite(tmp_path, "composto_kegg.tsv", lambda data: data[1].__setitem__(3, "not-a-number"))
    elif case == "zero-taxonomy":
        rewrite(tmp_path, "organismo.tsv", lambda data: data[1].__setitem__(2, "0"))
    elif case == "oversized-utf8-text":
        rewrite(tmp_path, "protein_uniprot.tsv", lambda data: data[1].__setitem__(3, "é" * 40000))
    elif case == "collation-equivalent-pk":
        rewrite(
            tmp_path, "gene_kegg.tsv", lambda data: data.append([data[1][0].upper(), *data[1][1:]])
        )
    elif case == "numeric-equivalent-pk":
        rewrite(
            tmp_path, "organismo.tsv", lambda data: data.append(["01", "oth", 9999999, "Synthetic"])
        )
    else:
        value = {"unicode-key": "É00001", "space-key": "K00001 ", "null-byte-key": "K\0"}[case]
        rewrite(tmp_path, "ortologia_kegg.tsv", lambda data: data[1].__setitem__(0, value))
    with pytest.raises(ValueError):
        validate(tmp_path, "synthetic")


@pytest.mark.parametrize(
    "value", ["NaN", "Infinity", "1.23456789012", "1e-11", "1e14", "-1e14", "1,2"]
)
def test_decimal_domain_rejected(tmp_path, value):
    generate(tmp_path)
    rewrite(tmp_path, "composto_kegg.tsv", lambda data: data[1].__setitem__(3, value))
    with pytest.raises(ValueError, match="decimal"):
        validate(tmp_path, "synthetic")


@pytest.mark.parametrize(
    "value", ["", "0", "1e3", "-0.01", ".1234567890", "99999999999999.9999999999"]
)
def test_decimal_domain_accepted(tmp_path, value):
    generate(tmp_path)
    rewrite(tmp_path, "composto_kegg.tsv", lambda data: data[1].__setitem__(3, value))
    validate(tmp_path, "synthetic")


@pytest.mark.parametrize("value", ["4294967296", "-1", "1.0", "١", "²"])
def test_bad_unsigned_integer(tmp_path, value):
    generate(tmp_path)
    rewrite(tmp_path, "protein_uniprot.tsv", lambda data: data[1].__setitem__(5, value))
    with pytest.raises(ValueError, match="unsigned integer"):
        validate(tmp_path, "synthetic")


def test_numeric_fk_normalization(tmp_path):
    generate(tmp_path)
    rewrite(tmp_path, "gene_kegg.tsv", lambda data: data[1].__setitem__(1, "01"))
    validate(tmp_path, "synthetic")


def test_bytes_not_codepoints_for_text(tmp_path):
    generate(tmp_path)
    rewrite(tmp_path, "protein_uniprot.tsv", lambda data: data[1].__setitem__(3, "é" * 32767))
    validate(tmp_path, "synthetic")
    rewrite(tmp_path, "protein_uniprot.tsv", lambda data: data[1].__setitem__(3, "é" * 32768))
    with pytest.raises(ValueError, match="text byte limit"):
        validate(tmp_path, "synthetic")


def test_reader_configures_own_field_limit(tmp_path):
    generate(tmp_path)
    previous = csv.field_size_limit(64)
    try:
        table = BY_NAME["PROTEIN_UNIPROT"]
        data = list(rows(tmp_path, table))
        data[0]["amino_acid_sequence"] = "A" * 200000
        data[0]["sequence_length"] = "200000"
        with (tmp_path / table["file"]).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=table["columns"], delimiter="\t", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(data)
        csv.field_size_limit(64)
        manifest(tmp_path, "synthetic")
        csv.field_size_limit(64)
        validate(tmp_path, "synthetic")
    finally:
        csv.field_size_limit(previous)


def test_blank_and_unterminated_csv_rows_rejected(tmp_path):
    generate(tmp_path)
    path = tmp_path / "numero_ec.tsv"
    for content in ["ec_number\n\n", 'ec_number\n"unterminated\n']:
        path.write_text(content)
        with pytest.raises(ValueError, match="Invalid column count|Invalid TSV"):
            list(rows(tmp_path, BY_NAME["NUMERO_EC"]))


@pytest.mark.parametrize(
    "metadata",
    [
        {"rows": True, "sha256": "a" * 64},
        {"rows": -1, "sha256": "a" * 64},
        {"rows": 1, "sha256": None},
    ],
)
def test_manifest_file_metadata_shape(tmp_path, metadata):
    generate(tmp_path)
    path = tmp_path / "manifest.json"
    report = json.loads(path.read_text())
    report["files"]["organismo.tsv"] = metadata
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="metadata"):
        validate(tmp_path, "synthetic")


def test_private_transport_preserves_values_and_source_bundle(tmp_path):
    generate(tmp_path)
    complex_text = 'Line one\nLine two\t"quoted" \\path café 🧬'
    rewrite(tmp_path, "gene_kegg.tsv", lambda data: data[1].__setitem__(3, "NULL"))
    rewrite(tmp_path, "protein_uniprot.tsv", lambda data: data[1].__setitem__(3, complex_text))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert b"\tNULL\t" in before["gene_kegg.tsv"]  # legacy QUOTE_MINIMAL bundle
    with verified_snapshot(tmp_path, "synthetic") as (snapshot, report, fingerprint):
        assert snapshot != tmp_path
        expected = {table["name"]: list(rows(snapshot, table)) for table in TABLES}
        quote_for_mysql(snapshot)
        assert '"NULL"' in (snapshot / "gene_kegg.tsv").read_text()
        assert len(fingerprint) == 64 and len(report["files"]) == 20
        for table in TABLES:
            assert list(rows(snapshot, table)) == expected[table["name"]]
        assert snapshot.exists()
    assert not snapshot.exists()
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_snapshot_immune_to_later_source_mutation(tmp_path):
    generate(tmp_path)
    with verified_snapshot(tmp_path, "synthetic") as (snapshot, _, _):
        original = (snapshot / "gene_kegg.tsv").read_bytes()
        (tmp_path / "gene_kegg.tsv").write_bytes(b"modified after validation\n")
        quote_for_mysql(snapshot)
        assert list(rows(snapshot, BY_NAME["GENE_KEGG"]))
        assert (tmp_path / "gene_kegg.tsv").read_bytes() != original
    assert not snapshot.exists()


def test_column_contract_matches_ddl():
    import re

    sql = (Path(__file__).resolve().parents[1] / "db/init/001_schema.sql").read_text()
    blocks = dict(re.findall(r"CREATE TABLE (\w+) \((.*?)\n\);", sql, re.S))
    assert set(blocks) == set(BY_NAME)
    for table in TABLES:
        block = blocks[table["name"]]
        for column, spec in table["specs"].items():
            actual = re.search(r"^    " + column + r" (.*?)(?:,)?$", block, re.M)[1]
            assert re.sub(r"\s+", "", actual).rstrip(",") == re.sub(r"\s+", "", spec)
        unique = {(column,) for column, spec in table["specs"].items() if " UNIQUE" in spec}
        unique.update(
            tuple(c.strip() for c in key.split(","))
            for key in re.findall(r"UNIQUE \(([^)]+)\)", block)
        )
        assert unique == {tuple(key) for key in table.get("unique", [])}


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX umask semantics")
def test_manifest_atomic_write_honors_bundle_permissions(tmp_path):
    import os
    import stat

    old_umask = os.umask(0o022)
    try:
        generate(tmp_path)
        path = tmp_path / "manifest.json"
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
        path.chmod(0o640)
        manifest(tmp_path, "synthetic")
        assert stat.S_IMODE(path.stat().st_mode) == 0o640
        assert not list(tmp_path.glob(".unikegg-manifest-*.tmp"))
    finally:
        os.umask(old_umask)
