# Operations

## Runtime contract

Run from the repository root or set `UNIKEGG_HOME` to that directory. `UNIKEGG_DATA_DIR` defaults to `data/`; `UNIKEGG_PROCESSED_DIR` overrides its `processed/` child. The container fixes these paths to `/app` and `/data`. Host paths are supplied through Compose bind mounts; SQL paths are resolved and quote-escaped by the loader.

`db/init/001_schema.sql` defines the 20 biological tables. `002_load_state.sql` defines one operational metadata table. Both are applied by MySQL's image entrypoint on first initialization. No destructive schema reset is included. Existing volumes are not automatically migrated when DDL changes. Back up existing databases and apply reviewed migrations separately; an automated migration framework is outside this implementation's scope.

Data loads acquire a MySQL advisory lock, validate the full TSV contract, require an empty domain database on first load, and insert data in foreign-key order. All domain writes and the load-state row are committed together. A validation failure, SQL error or warning leaves the dataset uncommitted. The database remains available after a failed ETL process, but must not be treated as a successful demo until the `ready` event appears. `unikegg verify` checks the recorded manifest identity, table counts, sequence lengths and referential integrity. It is not an exhaustive byte-for-byte comparison of every database field.

For retries use `docker compose run --rm etl load`. An identical committed manifest triggers verification rather than duplicate insertion. A different dataset is rejected; use a different Compose project name and port to retain both. The loader never uses `REPLACE`, disables foreign keys or deletes biological tables. No production backup schedule, TLS deployment, secret manager or high-availability topology is implied by the local demonstration configuration.

`LOAD DATA LOCAL INFILE` is enabled on the server. The Python client restricts file access to the configured processed-data directory. The application container mounts this directory read-only and does not receive root database credentials. Treat the MySQL endpoint as trusted; this configuration is for local use. Application credentials have database-scoped privileges assigned by the image initializer, not a production least-privilege role split.

## Existing datasets

Place all twenty TSVs under `data/processed/`. Preserve headers, UTF-8 encoding, LF line endings and CSV-style double quoting. File names, ordered columns, primary keys and references are defined in `src/unikegg/schema.json`. Do not remove quote characters or line breaks with an ad hoc text editor. Generate the manifest against the corresponding reviewed raw export:

```bash
unikegg manifest --reviewed-export data/raw/uniprot
unikegg validate
```

`--reviewed-export` is a directory containing `.tsv.gz` files, not a single filename. Every export must contain `Entry` and `Reviewed` columns. Every processed protein accession must exist among explicitly reviewed records. A manifest is generated after that comparison and is checked again before loading. Keep a single coherent upstream snapshot; do not combine historical and current exports in this directory.

The same option can select the reviewed source directory for `unikegg transform`. Alternatively, set `UNIKEGG_REVIEWED_DIR`. Duplicate upstream accessions across exports are rejected to prevent implicit merging of overlapping snapshots.

The prepared real snapshot was validated against its existing reviewed export before creating the local manifest. Its manifest remains with the ignored dataset rather than entering the public Git repository.

## Acquisition and transformation

The demo does not need raw data. To refresh the dataset, obtain appropriate upstream permissions and use a separate working data directory. Do not overwrite the prepared snapshot merely to run the demo.

```bash
unikegg download-uniprot --dry-run
unikegg download-kegg --dry-run
# After reviewing access terms and the request scope:
unikegg download-uniprot
unikegg download-kegg
unikegg transform
```

Expected layout:

```text
data/raw/
├── uniprot/*.tsv.gz          # Reviewed-only export, including annotation fields
│           *.json.gz        # Optional retained source representation
│           manifest.jsonl
└── kegg/
    ├── organism/organism_list.tsv
    ├── genes/{code}_genes.tsv
    ├── ko/ko_list.tsv
    ├── pathway/pathway_reference.tsv
    │           {code}_pathways.tsv
    ├── relations/*.tsv
    ├── details/reaction/*.txt
    ├── details/compound/*.txt
    └── manifest.jsonl
```

The parser consumes UniProt TSV exports; downloaded JSON is retained as an optional original representation. KEGG reaction and compound detail requests are derived from the configured organisms' mappings and requested in batches of at most ten records. Acquisition uses timeouts, bounded retries and temporary files. Complete existing files are reused. Reuse is not a freshness check; create a separate raw directory when refreshing upstream data.

`unikegg transform` runs the adapted existing entity and relationship parsers, then emits and validates the processed manifest. Reviewed-status checks are applied while parsing. Raw data and generated output are kept out of the image and Git. Transformation is documented for a local virtual environment; the default demo container's data mounts are intentionally read-only. An acquisition/transform container invocation requires explicit writable mounts and permission for UID 10001.

## Validation and CI

Run `ruff check src tests tools`, `sqlfluff lint db --dialect mysql`, `python tools/lint_ingest.py` and `pytest -q` locally. CI also starts the actual Compose services, waits for automatic loading to finish successfully, verifies the database and repeats the load. The synthetic fixture deliberately contains quoted text to exercise TSV enclosure handling.

SQLFluff is configured for MySQL with explicit whitespace, indentation, trailing-newline and keyword-case rules. Actual MySQL initialization and loading test dialect execution; linting alone is not a proof of runtime validity. CI is validation-only: it does not publish images, datasets or deploy an environment.

SQLFluff 4.3's MySQL `LOAD DATA` grammar accepts one `SET` expression but not comma-separated assignments. The complete ingestion template is therefore excluded from the direct CLI pass. `tools/lint_ingest.py` separately lints each complete LOAD prefix with every assignment, using the same MySQL dialect and rules. It refuses assignment shapes outside the supported `NULLIF` contract. This does not modify executable SQL. Integration executes all original multi-assignment statements on MySQL; parser limitations are not hidden by disabling syntax diagnostics globally.
