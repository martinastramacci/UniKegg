"""English contracts and explicit migration preserve values and reject ambiguity."""

import json
from pathlib import Path

import pytest

from tests.make_fixture import generate
from tools.migrate_database_names import rename_plan
from tools.migrate_dataset_names import run
from tools.migrate_legacy_dump import source_dump_file
from unikegg.dataset import TABLES, validate
from unikegg.legacy_names import LEGACY_TABLE_NAMES

ROOT = Path(__file__).resolve().parents[1]


def legacy_bundle(directory):
    generate(directory)
    reverse = {new: old for old, new in LEGACY_TABLE_NAMES.items()}
    path = directory / "manifest.json"
    metadata = json.loads(path.read_text())
    files = {}
    for table in TABLES:
        old = reverse.get(table["name"], table["name"]).lower() + ".tsv"
        (directory / table["file"]).rename(directory / old)
        files[old] = metadata["files"][table["file"]]
    metadata["files"] = files
    path.write_text(json.dumps(metadata))
    return {p.name: p.read_bytes() for p in directory.iterdir()}


def test_dataset_conversion_preserves_source_and_all_tsv_bytes(tmp_path):
    source, output = tmp_path / "legacy", tmp_path / "english"
    before = legacy_bundle(source)
    run(source, output)
    validate(output, "synthetic")
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    reverse = {new: old for old, new in LEGACY_TABLE_NAMES.items()}
    for table in TABLES:
        old = reverse.get(table["name"], table["name"]).lower() + ".tsv"
        assert (output / table["file"]).read_bytes() == before[old]


def test_dataset_conversion_rejects_damage_without_publishing(tmp_path):
    source, output = tmp_path / "legacy", tmp_path / "english"
    legacy_bundle(source)
    (source / "organismo.tsv").write_text("damaged\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        run(source, output)
    assert not output.exists()


def test_dataset_conversion_refuses_existing_or_source_destination(tmp_path):
    source = tmp_path / "legacy"
    legacy_bundle(source)
    for output in [source, source / "nested", tmp_path]:
        with pytest.raises(ValueError):
            run(source, output)


@pytest.mark.parametrize("bridges", [True, False])
def test_database_rename_handles_20_and_22_tables(bridges):
    reverse = {new: old for old, new in LEGACY_TABLE_NAMES.items()}
    expected = {t["name"] for t in TABLES}
    if not bridges:
        expected -= {"ORTHOLOGY_PATHWAY", "ORTHOLOGY_EC"}
    actual = {reverse.get(name, name) for name in expected}
    plan = rename_plan(actual)
    assert {old for old, _ in plan} <= actual
    assert {reverse.get(name, name): name for name in expected if name in reverse} == dict(plan)
    assert rename_plan(expected) == []


def test_database_rename_rejects_collision_and_incomplete_schema():
    actual = {t["name"] for t in TABLES}
    with pytest.raises(ValueError, match="Both legacy and English"):
        rename_plan(actual | {"ORGANISMO"})
    with pytest.raises(ValueError, match="Required domain table missing"):
        rename_plan(actual - {"ORGANISM"})
    with pytest.raises(ValueError, match="Only one KO bridge"):
        rename_plan(actual - {"ORTHOLOGY_EC"})


def test_static_migration_matches_legacy_mapping():
    sql = (ROOT / "db/migrations/005_english_names.sql").read_text()
    for old, new in LEGACY_TABLE_NAMES.items():
        assert f"{old} TO {new}" in sql
    assert sql.count("RENAME TABLE") == 1
    assert "DROP" not in sql and "FOREIGN_KEY_CHECKS" not in sql


def test_dump_import_accepts_legacy_names_and_rejects_ambiguous_input(tmp_path):
    legacy = tmp_path / "unikegg_organismo.sql"
    legacy.touch()
    assert source_dump_file(tmp_path, "ORGANISM") == legacy
    english = tmp_path / "unikegg_organism.sql"
    english.touch()
    with pytest.raises(ValueError, match="exactly one"):
        source_dump_file(tmp_path, "ORGANISM")
    legacy.unlink()
    assert source_dump_file(tmp_path, "ORGANISM") == english


def test_italian_guide_copies_use_english_filenames():
    for name in ["command-guide", "acquisition", "updates", "orthology-migration"]:
        assert (ROOT / "docs" / f"{name}.md").is_file()
        assert (ROOT / "docs" / f"{name}.it.md").is_file()
    assert not list(ROOT.rglob("*guida*"))
