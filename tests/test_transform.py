"""Offline raw-to-TSV and failure-preservation regression tests."""

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from tests.make_fixture import generate as make_processed
from tests.raw_fixture import generate as make_raw
from tests.raw_fixture import raw_tsv, write_uniprot
from unikegg import tsv
from unikegg.dataset import BY_NAME, manifest, rows, validate
from unikegg.identifiers import EC_RE
from unikegg.kegg_data import detail_records, flat_records, preflight
from unikegg.transforms import entities, pipeline, relations

ROOT = Path(__file__).resolve().parents[1]


def command(home, *args, extra_env=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith("UNIKEGG_")}
    env.update({"UNIKEGG_HOME": str(home), "PYTHONPATH": str(ROOT / "src")})
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-m", "unikegg.cli", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )


def contents(directory):
    return {path.name: path.read_bytes() for path in directory.iterdir()}


def test_raw_transform_repeat_and_external_reports(tmp_path):
    home = tmp_path / "home"
    make_raw(home)
    report_dir = tmp_path / "outside-project"
    result = command(home, "transform", extra_env={"UNIKEGG_ARTIFACTS_DIR": str(report_dir)})
    assert result.returncode == 0, result.stderr
    processed = home / "data/processed"
    before = contents(processed)
    report, _ = validate(processed)
    assert len(report["files"]) == 20
    assert all(item["rows"] for item in report["files"].values())
    assert (report_dir / "report_gene_proteina.tsv").is_file()
    assert b'"3.5.1.n3"' in before["numero_ec.tsv"]
    assert b'"3.5.1.n3"' in before["proteina_ec.tsv"]
    assert b'"3.5.1.n3"' in before["reazione_ec.tsv"]
    repeat = command(home, "transform", extra_env={"UNIKEGG_ARTIFACTS_DIR": str(report_dir)})
    assert repeat.returncode == 0, repeat.stderr
    assert before == contents(processed)
    assert not list(processed.parent.glob(".unikegg-*"))


@pytest.mark.parametrize(
    "damage",
    [
        "missing-reactions",
        "missing-compounds",
        "missing-one-reaction",
        "truncated-reaction",
        "short-gene",
        "extra-gene-column",
        "missing-gene",
        "missing-ko",
        "missing-pathway",
        "duplicate-reaction",
        "invalid-output",
    ],
)
def test_bad_raw_preserves_previous_bundle(tmp_path, damage):
    proteins = make_raw(tmp_path)
    processed = make_processed(tmp_path / "data/processed")
    (processed / ".gitkeep").touch()
    before = contents(processed)
    raw = tmp_path / "data/raw/kegg"
    if damage == "missing-reactions":
        shutil.rmtree(raw / "details/reaction")
    elif damage == "missing-compounds":
        shutil.rmtree(raw / "details/compound")
    elif damage == "missing-one-reaction":
        raw_tsv(
            raw / "relations/ko_reaction.tsv",
            [
                ["ko:K00001", "rn:R00001"],
                ["ko:K00001", "rn:R00002"],
            ],
        )
    elif damage == "truncated-reaction":
        path = raw / "details/reaction/R00001.txt"
        path.write_text(path.read_text().removesuffix("///\n"))
    elif damage in {"short-gene", "extra-gene-column"}:
        fields = ["hsa:demo1", "CDS", "1:1..12"]
        if damage == "extra-gene-column":
            fields += ["demo; Synthetic", "unexpected"]
        raw_tsv(raw / "genes/hsa_genes.tsv", [fields])
    elif damage == "missing-gene":
        raw_tsv(raw / "genes/hsa_genes.tsv", [["hsa:other", "CDS", "1:1..12", "other; Synthetic"]])
    elif damage == "missing-ko":
        raw_tsv(raw / "ko/ko_list.tsv", [["K00002", "other"]])
    elif damage == "missing-pathway":
        raw_tsv(raw / "pathway/hsa_pathways.tsv", [])
    elif damage == "duplicate-reaction":
        shutil.copyfile(raw / "details/reaction/R00001.txt", raw / "details/reaction/duplicate.txt")
    else:
        proteins[0][6] = "é" * 40000
        write_uniprot(tmp_path / "data/raw/uniprot/synthetic-test-only.tsv.gz", proteins)
    result = command(tmp_path, "transform")
    assert result.returncode != 0
    assert before == contents(processed)
    assert not list(processed.parent.glob(".unikegg-*"))
    assert not (tmp_path / "artifacts/report_gene_proteina.tsv").exists()


def test_empty_details_are_allowed_when_no_ids_are_selected(tmp_path):
    make_raw(tmp_path)
    root = tmp_path / "data/raw/kegg"
    for name in ["ko_reaction", "pathway_reaction", "reaction_compound"]:
        raw_tsv(root / f"relations/{name}.tsv", [])
    shutil.rmtree(root / "details")
    result = command(tmp_path, "transform")
    assert result.returncode == 0, result.stderr
    report, _ = validate(tmp_path / "data/processed")
    assert report["files"]["reazione_kegg.tsv"]["rows"] == 0
    assert report["files"]["composto_kegg.tsv"]["rows"] == 0


