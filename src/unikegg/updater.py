"""Synchronize a validated dataset atomically, keeping tables and unchanged rows."""

import json
import os
import re
from contextlib import suppress

import mysql.connector

from unikegg import loader, versions
from unikegg.dataset import TABLES, quote_for_mysql, verified_snapshot

STAGE = "UK_STAGE_"
REMOVE = "UK_REMOVE_"


def join_key(table, left="d", right="s"):
    return " AND ".join(f"{left}.`{c}`={right}.`{c}`" for c in table["pk"])


def different(table, left="d", right="s"):
    # SQL's case/accent-insensitive collation is correct for identity, but not
    # for detecting changes in stored annotation bytes. NULL equals only NULL.
    return (
        "NOT ("
        + " AND ".join(
            f"(CAST({left}.`{c}` AS BINARY) <=> CAST({right}.`{c}` AS BINARY))"
            for c in table["columns"]
        )
        + ")"
    )


def require_transactional(cursor):
    cursor.execute(
        "SELECT table_name,engine FROM information_schema.tables WHERE table_schema=DATABASE()"
    )
    engines = {name.upper(): engine for name, engine in cursor.fetchall()}
    for name in [*(t["name"] for t in TABLES), "ETL_LOAD_STATE"]:
        if engines.get(name) != "InnoDB":
            raise ValueError(f"Transactional update requires an InnoDB table: {name}")
    if "ETL_DATASET_HISTORY" in engines and engines["ETL_DATASET_HISTORY"] != "InnoDB":
        raise ValueError("Transactional update requires InnoDB history")


def stage(cursor, directory, manifest):
    for table in TABLES:
        name = table["name"]
        # LIKE preserves column types/unique constraints, but not foreign keys.
        # TEMPORARY DDL does not commit the ongoing transaction.
        cursor.execute(f"CREATE TEMPORARY TABLE `{STAGE}{name}` LIKE `{name}`")
    quote_for_mysql(directory)
    sql = (loader.PROJECT / "db/load/001_ingest.sql").read_text(encoding="utf-8")
    for statement in loader.load_statements(sql, directory):
        statement = re.sub(r"INTO TABLE (\w+)", lambda m: f"INTO TABLE `{STAGE}{m[1]}`", statement)
        cursor.execute(statement)
    for table in TABLES:
        cursor.execute(f"SELECT COUNT(*) FROM `{STAGE}{table['name']}`")
        if cursor.fetchone()[0] != manifest["files"][table["file"]]["rows"]:
            raise ValueError(f"Staging count mismatch: {table['name']}")


def differences(cursor):
    result = {}
    for table in TABLES:
        name, pk = table["name"], table["pk"][0]
        queries = {
            "added": f"SELECT COUNT(*) FROM `{STAGE}{name}` s LEFT JOIN `{name}` d "
            f"ON {join_key(table)} WHERE d.`{pk}` IS NULL",
            "removed": f"SELECT COUNT(*) FROM `{name}` d LEFT JOIN `{STAGE}{name}` s "
            f"ON {join_key(table)} WHERE s.`{pk}` IS NULL",
            "modified": f"SELECT COUNT(*) FROM `{name}` d JOIN `{STAGE}{name}` s "
            f"ON {join_key(table)} WHERE {different(table)}",
        }
        result[name] = {}
        for action, sql in queries.items():
            cursor.execute(sql)
            result[name][action] = cursor.fetchone()[0]
    return result


def synchronize(cursor):
    """Replace changed rows and their dependent closure, in FK order.

    Removing changed unique-key holders together supports swaps (e.g. two
    protein entry names) without transient uniqueness conflicts. Descendants
    are reinserted from staging. Unchanged rows outside that closure stay put.
    Foreign-key checks remain enabled throughout; no table is truncated.
    """
    by_name = {t["name"]: t for t in TABLES}
    for table in TABLES:
        name = table["name"]
        definitions = []
        for column in table["pk"]:
            match = re.match(
                r"(?:INT UNSIGNED|VARCHAR\(\d+\)|CHAR\(\d+\)|ENUM\('[A-Z_]+'(?:,'[A-Z_]+')*\))",
                table["specs"][column],
            )
            if match is None:
                raise ValueError(f"Unsupported primary-key type: {name}.{column}")
            definitions.append(f"`{column}` {match[0]} NOT NULL")
        keys = ",".join(f"`{c}`" for c in table["pk"])
        cursor.execute(
            f"CREATE TEMPORARY TABLE `{REMOVE}{name}` "
            f"({','.join(definitions)}, PRIMARY KEY ({keys})) ENGINE=InnoDB"
        )
        selected = ",".join(f"d.`{c}`" for c in table["pk"])
        cursor.execute(
            f"INSERT INTO `{REMOVE}{name}` ({keys}) SELECT {selected} FROM `{name}` d "
            f"LEFT JOIN `{STAGE}{name}` s ON {join_key(table)} "
            f"WHERE s.`{table['pk'][0]}` IS NULL OR {different(table)}"
        )

    # TABLES is topologically ordered. Every affected parent is complete before
    # visiting its children, including children with several parent tables.
    for table in TABLES:
        name = table["name"]
        keys = ",".join(f"`{c}`" for c in table["pk"])
        selected = ",".join(f"c.`{c}`" for c in table["pk"])
        key = table["pk"][0]
        for fk in table["fk"]:
            parent = by_name[fk["parent"]]
            cursor.execute(
                f"INSERT INTO `{REMOVE}{name}` ({keys}) SELECT {selected} FROM `{name}` c "
                f"JOIN `{parent['name']}` p ON c.`{fk['column']}`=p.`{fk['target']}` "
                f"JOIN `{REMOVE}{parent['name']}` r ON {join_key(parent, 'p', 'r')} "
                f"ON DUPLICATE KEY UPDATE `{key}`=`{REMOVE}{name}`.`{key}`"
            )
    for table in reversed(TABLES):
        name = table["name"]
        cursor.execute(
            f"DELETE d FROM `{name}` d JOIN `{REMOVE}{name}` r ON {join_key(table, 'd', 'r')}"
        )
    for table in TABLES:
        name = table["name"]
        columns = ",".join(f"`{c}`" for c in table["columns"])
        selected = ",".join(f"s.`{c}`" for c in table["columns"])
        cursor.execute(
            f"INSERT INTO `{name}` ({columns}) SELECT {selected} FROM `{STAGE}{name}` s "
            f"LEFT JOIN `{name}` d ON {join_key(table)} WHERE d.`{table['pk'][0]}` IS NULL"
        )


