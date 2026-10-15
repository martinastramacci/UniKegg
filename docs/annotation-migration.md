# Annotation fields and EC descriptions

`PROTEIN_GO` now contains only `accession, go_id`. The former `evidence_code`
was not populated by the TSV source; `evidence_source` was the constant
`UniProt export`. Neither described the evidence for an individual assertion.

`EC_NUMBER` contains `ec_number, name, catalytic_activity, comment`. The three
descriptive fields are nullable TEXT, taken from the official
[UniProt ENZYME RDF catalog](https://ftp.uniprot.org/pub/databases/uniprot/current_release/rdf/enzyme.rdf.xz):
`skos:prefLabel`, the labels of referenced `up:activity` nodes, and
`rdfs:comment`, respectively. Multiple activities/comments are retained in
source order as readable text. Missing, preliminary and obsolete entries keep
their EC identifier and relationships even when descriptions are unavailable.
This catalog also describes some incomplete EC classes. The activity text does
not replace the structured KEGG reaction associations.

`PROTEIN_UNIPROT.protein_name` retains names, synonyms, chemical parentheses and
component descriptions, but removes complete `(EC ...)` and `[EC:...]` blocks.
Repeated EC prefixes and multiple identifiers within a block are supported.
Malformed or mixed-content blocks remain intact. EC associations still come
from the dedicated upstream `EC number` field. The original raw export remains
unchanged. KEGG orthology definitions retain their source annotations: their EC
text can include partial classifications absent from the direct KO/EC links.

## New acquisitions

```bash
unikegg download-enzymes
unikegg transform
```

The organism-independent catalog is saved in `data/raw/enzyme/enzyme.rdf.xz`
with its URL, retrieval time and SHA-256 in `manifest.json`. The command supports
`--refresh`, `--dry-run`, `--interval` and `--attempts`. Transformation requires
this file in addition to the existing KEGG and reviewed UniProt exports. A
checksum mismatch or unresolved activity prevents publication.

UniProt and KEGG releases can differ. An EC present in KEGG can lack a description
in the downloaded UniProt catalog; this is preserved as NULL, not inferred from
protein names or silently substituted with a different EC.

## Existing English TSV bundles

```bash
unikegg download-enzymes
PYTHONPATH=src python tools/migrate_annotations.py \
  --source data/processed-english \
  --output data/processed-annotations \
  --enzyme-catalog data/raw/enzyme/enzyme.rdf.xz
UNIKEGG_PROCESSED_DIR="$PWD/data/processed-annotations" unikegg validate
```

The destination must be absent or empty. The migration checks the original
checksums, preserves the reviewed manifest declaration, validates the complete
new bundle and publishes only on success. All primary keys and associations
are retained. It never edits the source bundle. The three changed files are
`ec_number.tsv`, `protein_uniprot.tsv` and `protein_go.tsv`.

For Italian table filenames, use `tools/migrate_dataset_names.py` instead. It
accepts the same `--enzyme-catalog` argument and upgrades old annotation columns
while renaming the files, retaining the original bundle.

## Existing MySQL databases

After retaining a database backup, apply `db/migrations/006_annotations.sql`
once to an existing English schema, then use `unikegg update` with the migrated
TSV bundle and verify it. The SQL changes the structure; the TSV update supplies
EC descriptions and cleaned protein names. Fresh databases use the updated
`db/init/001_schema.sql` directly and must not reapply migration 006. MySQL DDL
is not transactional: do not run this migration concurrently with ingestion.

`tools/migrate_legacy_dump.py` also accepts `--enzyme-catalog`. It first checks
the original values in its isolated MySQL instance, then explicitly applies
these annotation changes before exporting and verifying the final SQL dump.
Its report distinguishes preservation before this migration from the intended
field removals, enrichment and name cleanup.
