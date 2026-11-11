# Dataset quality, provenance and operational measurements

## Quality report

With the package installed, run against the configured `UNIKEGG_PROCESSED_DIR`:

```bash
unikegg quality > quality.json
unikegg quality --compare-to /path/to/previous/processed > comparison.json
```

The command copies and validates each bundle before reading it. It does not connect
to MySQL or change the input dataset. stdout contains one JSON document; validation
events go to stderr. Use `UNIKEGG_DATASET_KIND=synthetic` for synthetic bundles.
Both comparison inputs must have the same dataset kind. Keep reports alongside
archived bundles; `dataset_sha256` identifies the exact manifest, also used by load
history. No filename or timestamp is interpreted as a release number.

Each organism includes:

- Total genes, CDS genes, proteins and distinct gene/protein pairs.
- Pairs supported by both sources, KEGG only, or UniProt only.
- Genes and proteins without a mapping; CDS genes with a mapping.
- Genes with multiple proteins and proteins with multiple genes.
- CDS coverage (covered CDS / CDS), protein coverage (mapped proteins / proteins)
  and source agreement (both-source pairs / all distinct pairs), in percent.

Two source assertions for the same pair count once. Identifiers use the same
case-insensitive comparison as the validator and MySQL. A zero denominator produces
JSON `null`, not zero coverage. CDS coverage excludes non-CDS genes; protein
coverage includes all proteins in the selected reviewed dataset.

Comparison returns count differences and percentage-point differences for shared
organisms, and separately lists added/removed organisms. Every decrease in coverage
or agreement is listed under `decreases_to_review`. These are review signals, not
automatic rejection thresholds: changed releases, denominators and selection can
legitimately change coverage. Multiple mappings and source disagreement are not
automatically biological errors. This report does not certify experimental function.

`transform` also stores deterministic quality metrics in the new manifest. The
standalone command recomputes metrics rather than trusting an embedded summary,
and works with old manifests. Existing rejection reports remain unchanged.

## Provenance

New transformations include `provenance` in `manifest.json`:

- Relative file names, byte sizes and SHA-256 hashes for each raw source directory.
- A digest of each source inventory, and acquisition dates/releases when matching
  acquisition records are available.
- Installed software version (or `null` when unavailable), Python version, hashes
  of package Python files and schema, and an aggregate code digest.

The inventory describes a directory snapshot, including inactive exports; it is
not a claim that every inventoried row was used. Hidden files, transport batch
caches, partial files and locks are excluded. Keep the complete raw directories,
including their acquisition manifests and active indexes, with the processed
bundle. Source inventories and code are checked before and after transformation;
detected changes abort publication. Managed acquisition locks remain in effect.
Manual exports must remain immutable throughout the operation.

Missing release metadata stays unknown (an empty release list), especially for
manual exports and KEGG responses without a release identifier. Hashes identify
bytes, not biological freshness or authenticity. No release is inferred from a
local version counter. Source dates remain in acquisition records; transformation
wall-clock time is deliberately excluded from the manifest to preserve repeatability.

Old manifests remain supported and are not rewritten. `manifest` reconstructs
integrity metadata and reviewed membership only; it cannot establish which raw
sources or transformer produced an already existing bundle. Use `transform` for
the new provenance record. Reordering raw rows or changing the transformer changes
the manifest fingerprint even when all resulting TSV values remain equal; update
history can consequently record a new version with zero biological changes.

Annotation and naming migrations retain original provenance and append a
`derivations` entry with the input manifest hash, operation and migration script
hash (plus the ENZYME catalog hash for annotation migration). They do not claim
that the original transformer generated the migrated output directly.

## Measurements and MySQL benchmark

The quality JSON includes elapsed seconds for copying, validating and reporting,
process peak RSS in bytes on Linux/macOS (`null` elsewhere), and the current private
snapshot's byte size. Baseline comparison time is included when requested. Peak RSS
is the process lifetime high-water mark, not a sampled per-phase measurement.
Snapshot size is measured disk usage in file bytes, not filesystem blocks or an
estimate of MySQL staging/transaction-log requirements.

For MySQL, configure the same connection environment as the CLI and run:

```bash
python tools/benchmark_queries.py > query-benchmark.json
```

This executes all 30 repository integration queries once, in a read-only consistent
transaction, with a 60-second server limit per SELECT. It records server version,
committed dataset fingerprint, query-file hash, result row counts and elapsed time
including result transfer. Results are consumed in batches, not printed. Errors
fail the command; no partial report is presented as complete. It rolls back and
closes the connection on success or failure. An initialized UniKegg database and
SELECT permission are required. The script does not load data or reset caches.
Run on a quiet database and record machine/load conditions when comparing results;
read-only queries still consume database resources. A fingerprint identifies the
declared load state, not a new verification of every database value.

Load/update timings and database disk peaks require a separate test database.
They are not measured by the quality command or query benchmark. To measure an
update, retain both old and new validated bundles, load the old one in an isolated
database, then time `update --dry-run`, `update` and `verify` with the new bundle.
Never use a smaller selection as a performance fixture against the working database:
update removes records outside the complete new selection.

## Backup and restore exercise

Use the backup commands in the [startup guide](command-guide.md), checking the
dump process exit status. Before each real update retain the previous bundle,
its raw sources, report, code version and successful database dump. Choose backup
frequency and retention according to the acceptable amount of lost work.

Periodically restore a dump into a new, empty, isolated MySQL database using the
same compatible server version. Point `MYSQL_DATABASE` at that restored database
and `UNIKEGG_PROCESSED_DIR` at the matching archived bundle, then run `unikegg verify`
and the query benchmark. Record restore time and results. A backup is not considered
tested until this exercise succeeds. The version-history table alone cannot
restore old biological rows. Scheduling/retention policies are deployment choices;
this change does not install a scheduler or modify a running database.
