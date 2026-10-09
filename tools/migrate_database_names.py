"""Preview or explicitly apply English domain table names in an existing database."""

import argparse
from contextlib import suppress

from unikegg.dataset import TABLES
from unikegg.legacy_names import LEGACY_TABLE_NAMES
from unikegg.loader import connect


def rename_plan(actual):
    """Support complete 20/22-table installations; reject missing/mixed pairs."""
    reverse = {new: old for old, new in LEGACY_TABLE_NAMES.items()}
    bridges = {"ORTHOLOGY_PATHWAY", "ORTHOLOGY_EC"}
    plan, missing_bridges = [], []
    for table in TABLES:
        new = table["name"]
        old = reverse.get(new, new)
        if old != new and old in actual and new in actual:
            raise ValueError(f"Both legacy and English tables exist: {old}, {new}")
        if new in actual:
            continue
        if old in actual:
            plan.append((old, new))
        elif new in bridges:
            missing_bridges.append(new)
        else:
            raise ValueError(f"Required domain table missing: {old} / {new}")
    if len(missing_bridges) == 1:
        raise ValueError("Only one KO bridge exists; complete or repair the KO migration first")
    return plan


def run(apply=False):
    connection = connect()
    cursor, locked = None, False
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT GET_LOCK('unikegg_ingestion', 60)")
        locked = cursor.fetchone()[0] == 1
        if not locked:
            raise RuntimeError("Another ingestion owns the load lock")
        cursor.execute("SHOW TABLES")
        plan = rename_plan({row[0] for row in cursor.fetchall()})
        sql = "RENAME TABLE " + ", ".join(f"`{old}` TO `{new}`" for old, new in plan) + ";"
        print(sql if plan else "Domain table names are already English")
        if apply and plan:
            cursor.execute(sql.removesuffix(";"))
        return plan
    finally:
        if cursor is not None:
            if locked:
                with suppress(Exception):
                    cursor.execute("SELECT RELEASE_LOCK('unikegg_ingestion')")
                    cursor.fetchone()
            cursor.close()
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="execute the planned table rename")
    args = parser.parse_args()
    run(args.apply)


if __name__ == "__main__":
    main()
