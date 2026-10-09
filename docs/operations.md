# Operations

For installations with previous Italian table or TSV names, first follow the [English naming migration](english-names-migration.md).

For complete native MySQL/Python and Docker startup paths, see the [English guide](command-guide.md) or [Italian guide](command-guide.it.md). Full options and acquisition examples are in the [command reference](command-reference.md) ([Italiano](command-reference.it.md)).

## Runtime contract

Run from the repository root or set `UNIKEGG_HOME` to that directory. `UNIKEGG_DATA_DIR` defaults to `data/`; `UNIKEGG_PROCESSED_DIR` overrides its `processed/` child. The container fixes these paths to `/app` and `/data`. Host paths are supplied through Compose bind mounts. The loader copies the bundle to a private temporary directory, validates that copy and renders SQL paths within it; the host bundle is never rewritten.

`db/init/001_schema.sql` defines the 22 biological tables. `002_load_state.sql` and `003_dataset_history.sql` define the current state and version history. All three are applied by MySQL's image entrypoint on first initialization. No destructive schema reset is included. For existing installations, `update` automatically adds the version metadata column/table before any biological writes. This targeted migration does not change the twenty-two domain tables; the new KO bridge tables require the explicit [orthology migration](orthology-migration.md) before `load`, `update` or `verify`.

Data loads first create and validate a private snapshot, then acquire a MySQL advisory lock, require an empty domain database on first load, and insert data in foreign-key order. Before insertion the private copy is re-encoded with every field quoted, preventing the literal text `NULL` in legacy bundles from being interpreted as SQL NULL. Nullable fields are converted only when `OCTET_LENGTH` is zero, not through collation-sensitive equality; whitespace and combining marks are preserved. The fingerprint always identifies the original verified manifest, not the transport encoding. All domain writes and the load-state row are committed together. A validation failure, SQL error or warning leaves the dataset uncommitted. The database remains available after a failed ETL process, but must not be treated as a successful demo until the `ready` event appears. `unikegg verify` checks the recorded manifest identity, table counts, sequence lengths and referential integrity, then compares every database field against a SQL-typed temporary copy of the validated dataset. Text comparison is byte-sensitive and distinguishes NULL from empty strings; numeric values use their database types. Verification does not change persistent data, schema or version history.

For retries use `docker compose run --rm etl load`. An identical committed manifest triggers verification rather than duplicate insertion. A different dataset is rejected; use a different Compose project name and port to retain both. The loader never uses `REPLACE`, disables foreign keys or deletes biological tables. No production backup schedule, TLS deployment, secret manager or high-availability topology is implied by the local demonstration configuration.

`LOAD DATA LOCAL INFILE` is enabled on the server. The Python client restricts local-file access to that load's private snapshot directory. The directory is removed on success or failure; later host-side edits cannot affect SQL input. The application container mounts this directory read-only and does not receive root database credentials. Treat the MySQL endpoint as trusted; this configuration is for local use. Application credentials have database-scoped privileges assigned by the image initializer, not a production least-privilege role split.

## Existing datasets

Place all twenty-two TSVs under `data/processed/`. Preserve headers, UTF-8 encoding, LF line endings and CSV-style double quoting. File names, ordered columns, primary keys, secondary unique keys, references and domain constraints are defined in `src/unikegg/schema.json`. The validator checks unsigned ranges, exact decimal range/scale and UTF-8 byte limits for TEXT/MEDIUMTEXT. Key/reference fields use printable non-space ASCII identifiers, allowing validation to match the database's case-insensitive key equality without guessing Unicode collation weights. Free text remains UTF-8. Blank records, ragged rows and malformed CSV are rejected; large fields use a shared 16,777,216-character CSV limit followed by SQL byte-size validation. Do not remove quote characters or line breaks with an ad hoc text editor. Generate the manifest against the corresponding reviewed raw export:

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

The [acquisition guide](acquisition.md) documents the 16-organism catalog, selection options, resumable pages, refresh and retry controls. Without selection options, all sixteen organisms are used as the default.

