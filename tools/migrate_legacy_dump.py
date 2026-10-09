"""Upgrade a trusted legacy dump using an isolated, temporary native MySQL server.

Never connects to an existing MySQL instance. Original SQL files are read-only.
KEGG raw files must already have been acquired with checksummed metadata.
"""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import mysql.connector

from unikegg import tsv
from unikegg.dataset import TABLES, sha256
from unikegg.identifiers import EC_RE
from unikegg.kegg_data import acquisition_manifest, orthology_links, strip_prefix, tabular_rows
from unikegg.legacy_names import LEGACY_TABLE_NAMES

PROJECT = Path(__file__).resolve().parents[1]
BRIDGES = {"ORTHOLOGY_PATHWAY", "ORTHOLOGY_EC"}
CATALOGS = {"ORTHOLOGY_KEGG", "PATHWAY_REFERENCE", "EC_NUMBER"}


def source_dump_file(source, name):
    reverse = {new: old for old, new in LEGACY_TABLE_NAMES.items()}
    candidates = {
        Path(source) / f"unikegg_{value.lower()}.sql"
        for value in (name, reverse.get(name, name))
    }
    found = [path for path in candidates if path.is_file()]
    if len(found) != 1:
        raise ValueError(f"Expected exactly one legacy or English dump file for {name}: {found}")
    return found[0]


def emit(message):
    print(message, flush=True)


