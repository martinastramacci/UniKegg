"""Atomic bulk ingestion with warning rejection and explicit dataset identity."""

import json
import os
import re
import time
from contextlib import suppress

import mysql.connector

from unikegg.config import PROCESSED, PROJECT
from unikegg.dataset import TABLES, validate


def connect():
    return mysql.connector.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3307")),
        user=os.environ.get("MYSQL_USER", "unikegg"),
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ.get("MYSQL_DATABASE", "UniKegg"),
        charset="utf8mb4",
        autocommit=False,
        use_pure=True,
        allow_local_infile=False,
        allow_local_infile_in_path=str(PROCESSED),
        raise_on_warnings=True,
        connection_timeout=10,
        sql_mode="ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION",
    )


def load_statements(sql, directory):
    """Render paths after splitting the template, including apostrophes in host paths."""

    def filename(match):
        path = (directory / match.group(1)).as_posix()
        quote = '"' if "'" in path else "'"
        if quote in path or any(char in path for char in "\r\n\x00"):
            raise ValueError("Unsupported quote or control character in processed-data path")
        # Connector/Python 9.4's LOCAL INFILE scanner does not decode doubled quotes.
        # Select an absent delimiter instead; the connection uses non-ANSI_QUOTES mode.
        return quote + path + quote

    for statement in re.sub(r"--[^\n]*", "", sql).split(";"):
        if statement.strip():
            yield re.sub(r"'\{\{DATA_DIR\}\}/([^']+)'", filename, statement)


def verify(connection, manifest):
    cursor = connection.cursor()
    try:
        for table in TABLES:
            cursor.execute(f"SELECT COUNT(*) FROM `{table['name']}`")
            actual = cursor.fetchone()[0]
            expected = manifest["files"][table["file"]]["rows"]
            if actual != expected:
                raise ValueError(
                    f"Database count mismatch for {table['name']}: {actual} != {expected}"
                )
        cursor.execute(
            "SELECT COUNT(*) FROM PROTEIN_UNIPROT WHERE CHAR_LENGTH(amino_acid_sequence) <> sequence_length"
        )
        if cursor.fetchone()[0]:
            raise ValueError("Database protein sequences are truncated")
        for table in TABLES:
            for fk in table["fk"]:
                cursor.execute(
                    f"SELECT COUNT(*) FROM `{table['name']}` c LEFT JOIN `{fk['parent']}` p "
                    f"ON c.`{fk['column']}` = p.`{fk['target']}` WHERE p.`{fk['target']}` IS NULL"
                )
                if cursor.fetchone()[0]:
                    raise ValueError(f"Database orphan reference: {table['name']}")
    finally:
        cursor.close()


def run(verify_only=False):
    kind = os.environ.get("UNIKEGG_DATASET_KIND", "swissprot")
    manifest, fingerprint = validate(PROCESSED, kind)
    connection = connect()
    cursor = connection.cursor()
    locked = False
    try:
        cursor.execute("SELECT GET_LOCK('unikegg_ingestion', 60)")
        locked = cursor.fetchone()[0] == 1
        if not locked:
            raise RuntimeError("Another ingestion owns the load lock")
        cursor.execute("SELECT dataset_sha256 FROM ETL_LOAD_STATE WHERE singleton_id=1")
        state = cursor.fetchone()
        if state and state[0] != fingerprint:
            raise ValueError("The database contains a different dataset; use a separate volume")
        if state or verify_only:
            if not state:
                raise ValueError("Dataset has not been committed")
            verify(connection, manifest)
            print(
                json.dumps({"event": "ready", "dataset_sha256": fingerprint, "action": "verified"}),
                flush=True,
            )
            return
        for table in TABLES:
            cursor.execute(f"SELECT EXISTS(SELECT 1 FROM `{table['name']}`)")
            if cursor.fetchone()[0]:
                raise ValueError("Nonempty database without load state; refusing to overwrite")
        sql = (PROJECT / "db/load/001_ingest.sql").read_text(encoding="utf-8")
        statements = load_statements(sql, PROCESSED)
        for statement in statements:
            if statement.strip():
                start = time.monotonic()
                cursor.execute(statement)
                print(
                    json.dumps(
                        {
                            "event": "table_loaded",
                            "rows": cursor.rowcount,
                            "seconds": round(time.monotonic() - start, 3),
                        }
                    ),
                    flush=True,
                )
        verify(connection, manifest)
        cursor.execute(
            "INSERT INTO ETL_LOAD_STATE(singleton_id,dataset_sha256,dataset_kind) VALUES (1,%s,%s)",
            (fingerprint, kind),
        )
        connection.commit()
        print(
            json.dumps({"event": "ready", "dataset_sha256": fingerprint, "action": "loaded"}),
            flush=True,
        )
    except Exception:
        with suppress(mysql.connector.Error):
            connection.rollback()
        raise
    finally:
        if locked:
            with suppress(mysql.connector.Error):
                cursor.execute("SELECT RELEASE_LOCK('unikegg_ingestion')")
                cursor.fetchone()
        with suppress(mysql.connector.Error):
            cursor.close()
        connection.close()