If `transform` reports an unresolved KO in `relations/ko_ec.tsv`, rerun
`unikegg download-kegg` with the same organism selection, then `unikegg transform`.
Acquisition reuses verified downloads and refreshes the KO catalog when links
reference absent KOs. Remaining KO/EC orphans are checked through KEGG GET;
only HTTP 404 permits quarantine, recorded in `data/raw/kegg/missing_ko_checks.json`.
Transformation emits a warning for each quarantined assertion and preserves the
original raw relationship. Missing gene KO assignments, malformed links and network failures
remain errors. If gene KOs remain missing after catalog refresh, retry acquisition
with `--refresh` to obtain consistent source exports.

Acquisition also checks selected organisms' gene relationships against their gene
and pathway catalogs before downloading reaction/compound details. If a gene or
pathway is missing, it refreshes the organism catalogs and any relationship files
that still disagree. Verified detail batches are reused. Relationships that remain
inconsistent after this targeted refresh stop acquisition before the detail phase.
An exception applies to gene/pathway links: if the pathway is present and the absent
gene is independently confirmed HTTP 404 by KEGG GET, acquisition records evidence
in `missing_gene_checks.json`. Transformation warns and excludes those links while
preserving raw files. Other HTTP errors and existing genes cannot justify exclusion.
Transform errors distinguish missing genes
from missing targets and identify the files to reconcile.

Expected layout:

```text
data/raw/
├── uniprot/*.tsv.gz          # Reviewed-only export, including annotation fields
│           *.json.gz        # Optional retained source representation
│           manifest.jsonl
│           selection.json
│           .pages/                 # Verified pagination checkpoints
└── kegg/
    ├── organism/organism_list.tsv
    ├── genes/{code}_genes.tsv
    ├── ko/ko_list.tsv
    ├── pathway/pathway_reference.tsv
    │           {code}_pathways.tsv
    ├── relations/*.tsv
    ├── batches/{category}/*.txt
    ├── details/{category}/active.json
    ├── details/{category}/records/*.txt
    ├── selection.json
    └── manifest.jsonl
```

The parser consumes UniProt TSV exports; JSON is acquired only with `--include-json`. TSV acquisition uses `/search` pages with verified checkpoints; optional JSON streams restart the individual file after interruption. Both clients verify request/checksum/content before reusing final files, distinguish temporary HTTP failures, and honor `Retry-After`. Four attempts and one-second pauses are defaults, configurable through `--attempts` and `--interval`. A shared per-host process lock coordinates requests for the same user and temporary directory. A source directory lock prevents concurrent acquisition or transformation of managed sources. Malformed metadata fails explicitly.

KEGG reaction and compound requests use at most ten identifiers per batch. The active detail index lists per-ID files with checksums, preventing overlap with historical batches; expected selections filter out extra records. Empty relationship responses and reviewed result sets are allowed, but empty required KEGG catalogs and gene lists are not. `selection.json` marks incomplete work, which must be resumed before transformation. Refresh with `--refresh`, or preferably use a separate data directory for a new snapshot. Reuse does not query the server for freshness.

Both UniProt entry points share the same request plan and default names (`{taxid}_{code}.tsv.gz`). If only the legacy `.index.tsv.gz` file exists, that filename is retained; its content is reused only if provenance and integrity validate. If both exist, acquisition fails before making requests: select a single coherent export explicitly; the program does not delete either copy. `--dry-run` previews HTTP requests for the two download commands and previews database changes for `update`. Other commands reject it before performing any work.

`unikegg transform` performs a KEGG preflight (required files, column counts, known raw checksums, source endpoints, unique/terminated flat-file records, and presence of all selected reaction/compound details). Authorized manual raw exports without an acquisition manifest are supported, but no program can infer a record missing from every input without an authoritative source inventory. Managed source locks prevent acquisition while transformation reads; manually supplied raw snapshots must also remain unchanged during transformation. Empty detail sets are permitted when no IDs are selected; silently discarding required missing details is not.

Entities, relationships and the processed manifest are then generated in a sibling staging directory and validated there. Source/parse/validation failures leave the previous output bundle untouched. Publication uses a writer lock and a recoverable pair of directory renames. This is **not** a crash-atomic exchange across all operating systems: an interruption between renames can leave a `.unikegg-previous-*` backup and a `.unikegg-{name}.lock` file beside the destination. Before removing a stale lock, ensure no writer remains active, inspect the backup, restore the complete previous bundle if necessary, and run `validate`. Failed automatic recovery retains the backup rather than deleting it. Do not delete backups blindly.