def test_flat_parser_rejects_nested_or_unterminated_records(tmp_path):
    with pytest.raises(ValueError, match="Unterminated"):
        list(
            flat_records(
                ["ENTRY       R00001 Reaction\n", "ENTRY       R00002 Reaction\n", "///\n"], "probe"
            )
        )
    with pytest.raises(ValueError, match="Unterminated"):
        list(flat_records(["ENTRY       R00001 Reaction\n"], "probe"))
    with pytest.raises(FileNotFoundError, match="Missing KEGG"):
        list(detail_records(tmp_path / "absent"))


def test_raw_checksum_verified_when_available(tmp_path):
    from unikegg.dataset import sha256

    make_raw(tmp_path)
    root = tmp_path / "data/raw/kegg"
    relative = "genes/hsa_genes.tsv"
    metadata = {
        "file": relative,
        "sha256": sha256(root / relative),
        "url": "https://rest.kegg.jp/list/hsa",
    }
    (root / "manifest.jsonl").write_text(json.dumps(metadata) + "\n")
    assert preflight(root)["reaction"] == {"R00001"}
    (root / relative).write_text((root / relative).read_text().replace("Synthetic", "Modified"))
    with pytest.raises(ValueError, match="checksum mismatch"):
        preflight(root)


def test_failure_after_entity_generation_preserves_bundle(tmp_path, monkeypatch):
    make_raw(tmp_path)
    output = make_processed(tmp_path / "data/processed")
    before = contents(output)
    monkeypatch.setattr(entities, "RAW_KEGG", tmp_path / "data/raw/kegg")
    monkeypatch.setattr(relations, "RAW_KEGG", tmp_path / "data/raw/kegg")
    monkeypatch.setattr(relations, "CONTROLLI", tmp_path / "reports")

    def fail_relations():
        assert (entities.OUTPUT / "protein_uniprot.tsv").exists()
        raise RuntimeError("Synthetic failure after entities")

    monkeypatch.setattr(relations, "main", fail_relations)
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        pipeline.run(output, tmp_path / "data/raw/uniprot")
    assert before == contents(output)
    assert not list(output.parent.glob(".unikegg-*"))


@pytest.mark.parametrize("restore_fails", [False, True])
def test_publication_rollback_or_recovery_backup(tmp_path, monkeypatch, restore_fails):
    output, stage = tmp_path / "processed", tmp_path / "stage"
    output.mkdir()
    stage.mkdir()
    (output / "old.txt").write_text("old dataset")
    (stage / "new.txt").write_text("new dataset")
    replace = os.replace

    def fail_publish(source, destination):
        source, destination = Path(source), Path(destination)
        if source == stage or (
            restore_fails and source.parent.name.startswith(".unikegg-previous-")
        ):
            raise OSError("Simulated rename failure")
        return replace(source, destination)

    monkeypatch.setattr(pipeline.os, "replace", fail_publish)
    if restore_fails:
        with pytest.raises(RuntimeError, match="Previous dataset retained"):
            pipeline.publish(stage, output)
        backups = list(tmp_path.glob(".unikegg-previous-*/processed/old.txt"))
        assert len(backups) == 1 and backups[0].read_text() == "old dataset"
    else:
        with pytest.raises(OSError, match="rename failure"):
            pipeline.publish(stage, output)
        assert (output / "old.txt").read_text() == "old dataset"
        assert not list(tmp_path.glob(".unikegg-previous-*"))


def test_destination_and_lock_guards(tmp_path):
    output = tmp_path / "processed"
    output.mkdir()
    (output / "notes.txt").write_text("user-owned file")
    with pytest.raises(ValueError, match="unrelated files"):
        pipeline.check_destination(output)
    with pipeline.output_lock(output):
        with pytest.raises(RuntimeError, match="lock exists"):
            with pipeline.output_lock(output):
                pytest.fail("concurrent writer admitted")
    assert (output / "notes.txt").read_text() == "user-owned file"


def test_isoforms_prefer_parent_and_are_order_independent(tmp_path, monkeypatch):
    inputs = [
        {
            "Entry": "P00001",
            "Alternative products (isoforms)": "Name=External; IsoId=P00002-2; Sequence=External;",
        },
        {
            "Entry": "P00002",
            "Alternative products (isoforms)": "Name=Canonical; IsoId=P00002-1; Sequence=Displayed; "
            "Name=Own description; IsoId=P00002-2; Sequence=VSP_000001;",
        },
    ]
    monkeypatch.setattr(entities, "OUTPUT", tmp_path)
    monkeypatch.setattr(entities, "PROTEINE_ACC", {"P00001", "P00002"})
    monkeypatch.setattr(entities, "EC_KEGG", set())
    previous = None
    for source in [inputs, list(reversed(inputs))]:
        monkeypatch.setattr(entities, "leggi_uniprot_tsv", lambda: iter(source))
        entities.costruisci_go_ec_isoforme()
        data = list(rows(tmp_path, BY_NAME["PROTEIN_ISOFORM"]))
        assert len({(row["accession"], row["ordinal"]) for row in data}) == 2
        assert [(row["isoform_id"], row["ordinal"]) for row in data] == [
            ("P00002-1", "1"),
            ("P00002-2", "2"),
        ]
        assert data[1]["sequence_status"] == "DESCRIBED"
        assert data[1]["name"] == "Own description"
        if previous is not None:
            assert data == previous
        previous = data


