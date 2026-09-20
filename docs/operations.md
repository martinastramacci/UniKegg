# Operations

## Runtime contract

Run from the repository root or set `UNIKEGG_HOME` to that directory. `UNIKEGG_DATA_DIR` defaults to `data/`; `UNIKEGG_PROCESSED_DIR` overrides its `processed/` child. The container fixes these paths to `/app` and `/data`. Host paths are supplied through Compose bind mounts. The loader copies the bundle to a private temporary directory, validates that copy and renders SQL paths within it; the host bundle is never rewritten.

`db/init/001_schema.sql` defines the 20 biological tables. `002_load_state.sql` defines one operational metadata table. Both are applied by MySQL's image entrypoint on first initialization. No destructive schema reset is included. Existing volumes are not automatically migrated when DDL changes. Back up existing databases and apply reviewed migrations separately; an automated migration framework is outside this implementation's scope.

Data loads first create and validate a private snapshot, then acquire a MySQL advisory lock, require an empty domain database on first load, and insert data in foreign-key order. Before insertion the private copy is re-encoded with every field quoted, preventing the literal text `NULL` in legacy bundles from being interpreted as SQL NULL. Nullable fields are converted only when `OCTET_LENGTH` is zero, not through collation-sensitive equality; whitespace and combining marks are preserved. The fingerprint always identifies the original verified manifest, not the transport encoding. All domain writes and the load-state row are committed together. A validation failure, SQL error or warning leaves the dataset uncommitted. The database remains available after a failed ETL process, but must not be treated as a successful demo until the `ready` event appears. `unikegg verify` checks the recorded manifest identity, table counts, sequence lengths and referential integrity. It is not an exhaustive byte-for-byte comparison of every database field.

For retries use `docker compose run --rm etl load`. An identical committed manifest triggers verification rather than duplicate insertion. A different dataset is rejected; use a different Compose project name and port to retain both. The loader never uses `REPLACE`, disables foreign keys or deletes biological tables. No production backup schedule, TLS deployment, secret manager or high-availability topology is implied by the local demonstration configuration.

`LOAD DATA LOCAL INFILE` is enabled on the server. The Python client restricts local-file access to that load's private snapshot directory. The directory is removed on success or failure; later host-side edits cannot affect SQL input. The application container mounts this directory read-only and does not receive root database credentials. Treat the MySQL endpoint as trusted; this configuration is for local use. Application credentials have database-scoped privileges assigned by the image initializer, not a production least-privilege role split.

## Existing datasets

Place all twenty TSVs under `data/processed/`. Preserve headers, UTF-8 encoding, LF line endings and CSV-style double quoting. File names, ordered columns, primary keys, secondary unique keys, references and domain constraints are defined in `src/unikegg/schema.json`. The validator checks unsigned ranges, exact decimal range/scale and UTF-8 byte limits for TEXT/MEDIUMTEXT. Key/reference fields use printable non-space ASCII identifiers, allowing validation to match the database's case-insensitive key equality without guessing Unicode collation weights. Free text remains UTF-8. Blank records, ragged rows and malformed CSV are rejected; large fields use a shared 16,777,216-character CSV limit followed by SQL byte-size validation. Do not remove quote characters or line breaks with an ad hoc text editor. Generate the manifest against the corresponding reviewed raw export:

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

The parser consumes UniProt TSV exports; downloaded JSON is retained as an optional original representation. KEGG reaction and compound detail requests are derived from the configured organisms' mappings and requested in batches of at most ten records. Acquisition uses timeouts, bounded retries and temporary files. A KEGG cached response is reused only when its recorded request and SHA-256 match and its format is complete. Unrecorded, corrupt or wrong-request cache entries are downloaded again; interrupted HTTP reads participate in all four bounded retry attempts. A malformed acquisition manifest fails explicitly rather than being silently ignored. Empty relationship responses are allowed, but empty required catalogs and gene lists are not. Reuse is not a freshness check; create a separate raw directory when refreshing upstream data.

Both UniProt entry points share the same request plan and default names (`{taxid}_{code}.tsv.gz`). If only the legacy `.index.tsv.gz` file exists, it is reused instead of creating a second export. If both exist, acquisition fails before making requests: select a single coherent export explicitly; the program does not delete either copy. `--dry-run` is supported only for the two download commands. Other commands reject it before performing any work.

