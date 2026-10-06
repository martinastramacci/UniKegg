"""Update regressions for the explicitly disposable MySQL integration database."""

import json
from unittest.mock import patch

from unikegg import loader, tsv, updater, versions
from unikegg.dataset import TABLES, manifest, rows, validate


def run(directory, original):
    from concurrent.futures import ThreadPoolExecutor

    from tests.mysql_integration import expect_error, query, typed

    def database():
        return {
            table["name"]: set(
                query(
                    "SELECT "
                    + ",".join(f"`{c}`" for c in table["columns"])
                    + f" FROM `{table['name']}`"
                )
            )
            for table in TABLES
        }

    def write(data):
        for table in TABLES:
            with (directory / table["file"]).open("w", encoding="utf-8", newline="") as stream:
                writer = tsv.writer(stream)
                writer.writerow(table["columns"])
                writer.writerows([row[c] for c in table["columns"]] for row in data[table["name"]])
        manifest(directory, "synthetic")
        return validate(directory, "synthetic")[1]

    def expected(data):
        return {
            table["name"]: {
                tuple(typed(table, c, row[c]) for c in table["columns"])
                for row in data[table["name"]]
            }
            for table in TABLES
        }

    def sql(statement):
        connection = loader.connect()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(statement)
                connection.commit()
            finally:
                cursor.close()
        finally:
            connection.close()

    assert versions.run()["current_version"] == 1
    assert len(versions.run()["versions"]) == 1
    before = database()
    old_state = query("SELECT * FROM ETL_LOAD_STATE")
    data = {table["name"]: list(rows(directory, table)) for table in TABLES}
    proteins = data["PROTEIN_UNIPROT"]
    proteins[0]["entry_name"], proteins[1]["entry_name"] = (
        proteins[1]["entry_name"],
        proteins[0]["entry_name"],
    )
    proteins[0]["protein_name"] = "UPDATED protein 🧬"
    # A change invisible to MySQL's accent/case-insensitive text equality.
    data["GENE_KEGG"][0]["definition"] = "SYNTHETIC GENE"
    # Change a KO parent (dependent bridges must be removed/reinserted),
    # replace a direct EC assertion and add a pathway assertion.
    data["ORTOLOGIA_KEGG"][0]["definition"] = "Updated KO definition"
    data["PATHWAY_RIFERIMENTO"].append({"map_id": "map00020", "name": "New map"})
    data["ORTOLOGIA_PATHWAY"].append({"ko_id": "K00001", "map_id": "map00020"})
    data["NUMERO_EC"].append({"ec_number": "2.7.1.999"})
    data["ORTOLOGIA_EC"] = [{"ko_id": "K00001", "ec_number": "2.7.1.999"}]
    removed_protein = proteins[-1]["accession"]
    removed_gene = data["GENE_KEGG"][-1]["kegg_gene_id"]
    for table in TABLES:
        data[table["name"]] = [
            r
            for r in data[table["name"]]
            if r.get("accession") != removed_protein and r.get("kegg_gene_id") != removed_gene
        ]
    protein = dict(data["PROTEIN_UNIPROT"][0])
    protein.update(
        accession="NEW000001", entry_name="NEW_ENTRY", protein_name="New reviewed fixture"
    )
    data["PROTEIN_UNIPROT"].append(protein)
    gene = dict(data["GENE_KEGG"][0])
    gene["kegg_gene_id"] = gene["kegg_gene_id"].split(":")[0] + ":new"
    data["GENE_KEGG"].append(gene)
    data["GENE_PROTEINA"].append(
        {
            "kegg_gene_id": gene["kegg_gene_id"],
            "accession": "NEW000001",
            "mapping_source": "KEGG_CONV",
        }
    )
    new_hash = write(data)
    source_bytes = {p.name: p.read_bytes() for p in directory.iterdir()}
    plan = updater.run(dry_run=True)
    assert plan["action"] == "planned"
    assert plan["changes"]["PROTEIN_UNIPROT"] == {"added": 1, "removed": 1, "modified": 2}
    assert plan["changes"]["GENE_KEGG"] == {"added": 1, "removed": 1, "modified": 1}
    assert plan["changes"]["ORTOLOGIA_PATHWAY"] == {"added": 1, "removed": 0, "modified": 0}
    assert plan["changes"]["ORTOLOGIA_EC"] == {"added": 1, "removed": 1, "modified": 0}
    assert database() == before
    assert query("SELECT * FROM ETL_LOAD_STATE") == old_state
    assert len(versions.run()["versions"]) == 1

    # This fault happens after synchronization has actually deleted/inserted rows.
    with patch.object(updater, "verify_exact", side_effect=RuntimeError("Injected late failure")):
        expect_error(updater.run, RuntimeError)
    assert database() == before
    assert query("SELECT * FROM ETL_LOAD_STATE") == old_state
    assert len(versions.run()["versions"]) == 1

    record = versions.record

    def fail_metadata(*args, **kwargs):
        record(*args, **kwargs)
        raise RuntimeError("Failure after history and current-version writes")

    with patch.object(versions, "record", fail_metadata):
        expect_error(updater.run, RuntimeError)
    assert database() == before
    assert query("SELECT * FROM ETL_LOAD_STATE") == old_state
    assert len(versions.run()["versions"]) == 1

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(updater.run, version_label="Snapshot test 2") for _ in range(2)]
        results = [f.result(timeout=120) for f in futures]
    assert sorted(r["action"] for r in results) == ["unchanged", "updated"]
    assert all(r["current_version"] == 2 for r in results)
    assert database() == expected(data)
    assert source_bytes == {p.name: p.read_bytes() for p in directory.iterdir()}
    history = versions.run()
    assert history["current_version"] == 2
    assert [r["version"] for r in history["versions"]] == [2, 1]
    assert history["versions"][0]["label"] == "Snapshot test 2"
    assert history["versions"][0]["applied_at"].endswith("+00:00")
    assert history["versions"][0]["dataset_sha256"] == new_hash
    assert updater.run()["action"] == "unchanged"
    assert len(versions.run()["versions"]) == 2
    assert loader.run(verify_only=True)["action"] == "verified"

    # Same fingerprint cannot disguise manual modification with unchanged counts.
    sql(
        "UPDATE GENE_KEGG SET definition='manual drift' WHERE kegg_gene_id='"
        + gene["kegg_gene_id"]
        + "'"
    )
    drift = expect_error(updater.run, ValueError)
    assert "differ from staged" in str(drift)
    sql(
        "UPDATE GENE_KEGG SET definition='SYNTHETIC GENE' WHERE kegg_gene_id='"
        + gene["kegg_gene_id"]
        + "'"
    )
    assert database() == expected(data)

    for filename, content in original.items():
        (directory / filename).write_bytes(content)
    error = expect_error(updater.run, ValueError)
    assert "historical version" in str(error)
    for filename, content in source_bytes.items():
        (directory / filename).write_bytes(content)

    # Simulate an installation created before version tracking. Only the explicitly
    # disposable regression schema is used; no biological data is reset here.
    baseline = query("SELECT dataset_sha256,dataset_kind,loaded_at FROM ETL_LOAD_STATE")[0]
    sql("DROP TABLE ETL_DATASET_HISTORY")
    sql("ALTER TABLE ETL_LOAD_STATE DROP COLUMN current_version")
    assert versions.run()["versions"][0]["action"] == "baseline"
    data["PROTEIN_UNIPROT"][0]["protein_name"] = "Next release"
    data["ORGANISMO"][0]["scientific_name"] += " updated annotation"
    write(data)
    updater.run(dry_run=True)
    assert (
        query(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='ETL_DATASET_HISTORY'"
        )[0][0]
        == 0
    )
    with patch.object(updater, "verify_exact", side_effect=RuntimeError("Legacy update fails")):
        expect_error(updater.run, RuntimeError)
    assert query("SELECT COUNT(*) FROM ETL_DATASET_HISTORY")[0][0] == 0
    assert query("SELECT current_version FROM ETL_LOAD_STATE")[0][0] is None
    assert versions.run()["current_version"] == 1
    assert updater.run(version_label="Migrated update")["current_version"] == 2
    entries = versions.run()["versions"]
    assert entries[1]["action"] == "baseline"
    assert entries[1]["dataset_sha256"] == baseline[0]
    assert entries[1]["applied_at"] == versions.utc(baseline[2])
    assert database() == expected(data)
    # A smaller selection removes organisms and all their dependent records.
    data["ORGANISMO"].pop()
    for table in TABLES:
        for fk in table["fk"]:
            parents = {r[fk["target"]] for r in data[fk["parent"]]}
            data[table["name"]] = [r for r in data[table["name"]] if r[fk["column"]] in parents]
    write(data)
    assert updater.run()["current_version"] == 3
    assert database() == expected(data)
    entries = versions.run()["versions"]
    print(
        json.dumps({"event": "mysql_update_regressions_passed", "versions": len(entries)}),
        flush=True,
    )