The transform destination must contain only the twenty-two known TSVs, `manifest.json` and optionally `.gitkeep`; unrelated files cause an explicit refusal. Reports are staged separately and `UNIKEGG_ARTIFACTS_DIR` may be outside the project. Report destinations are checked for writability before dataset publication; a later report-only publication error is reported separately from a successfully published dataset. Reviewed-status checks are applied while parsing. Raw data and generated output are kept out of the image and Git. Transformation is documented for a local virtual environment; the default demo container's data mounts are intentionally read-only. An acquisition/transform container invocation requires explicit writable mounts and permission for UID 10001.

## Temporary storage and compatibility

A load needs temporary storage for the copied bundle plus the largest TSV being rewritten, including extra enclosure bytes. Verification and repeated loads also rewrite the private copy and load temporary MySQL tables for comparison; they require `CREATE TEMPORARY TABLES` privileges and space for the full staging dataset. Source files remain unchanged. Standard Python `TMPDIR` controls the private snapshot location. Compose mounts `etl_tmp` at `/app/tmp` and the image sets `TMPDIR=/app/tmp`, keeping large working copies and SQLite sorting on disk. The ETL user (UID 10001) must be able to create files there.

Newly transformed bytes and annotations can produce a different fingerprint. Apply a new complete snapshot with `unikegg update --dry-run`, then `unikegg update`; the command synchronizes additions, changes and removals without recreating the database. `unikegg history` lists committed versions and dates. Repeating `load`, running `verify`, and repeating `update` with the current fingerprint all compare every staged field and reject manual data drift. See the [update guide](updates.md) for legacy migration, atomicity, selection semantics and the distinction between version history and backups. MySQL needs additional space for temporary staging tables and transaction logs.

## Validation and CI

Run `ruff check src tests tools`, `sqlfluff lint db --dialect mysql`, `python tools/lint_ingest.py` and `pytest -q` locally. CI also starts the actual Compose services, waits for automatic loading to finish successfully, verifies the database and repeats the load. The integration fixture includes legacy unquoted `NULL`, quotes, tabs, newlines, backslashes, Unicode, a 200,000-residue sequence and decimal bounds. A separate initially empty database exercises actual SQL warning rejection/rollback, two concurrent loaders, full field-by-field round trips, dataset mismatch rejection and all thirty integration queries. `python -m tests.mysql_integration` is an explicit CI-only runner: it requires `UNIKEGG_MYSQL_TEST_DATABASE=UniKeggRegression` and refuses a schema that already contains tables. It never drops or clears a database. Its update tests deliberately remove and recreate only version metadata in that disposable schema to exercise legacy migration, and verify synchronization, unique-key swaps, organism removal, preview, concurrent updates and rollback of data and history. The workflow creates/grants that separate database and removes its own ephemeral Compose volume at the end.

The unit matrix targets Python 3.11 and 3.12. Acquisition tests mock HTTP and raw parser tests use invented records, never live upstream APIs. The Python 3.12 CI job also runs `pip-audit` against the development requirements. This is not a container-image or complete production security audit.

SQLFluff is configured for MySQL with explicit whitespace, indentation, trailing-newline and keyword-case rules. Actual MySQL initialization and loading test dialect execution; linting alone is not a proof of runtime validity. CI is validation-only: it does not publish images, datasets or deploy an environment.

SQLFluff 4.3's MySQL `LOAD DATA` grammar accepts one `SET` expression but not comma-separated assignments. The complete ingestion template is therefore excluded from the direct CLI pass. `tools/lint_ingest.py` separately lints each complete LOAD prefix with every assignment, using the same MySQL dialect and rules. It refuses assignment shapes outside the supported `IF(OCTET_LENGTH(@value) = 0, NULL, @value)` contract. This does not modify executable SQL. Integration executes all original multi-assignment statements on MySQL; parser limitations are not hidden by disabling syntax diagnostics globally.
