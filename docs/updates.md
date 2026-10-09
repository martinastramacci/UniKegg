# Update the database and inspect dataset versions

For installation, server startup and credentials, choose [Python and SQL without Docker](command-guide.md#a-python-and-sql-without-docker) or [Docker and SQL](command-guide.md#b-docker-and-sql). This page describes the individual operation in more detail.

For installations with previous Italian table or TSV names, first follow the [English naming migration](english-names-migration.md).

[Italian copy](updates.it.md).

`unikegg update` synchronizes the existing database with the twenty-two TSVs and manifest in `data/processed/` (or `UNIKEGG_PROCESSED_DIR`). It adds new records, changes existing values and removes records absent from the new dataset, including relationships. It preserves the database, biological tables and MySQL volume.

For installations with Italian table names, first follow the [English naming migration](english-names-migration.md). For installations predating the KO extension, also apply the [KO relationship migration](orthology-migration.md) and generate all 22 TSVs. `update` does not automatically create domain tables.

## Commands

With the new dataset transformed and the MySQL connection variables configured:

```bash
unikegg update --dry-run
unikegg update --version-label "September 2026 update"
unikegg history
```

The dry-run reports `added`, `modified` and `removed` counts for every table. It connects to the database and loads temporary comparison tables without changing persistent records, the version or the schema. Labels are optional, nonempty and at most 128 characters. The actual update recalculates its plan against the current database state.

With the dataset mounted through the project's Compose configuration:

```bash
docker compose build etl
docker compose run --rm etl update --dry-run
docker compose run --rm etl update --version-label "September 2026 update"
docker compose run --rm etl history
```

The first load into an empty database remains `unikegg load`; it records version 1 and also accepts `--version-label`. Repeating `load` with a different manifest directs you to `update`. `history` works without local dataset files and returns JSON ordered from newest to oldest.

## Acquire a new source snapshot

`update` applies a complete, validated local dataset. Downloads remain an explicit step. To retain the 16 default organisms:

```bash
unikegg download-kegg --refresh
unikegg download-uniprot --refresh
unikegg transform
unikegg update --dry-run
unikegg update
unikegg history
```

You can specify `--all-organisms` for all sixteen curated organisms or use the same `--organisms hsa,eco,spo` or `--limit N` on both downloads. `transform` derives its selection from completed sources. Acquire into a new `UNIKEGG_DATA_DIR` to preserve the previous snapshot, as explained in the [acquisition guide](acquisition.md).

Synchronization covers **the entire new dataset**. Switching from sixteen organisms to three removes the excluded organisms and their dependent records from the database. It is not a partial update limited to organisms mentioned in a file. `update`, `load` and `verify` respect the validated manifest and reject organism selection options.

## Current version and persistent history

`ETL_LOAD_STATE.current_version` is the persistent version number. Every successful update with a new fingerprint increments it. `ETL_DATASET_HISTORY` stores the number, UTC date, manifest SHA-256, dataset kind, operation (`load`, `update`, `baseline`), optional label, manifest and change counts.

```sql
SELECT current_version, dataset_sha256, loaded_at
FROM ETL_LOAD_STATE WHERE singleton_id = 1;

SELECT version, applied_at, action, version_label, dataset_sha256
FROM ETL_DATASET_HISTORY ORDER BY version DESC;
```

`history` returns dates with offset `+00:00`. To read `loaded_at` as UTC in a SQL session, set `SET time_zone = '+00:00'`; `applied_at` is already stored as a UTC date.

The version identifies local applications of datasets, **not KEGG or UniProt release numbers**. A different hash alone does not establish that annotations are biologically newer: refresh sources and retain acquisition metadata. A fingerprint already present in history is rejected as an update. If it matches the current fingerprint, the command compares all values and returns `unchanged` without incrementing the version. Manual differences are detected even when row counts match.

History retains metadata and dates, not previous biological rows: **it is not a backup and cannot independently restore a previous version**. It does not change the software version in `pyproject.toml`.

## Existing databases, integrity and storage

The first update of an installation predating dataset history adds only the missing metadata column and table. The previously loaded dataset becomes `baseline`, version 1, retaining its original load date; the new dataset becomes version 2. Before updating, `history` shows that baseline through read-only queries. Earlier unrecorded applications cannot be reconstructed.

The client validates a private TSV snapshot, acquires the MySQL lock shared with `load`, and stages the snapshot in temporary tables. Changed rows and necessary dependencies are replaced while respecting foreign keys and unique constraints, including swaps of unique values. Unrelated rows remain in place. History counts describe logical changes: an identical relationship reinserted to update its parent is not counted as modified.

Final checks compare counts, references and every column value. Data, current version and history entry commit in one transaction; SQL errors and warnings roll back the changes. Initial metadata migration precedes that transaction and may remain after failure without recording a new version. This order accounts for [MySQL implicit DDL commits](https://dev.mysql.com/doc/refman/8.0/en/implicit-commit.html).

InnoDB tables and privileges for temporary tables, inserts, deletes and updates are required; initial metadata migration also requires `ALTER`/`CREATE`. The configured application account is reused. The lock coordinates UniKegg commands; suspend manual writes and external writers during synchronization.

Allow storage for the private TSV snapshot, MySQL staging of the complete dataset and transaction logs. The dry-run also stages the entire dataset, so runtime depends on its size. Updating avoids rebuilding the database, but still requires downloading, transforming and comparing the new snapshot.