def query(connection, sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def execute(connection, sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


@contextmanager
def isolated_mysql():
    with tempfile.TemporaryDirectory(prefix="unikegg-legacy-migration-") as temporary:
        root = Path(temporary)
        socket, log = root / "mysql.sock", root / "server.log"
        base = ["mysqld", "--no-defaults", f"--datadir={root / 'data'}", f"--log-error={log}"]
        emit("Initializing a private MySQL instance (no TCP listener)")
        subprocess.run(base + ["--initialize-insecure"], check=True, timeout=90)
        server = subprocess.Popen(
            base
            + [
                f"--socket={socket}",
                f"--pid-file={root / 'server.pid'}",
                "--skip-networking",
                "--mysqlx=OFF",
                "--max-allowed-packet=1G",
                "--innodb-buffer-pool-size=256M",
                "--local-infile=1",
            ]
        )
        connection = None
        try:
            for _ in range(150):
                if server.poll() is not None:
                    raise RuntimeError(log.read_text())
                try:
                    connection = mysql.connector.connect(
                        unix_socket=str(socket),
                        user="root",
                        password="",
                        charset="utf8mb4",
                    )
                    break
                except mysql.connector.Error:
                    time.sleep(0.2)
            if connection is None:
                raise RuntimeError(log.read_text())
            execute(
                connection,
                "CREATE DATABASE migrated CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci",
            )
            execute(connection, "USE migrated")
            yield connection, socket
        finally:
            if connection is not None:
                connection.close()
            if server.poll() is None:
                server.terminate()
                server.wait(timeout=60)


def import_sql(socket, database, path):
    with path.open("rb") as stream:
        result = subprocess.run(
            [
                "mysql",
                "--no-defaults",
                "--protocol=SOCKET",
                f"--socket={socket}",
                "-uroot",
                "--default-character-set=utf8mb4",
                "--max-allowed-packet=1G",
                database,
            ],
            stdin=stream,
            capture_output=True,
            timeout=300,
        )
    if result.returncode:
        raise RuntimeError(f"Import failed: {path.name}: {result.stderr.decode(errors='replace')}")


def fingerprint(connection, name, columns, primary_key, allowed=None, export=None):
    """Hash every SQL value, preserving NULL, types and column boundaries."""
    sql = "SELECT " + ",".join(f"`{c}`" for c in columns) + f" FROM `{name}` ORDER BY "
    sql += ",".join(f"`{c}`" for c in primary_key)
    digest, count = hashlib.sha256(), 0
    indexes = [columns.index(c) for c in primary_key]
    with connection.cursor() as cursor:
        cursor.execute(sql)
        for row in cursor:
            if allowed is not None and tuple(row[i] for i in indexes) not in allowed:
                continue
            digest.update(
                json.dumps(row, ensure_ascii=False, default=str, separators=(",", ":")).encode()
            )
            digest.update(b"\n")
            count += 1
            if export is not None:
                export.writerow(["" if value is None else value for value in row])
    return {"rows": count, "sha256_sql_values": digest.hexdigest()}


def audit(connection):
    findings = {}
    for table in TABLES:
        for fk in table["fk"]:
            child, parent = table["name"], fk["parent"]
            column, target = fk["column"], fk["target"]
            n = query(
                connection,
                f"SELECT COUNT(*) FROM `{child}` c LEFT JOIN `{parent}` p "
                f"ON c.`{column}`=p.`{target}` WHERE p.`{target}` IS NULL",
            )[0][0]
            findings[f"orphan:{child}.{column}"] = n
    for name, sql in {
        "invalid_protein_sequence": "SELECT COUNT(*) FROM PROTEIN_UNIPROT WHERE CHAR_LENGTH(amino_acid_sequence) <> sequence_length OR NOT REGEXP_LIKE(amino_acid_sequence, '^[A-Z]+$', 'c')",
        "gene_protein_species_mismatch": "SELECT COUNT(*) FROM GENE_PROTEIN gp JOIN GENE_KEGG g USING(kegg_gene_id) JOIN PROTEIN_UNIPROT p USING(accession) WHERE g.organism_id <> p.organism_id",
        "gene_pathway_species_mismatch": "SELECT COUNT(*) FROM GENE_PATHWAY gp JOIN GENE_KEGG g USING(kegg_gene_id) JOIN PATHWAY_ORGANISM p USING(pathway_id) WHERE g.organism_id <> p.organism_id",
        "isoform_parent_mismatch": "SELECT COUNT(*) FROM PROTEIN_ISOFORM WHERE isoform_id NOT LIKE CONCAT(accession, '-%')",
    }.items():
        findings[name] = query(connection, sql)[0][0]
    if any(findings.values()):
        raise ValueError(f"Integrity audit failed: {findings}")
    return findings


def direct_links(raw):
    """Quarantine only catalog orphans independently confirmed missing by KEGG GET."""
    kos = {strip_prefix(r[0]) for r in tabular_rows(raw / "ko/ko_list.tsv")}
    evidence_path = raw / "missing_ko_checks.json"
    evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else {}
    ec_links, excluded = set(), []
    for left, right in tabular_rows(raw / "relations/ko_ec.tsv"):
        ko, ec = left.removeprefix("ko:"), right.removeprefix("ec:")
        if not re.fullmatch(r"K[0-9]{5}", ko) or not EC_RE.fullmatch(ec):
            raise ValueError(f"Malformed KO/EC source: {left}, {right}")
        if ko not in kos:
            check = evidence.get(ko, {})
            if check.get("status") != 404 or check.get("url") != f"https://rest.kegg.jp/get/{ko}":
                raise ValueError(f"Unresolved KO requires independent KEGG verification: {ko}")
            excluded.append(
                {
                    "ko_id": ko,
                    "ec_number": ec,
                    "reason": "KO absent from current catalog and GET returned 404",
                    "verification": check,
                }
            )
        else:
            ec_links.add((ko, ec))
    return {
        "pathway": sorted(set(orthology_links(raw, "pathway"))),
        "ec": sorted(ec_links),
    }, excluded


def run(source, output, raw):
    output.mkdir(parents=True, exist_ok=True)
    dump = output / "unikegg_updated.sql"
    if dump.exists() or (output / "migration_report.json").exists():
        raise ValueError("Refusing to overwrite an already exported migration")
    metadata = acquisition_manifest(raw)
    required = [
        "ko/ko_list.tsv",
        "pathway/pathway_reference.tsv",
        "relations/ko_pathway.tsv",
        "relations/ko_ec.tsv",
    ]
    for name in required:
        if name not in metadata or metadata[name]["sha256"] != sha256(raw / name):
            raise ValueError(f"Missing or mismatched KEGG provenance: {name}")
    links, excluded = direct_links(raw)
    emit(f"Verified direct KEGG links: { {kind: len(value) for kind, value in links.items()} }")
    report = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_directory": str(source),
        "source_files": {},
        "kegg_sources": metadata,
        "policy": "Preserve original biological values; add current direct KO links and missing catalog entries. Not a full biological release refresh.",
        "reviewed_status": "Inherited from legacy dump; not independently reverified against UniProt. No Swiss-Prot ETL manifest fabricated.",
    }
    report["excluded_upstream_links"] = excluded
    old_tables = [t for t in TABLES if t["name"] not in BRIDGES]
    original_keys, original_columns, original_fingerprints = {}, {}, {}
    with isolated_mysql() as (connection, socket):
        report["mysql_version"] = query(connection, "SELECT VERSION()")[0][0]
        for table in old_tables:
            name = table["name"]
            path = source_dump_file(source, name)
            report["source_files"][path.name] = {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            emit(f"Restoring {path.name}")
            import_sql(socket, "migrated", path)
        actual = {r[0] for r in query(connection, "SHOW TABLES")}
        reverse = {new: old for old, new in LEGACY_TABLE_NAMES.items()}
        imported = {}
        for table in old_tables:
            name = table["name"]
            candidates = {name.lower(), reverse.get(name, name).lower()} & actual
            if len(candidates) != 1:
                raise ValueError(f"Ambiguous or missing imported table: {name}: {candidates}")
            imported[name] = candidates.pop()
        if actual != set(imported.values()):
            raise ValueError(f"Unexpected tables: {actual}")
        execute(
            connection,
            "RENAME TABLE "
            + ", ".join(f"`{imported[t['name']]}` TO `{t['name']}`" for t in old_tables),
        )
        for table in old_tables:
            name = table["name"]
            columns = [r[0] for r in query(connection, f"SHOW COLUMNS FROM `{name}`")]
            original_columns[name] = columns
            if name in CATALOGS:
                original_keys[name] = set(
                    query(connection, f"SELECT `{table['pk'][0]}` FROM `{name}`")
                )
            original_fingerprints[name] = fingerprint(connection, name, columns, table["pk"])
            emit(f"Original {name}: {original_fingerprints[name]['rows']} rows")
        report["original_tables"] = original_fingerprints
        if "evidence_code" not in original_columns["PROTEIN_GO"]:
            execute(
                connection,
                "ALTER TABLE PROTEIN_GO ADD COLUMN evidence_code VARCHAR(12) NULL, ADD COLUMN evidence_source VARCHAR(100) NULL",
            )
        migration = (PROJECT / "db/migrations/004_orthology_links.sql").read_text()
        for sql in re.sub(r"--[^\n]*", "", migration).split(";"):
            if sql.strip():
                execute(connection, sql)
        # Preserve all original annotations, adding parents only where absent.
        additions = {}
        ko_rows = []
        for identifier, description in tabular_rows(raw / "ko/ko_list.tsv"):
            ko = strip_prefix(identifier)
            if (ko,) not in original_keys["ORTHOLOGY_KEGG"]:
                ko_rows.append((ko, description.split(";", 1)[0].strip(), description))
        pathway_rows = [
            (strip_prefix(i), d)
            for i, d in tabular_rows(raw / "pathway/pathway_reference.tsv")
            if (strip_prefix(i),) not in original_keys["PATHWAY_REFERENCE"]
        ]
        ec_rows = [
            (ec,)
            for ec in sorted({ec for _, ec in links["ec"]})
            if (ec,) not in original_keys["EC_NUMBER"]
        ]
        for name, records in [
            ("ORTHOLOGY_KEGG", ko_rows),
            ("PATHWAY_REFERENCE", pathway_rows),
            ("EC_NUMBER", ec_rows),
            ("ORTHOLOGY_PATHWAY", links["pathway"]),
            ("ORTHOLOGY_EC", links["ec"]),
        ]:
            additions[name] = len(records)
            with connection.cursor() as cursor:
                for offset in range(0, len(records), 2000):
                    batch = records[offset : offset + 2000]
                    cursor.executemany(
                        f"INSERT INTO `{name}` VALUES ({','.join(['%s'] * len(batch[0]))})", batch
                    )
            emit(f"Added {name}: {len(records)} rows")
        connection.commit()
        report["additions"] = additions
        report["audit_before_export"] = audit(connection)
        for table in old_tables:
            name = table["name"]
            after = fingerprint(
                connection, name, original_columns[name], table["pk"], original_keys.get(name)
            )
            if after != original_fingerprints[name]:
                raise ValueError(f"Original biological values changed: {name}")
        report["all_original_values_preserved"] = True
        emit("All original rows and values preserved; FK and biological consistency audit passed")
        current_kos = {strip_prefix(row[0]) for row in tabular_rows(raw / "ko/ko_list.tsv")}
        current_maps = {
            strip_prefix(row[0]) for row in tabular_rows(raw / "pathway/pathway_reference.tsv")
        }
        report["legacy_catalog_ids_absent_from_current_kegg"] = {
            "ko": sorted(k[0] for k in original_keys["ORTHOLOGY_KEGG"] if k[0] not in current_kos),
            "pathway": sorted(
                k[0] for k in original_keys["PATHWAY_REFERENCE"] if k[0] not in current_maps
            ),
        }
        processed = output / "tsv"
        processed.mkdir(exist_ok=True)
        final = {}
        for table in TABLES:
            with (processed / table["file"]).open("w", encoding="utf-8", newline="") as stream:
                writer = tsv.writer(stream)
                writer.writerow(table["columns"])
                final[table["name"]] = fingerprint(
                    connection, table["name"], table["columns"], table["pk"], export=writer
                )
            final[table["name"]]["tsv_sha256"] = sha256(processed / table["file"])
        report["final_tables"] = final
        candidate = output / "unikegg_updated.sql.part"
        with candidate.open("wb") as stream:
            subprocess.run(
                [
                    "mysqldump",
                    "--no-defaults",
                    "--protocol=SOCKET",
                    f"--socket={socket}",
                    "-uroot",
                    "--default-character-set=utf8mb4",
                    "--single-transaction",
                    "--skip-lock-tables",
                    "--no-tablespaces",
                    "--set-gtid-purged=OFF",
                    "--column-statistics=0",
                    "--order-by-primary",
                    "--hex-blob",
                    "--skip-add-drop-table",
                    "migrated",
                    *[t["name"] for t in TABLES],
                ],
                stdout=stream,
                check=True,
                timeout=300,
            )
        emit("Exported complete SQL; restoring it in a second empty database")
        execute(
            connection, "CREATE DATABASE restored CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
        import_sql(socket, "restored", candidate)
        execute(connection, "USE restored")
        report["audit_after_restore"] = audit(connection)
        for table in TABLES:
            actual = fingerprint(connection, table["name"], table["columns"], table["pk"])
            expected = {k: v for k, v in final[table["name"]].items() if k != "tsv_sha256"}
            if actual != expected:
                raise ValueError(f"Dump round-trip mismatch: {table['name']}")
        report["dump_roundtrip_all_values_verified"] = True
        for name, item in report["source_files"].items():
            if sha256(source / name) != item["sha256"]:
                raise ValueError(f"Source dump changed during migration: {name}")
        candidate.replace(dump)
        report["dump_sha256"] = sha256(dump)
        report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        (output / "migration_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        )
        emit(json.dumps({"event": "migration_verified", "dump": str(dump), "additions": additions}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    args = parser.parse_args()
    run(args.source.resolve(), args.output.resolve(), args.raw.resolve())