`unikegg transform` performs a KEGG preflight (required files, column counts, known raw checksums, source endpoints, unique/terminated flat-file records, and presence of all selected reaction/compound details). Authorized manual raw exports without an acquisition manifest are supported, but no program can infer a record missing from every input without an authoritative source inventory. Do not modify the raw snapshot while a transformation runs. Empty detail sets are permitted when no IDs are selected; silently discarding required missing details is not.

Entities, relationships and the processed manifest are then generated in a sibling staging directory and validated there. Source/parse/validation failures leave the previous output bundle untouched. Publication uses a writer lock and a recoverable pair of directory renames. This is **not** a crash-atomic exchange across all operating systems: an interruption between renames can leave a `.unikegg-previous-*` backup and a `.unikegg-{name}.lock` file beside the destination. Before removing a stale lock, ensure no writer remains active, inspect the backup, restore the complete previous bundle if necessary, and run `validate`. Failed automatic recovery retains the backup rather than deleting it. Do not delete backups blindly.

The transform destination must contain only the twenty known TSVs, `manifest.json` and optionally `.gitkeep`; unrelated files cause an explicit refusal. Reports are staged separately and `UNIKEGG_ARTIFACTS_DIR` may be outside the project. Report destinations are checked for writability before dataset publication; a later report-only publication error is reported separately from a successfully published dataset. Reviewed-status checks are applied while parsing. Raw data and generated output are kept out of the image and Git. Transformation is documented for a local virtual environment; the default demo container's data mounts are intentionally read-only. An acquisition/transform container invocation requires explicit writable mounts and permission for UID 10001.

## Temporary storage and compatibility

A load needs temporary storage for the copied bundle plus the largest TSV being rewritten, including extra enclosure bytes. Repeated verification also copies and validates the source bundle, but does not rewrite it. Standard Python `TMPDIR` controls the private snapshot location. Compose's default `/tmp` is tmpfs and consumes RAM; for a large real bundle, provide a private writable disk-backed mount and set `TMPDIR` accordingly. The ETL user (UID 10001) must be able to create files there.

These corrections do not migrate the database schema or rewrite an already committed database. Newly transformed bytes and annotations (including EC preliminaries and isoform metadata) can produce a different fingerprint, which requires a separate volume as before. A previously loaded database is not retroactively repaired by repeating `load`: `verify` is still a structural check, not a full field comparison. If old import semantics may have affected values, test a fresh load in a separate project/volume and compare the relevant fields before replacing anything.

## Validation and CI

Run `ruff check src tests tools`, `sqlfluff lint db --dialect mysql`, `python tools/lint_ingest.py` and `pytest -q` locally. CI also starts the actual Compose services, waits for automatic loading to finish successfully, verifies the database and repeats the load. The integration fixture includes legacy unquoted `NULL`, quotes, tabs, newlines, backslashes, Unicode, a 200,000-residue sequence and decimal bounds. A separate initially empty database exercises actual SQL warning rejection/rollback, two concurrent loaders, full field-by-field round trips, dataset mismatch rejection and all thirty integration queries. `python -m tests.mysql_integration` is an explicit CI-only runner: it requires `UNIKEGG_MYSQL_TEST_DATABASE=UniKeggRegression` and refuses a schema that already contains tables. It never drops or clears a database. The workflow creates/grants that separate database and removes its own ephemeral Compose volume at the end.

The unit matrix targets Python 3.11 and 3.12. Acquisition tests mock HTTP and raw parser tests use invented records, never live upstream APIs. The Python 3.12 CI job also runs `pip-audit` against the development requirements. This is not a container-image or complete production security audit.

SQLFluff is configured for MySQL with explicit whitespace, indentation, trailing-newline and keyword-case rules. Actual MySQL initialization and loading test dialect execution; linting alone is not a proof of runtime validity. CI is validation-only: it does not publish images, datasets or deploy an environment.

SQLFluff 4.3's MySQL `LOAD DATA` grammar accepts one `SET` expression but not comma-separated assignments. The complete ingestion template is therefore excluded from the direct CLI pass. `tools/lint_ingest.py` separately lints each complete LOAD prefix with every assignment, using the same MySQL dialect and rules. It refuses assignment shapes outside the supported `IF(OCTET_LENGTH(@value) = 0, NULL, @value)` contract. This does not modify executable SQL. Integration executes all original multi-assignment statements on MySQL; parser limitations are not hidden by disabling syntax diagnostics globally.
