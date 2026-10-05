"""Persistent dataset versions; metadata and biological changes commit together."""

import json
from datetime import timezone


def has_table(cursor):
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema=DATABASE() AND table_name='ETL_DATASET_HISTORY'"
    )
    return bool(cursor.fetchone()[0])


def ensure_schema(cursor, project):
    """Add metadata to old installations before any transactional data writes.

    Called only while holding the shared ingestion lock. MySQL DDL commits
    implicitly; keeping it ahead of biological changes preserves rollback.
    """
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() "
        "AND table_name='ETL_LOAD_STATE' AND column_name='current_version'"
    )
    if not cursor.fetchone()[0]:
        cursor.execute("ALTER TABLE ETL_LOAD_STATE ADD COLUMN current_version INT UNSIGNED NULL")
    if not has_table(cursor):
        sql = (project / "db/init/003_dataset_history.sql").read_text(encoding="utf-8")
        cursor.execute(sql.strip().removesuffix(";"))


def label_value(value):
    if value is not None and (not value.strip() or len(value) > 128):
        raise ValueError("Version label must contain 1..128 characters")
    return value


def bootstrap(cursor, state):
    """Record the previously committed legacy snapshot as version 1."""
    cursor.execute("SELECT current_version FROM ETL_LOAD_STATE WHERE singleton_id=1")
    version = cursor.fetchone()[0]
    if version is not None:
        cursor.execute(
            "SELECT dataset_sha256, dataset_kind FROM ETL_DATASET_HISTORY WHERE version=%s",
            (version,),
        )
        if cursor.fetchone() != (state[0], state[1]):
            raise ValueError("Current version and dataset history disagree")
        return version
    cursor.execute("SELECT COUNT(*) FROM ETL_DATASET_HISTORY")
    if cursor.fetchone()[0]:
        raise ValueError("History exists without a current version")
    cursor.execute(
        "INSERT INTO ETL_DATASET_HISTORY "
        "(version,dataset_sha256,dataset_kind,applied_at,action) VALUES (1,%s,%s,%s,'baseline')",
        state,
    )
    cursor.execute("UPDATE ETL_LOAD_STATE SET current_version=1 WHERE singleton_id=1")
    return 1


def record(cursor, fingerprint, kind, manifest, changes, action, label=None, previous=0):
    version = previous + 1
    cursor.execute(
        "INSERT INTO ETL_DATASET_HISTORY "
        "(version,dataset_sha256,dataset_kind,applied_at,action,version_label,manifest_json,changes_json) "
        "VALUES (%s,%s,%s,UTC_TIMESTAMP(6),%s,%s,%s,%s)",
        (
            version,
            fingerprint,
            kind,
            action,
            label_value(label),
            json.dumps(manifest),
            json.dumps(changes),
        ),
    )
    cursor.execute(
        "UPDATE ETL_LOAD_STATE SET current_version=%s, dataset_sha256=%s, "
        "dataset_kind=%s, loaded_at=UTC_TIMESTAMP() WHERE singleton_id=1",
        (version, fingerprint, kind),
    )
    return version


def utc(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value is not None else None


def read(cursor):
    """Read history without migrating or needing any local dataset files."""
    cursor.execute("SET time_zone = '+00:00'")
    if has_table(cursor):
        cursor.execute(
            "SELECT h.version,h.dataset_sha256,h.dataset_kind,h.applied_at,h.action,"
            "h.version_label,h.changes_json,(h.version=s.current_version) "
            "FROM ETL_DATASET_HISTORY h LEFT JOIN ETL_LOAD_STATE s ON s.singleton_id=1 "
            "ORDER BY h.version DESC"
        )
        entries = [
            {
                "version": row[0],
                "dataset_sha256": row[1],
                "dataset_kind": row[2],
                "applied_at": utc(row[3]),
                "action": row[4],
                "label": row[5],
                "changes": json.loads(row[6]) if row[6] else None,
                "current": bool(row[7]),
            }
            for row in cursor.fetchall()
        ]
        if entries:
            return entries
    cursor.execute(
        "SELECT dataset_sha256,dataset_kind,loaded_at FROM ETL_LOAD_STATE WHERE singleton_id=1"
    )
    state = cursor.fetchone()
    if not state:
        return []
    return [
        {
            "version": 1,
            "dataset_sha256": state[0],
            "dataset_kind": state[1],
            "applied_at": utc(state[2]),
            "action": "baseline",
            "label": None,
            "changes": None,
            "current": True,
        }
    ]


def run():
    from unikegg import loader

    connection = loader.connect()
    try:
        cursor = connection.cursor()
        try:
            entries = read(cursor)
            result = {
                "current_version": next((r["version"] for r in entries if r["current"]), None),
                "versions": entries,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result
        finally:
            cursor.close()
    finally:
        connection.close()