def test_multiple_isoids_in_one_block_have_distinct_ordinals(tmp_path, monkeypatch):
    monkeypatch.setattr(entities, "OUTPUT", tmp_path)
    monkeypatch.setattr(entities, "PROTEINE_ACC", {"P00001"})
    monkeypatch.setattr(entities, "EC_KEGG", set())
    monkeypatch.setattr(
        entities,
        "leggi_uniprot_tsv",
        lambda: iter(
            [
                {
                    "Entry": "P00001",
                    "Alternative products (isoforms)": "Name=Example; IsoId=P00001-1, P00001-2; Sequence=Displayed;",
                }
            ]
        ),
    )
    entities.costruisci_go_ec_isoforme()
    assert {row["ordinal"] for row in rows(tmp_path, BY_NAME["PROTEIN_ISOFORM"])} == {"1", "2"}


@pytest.mark.parametrize("identifier", ["1.1.1.1", "3.5.1.n3", "1.-.-.-", "1.1.1.-"])
def test_ec_supported_identifiers(identifier):
    assert EC_RE.findall(f"{identifier}; {identifier} ") == [identifier, identifier]


@pytest.mark.parametrize("text", ["x3.5.1.n3", "3.5.1.n3x", "3.5.1.3.4", "3.5.1.---", "3.5.1.n"])
def test_ec_does_not_extract_valid_looking_substrings(text):
    assert EC_RE.findall(text) == []


def test_report_path_and_quoted_literal_null(tmp_path, monkeypatch):
    monkeypatch.setattr(relations, "CONTROLLI", tmp_path / "outside-project")
    relations.scrivi_report_gene_proteina({code: Counter() for code in relations.ORGANISMI})
    assert (relations.CONTROLLI / "report_gene_proteina.tsv").is_file()
    monkeypatch.setattr(entities, "OUTPUT", tmp_path)
    entities.scrivi_tsv("probe.tsv", ["value"], [["NULL"]])
    assert (tmp_path / "probe.tsv").read_text().splitlines()[1] == '"NULL"'
    with (tmp_path / "probe.tsv").open() as stream:
        assert list(tsv.reader(stream)) == [["value"], ["NULL"]]


def test_entities_reentrant(tmp_path, monkeypatch):
    make_raw(tmp_path)
    monkeypatch.setattr(entities, "OUTPUT", tmp_path / "entities")
    monkeypatch.setattr(entities, "RAW_KEGG", tmp_path / "data/raw/kegg")
    monkeypatch.setenv("UNIKEGG_REVIEWED_DIR", str(tmp_path / "data/raw/uniprot"))
    entities.main()
    before = contents(entities.OUTPUT)
    entities.main()
    assert before == contents(entities.OUTPUT)


def test_large_sequence_fresh_cli_process(tmp_path):
    output = make_processed(tmp_path / "data/processed")
    table = BY_NAME["PROTEIN_UNIPROT"]
    data = list(rows(output, table))
    data[0]["amino_acid_sequence"], data[0]["sequence_length"] = "A" * 200000, "200000"
    with (output / table["file"]).open("w", encoding="utf-8", newline="") as stream:
        writer = tsv.writer(stream)
        writer.writerow(table["columns"])
        writer.writerows([row[c] for c in table["columns"]] for row in data)
    manifest(output, "synthetic")
    result = command(tmp_path, "validate", extra_env={"UNIKEGG_DATASET_KIND": "synthetic"})
    assert result.returncode == 0, result.stderr


def test_pipeline_in_process_success_restores_configuration(tmp_path, monkeypatch):
    make_raw(tmp_path)
    output = tmp_path / "data/processed"
    monkeypatch.setattr(entities, "RAW_KEGG", tmp_path / "data/raw/kegg")
    monkeypatch.setattr(relations, "RAW_KEGG", tmp_path / "data/raw/kegg")
    monkeypatch.setattr(relations, "CONTROLLI", tmp_path / "external-reports")
    old = (entities.OUTPUT, relations.OUTPUT, relations.CONTROLLI)
    reviewed = os.environ.get("UNIKEGG_REVIEWED_DIR")
    pipeline.run(output, tmp_path / "data/raw/uniprot")
    before = contents(output)
    pipeline.run(output, tmp_path / "data/raw/uniprot")
    assert contents(output) == before
    assert (entities.OUTPUT, relations.OUTPUT, relations.CONTROLLI) == old
    assert os.environ.get("UNIKEGG_REVIEWED_DIR") == reviewed
    validate(output)