def verify_exact(cursor):
    for table in TABLES:
        name = table["name"]
        cursor.execute(
            f"SELECT COUNT(*) FROM `{STAGE}{name}` s LEFT JOIN `{name}` d "
            f"ON {join_key(table)} WHERE d.`{table['pk'][0]}` IS NULL OR {different(table)}"
        )
        if cursor.fetchone()[0]:
            raise ValueError(f"Database records differ from staged dataset: {name}")


def run(dry_run=False, version_label=None):
    versions.label_value(version_label)
    kind = os.environ.get("UNIKEGG_DATASET_KIND", "swissprot")
    with verified_snapshot(loader.PROCESSED, kind) as (directory, manifest, fingerprint):
        return _run(directory, manifest, fingerprint, kind, dry_run, version_label)


def _run(directory, manifest, fingerprint, kind, dry_run, version_label):
    connection = loader.connect(directory)
    cursor, locked = None, False
    try:
        cursor = connection.cursor()
        cursor.execute("SET time_zone = '+00:00'")
        cursor.execute("SELECT GET_LOCK('unikegg_ingestion', 60)")
        locked = cursor.fetchone()[0] == 1
        if not locked:
            raise RuntimeError("Another ingestion owns the load lock")
        cursor.execute(
            "SELECT dataset_sha256,dataset_kind,loaded_at FROM ETL_LOAD_STATE WHERE singleton_id=1"
        )
        state = cursor.fetchone()
        if not state:
            raise ValueError("Dataset has not been committed; use load for the first version")
        if state[1] != kind:
            raise ValueError("Cannot update between synthetic and Swiss-Prot datasets")
        history = versions.read(cursor)
        current = next((r for r in history if r["current"]), None)
        if not current or current["dataset_sha256"] != state[0]:
            raise ValueError("Current version and dataset history disagree")
        if fingerprint == state[0]:
            require_transactional(cursor)
            stage(cursor, directory, manifest)
            loader.verify(connection, manifest)
            verify_exact(cursor)
            result = {
                "action": "unchanged",
                "current_version": current["version"],
                "dataset_sha256": fingerprint,
            }
            print(json.dumps(result), flush=True)
            return result
        if any(row["dataset_sha256"] == fingerprint for row in history):
            raise ValueError("This dataset is a historical version, not a new update")
        require_transactional(cursor)
        if not dry_run:
            versions.ensure_schema(cursor, loader.PROJECT)
        stage(cursor, directory, manifest)
        changes = differences(cursor)
        print(
            json.dumps(
                {
                    "event": "update_plan",
                    "from_version": current["version"],
                    "dataset_sha256": fingerprint,
                    "changes": changes,
                }
            ),
            flush=True,
        )
        if dry_run:
            connection.rollback()
            return {
                "action": "planned",
                "current_version": current["version"],
                "changes": changes,
                "dataset_sha256": fingerprint,
            }
        previous = versions.bootstrap(cursor, state)
        synchronize(cursor)
        loader.verify(connection, manifest)
        verify_exact(cursor)
        version = versions.record(
            cursor, fingerprint, kind, manifest, changes, "update", version_label, previous
        )
        connection.commit()
        result = {
            "action": "updated",
            "previous_version": previous,
            "current_version": version,
            "dataset_sha256": fingerprint,
            "changes": changes,
        }
        print(json.dumps({"event": "ready", **result}), flush=True)
        return result
    except Exception:
        with suppress(mysql.connector.Error):
            connection.rollback()
        raise
    finally:
        if locked:
            with suppress(mysql.connector.Error):
                cursor.execute("SELECT RELEASE_LOCK('unikegg_ingestion')")
                cursor.fetchone()
        if cursor is not None:
            with suppress(mysql.connector.Error):
                cursor.close()
        connection.close()
