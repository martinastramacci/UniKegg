"""Time the repository's integration queries in a read-only MySQL transaction."""

import json
import re
import time
from pathlib import Path

from unikegg.dataset import sha256
from unikegg.loader import connect

QUERIES = Path(__file__).resolve().parents[1] / "db/queries/integration.sql"


def statements():
    queries = [sql.strip() for sql in re.sub(r"--[^\n]*", "", QUERIES.read_text()).split(";")
               if sql.strip()]
    if any(not re.match(r"(?:SELECT|WITH)\b", sql, re.I) for sql in queries):
        raise ValueError("Benchmark accepts only the repository's SELECT/WITH queries")
    return queries


def run():
    queries = statements()
    connection = connect()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute("SET SESSION MAX_EXECUTION_TIME = 60000")
            connection.start_transaction(readonly=True, consistent_snapshot=True)
            cursor.execute("SELECT VERSION()")
            server = cursor.fetchone()[0]
            cursor.execute("SELECT dataset_sha256 FROM ETL_LOAD_STATE WHERE singleton_id = 1")
            state = cursor.fetchone()
            timings = []
            for number, sql in enumerate(queries, 1):
                started, count = time.perf_counter(), 0
                cursor.execute(sql)
                while batch := cursor.fetchmany(1000):
                    count += len(batch)
                timings.append({"query": number, "rows": count,
                                "elapsed_seconds": time.perf_counter() - started})
            return {"mysql_version": server, "dataset_sha256": state[0] if state else None,
                    "queries_sha256": sha256(QUERIES), "queries": timings,
                    "scope": "one read-only pass; includes result transfer; cache not reset"}
        finally:
            cursor.close()
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
