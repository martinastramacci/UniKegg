# Migrate domain names and dataset files to English

For server startup and configuration, first follow the [Python and SQL or Docker and SQL guide](command-guide.md). Section C3 also shows how to run the migration tools inside containers.

[Italian copy](english-names-migration.it.md).

New installations use English domain table names, English TSV filenames and English guide filenames. Columns, keys, biological identifiers and source values remain unchanged. Italian-language guides use the same English base filename plus `.it.md`.

## Name mapping

| Previous table | Current table | Current TSV |
|---|---|---|
| ORGANISMO | ORGANISM | organism.tsv |
| ORTOLOGIA_KEGG | ORTHOLOGY_KEGG | orthology_kegg.tsv |
| PATHWAY_RIFERIMENTO | PATHWAY_REFERENCE | pathway_reference.tsv |
| REAZIONE_KEGG | REACTION_KEGG | reaction_kegg.tsv |
| COMPOSTO_KEGG | COMPOUND_KEGG | compound_kegg.tsv |
| TERMINE_GO | GO_TERM | go_term.tsv |
| NUMERO_EC | EC_NUMBER | ec_number.tsv |
| PATHWAY_ORGANISMO | PATHWAY_ORGANISM | pathway_organism.tsv |
| GENE_PROTEINA | GENE_PROTEIN | gene_protein.tsv |
| GENE_ORTOLOGIA | GENE_ORTHOLOGY | gene_orthology.tsv |
| ORTOLOGIA_REAZIONE | ORTHOLOGY_REACTION | orthology_reaction.tsv |
| PATHWAY_REAZIONE | PATHWAY_REACTION | pathway_reaction.tsv |
| REAZIONE_COMPOSTO | REACTION_COMPOUND | reaction_compound.tsv |
| PROTEINA_GO | PROTEIN_GO | protein_go.tsv |
| PROTEINA_EC | PROTEIN_EC | protein_ec.tsv |
| REAZIONE_EC | REACTION_EC | reaction_ec.tsv |
| ORTOLOGIA_PATHWAY | ORTHOLOGY_PATHWAY | orthology_pathway.tsv |
| ORTOLOGIA_EC | ORTHOLOGY_EC | orthology_ec.tsv |

`GENE_KEGG`, `PROTEIN_UNIPROT`, `PROTEIN_ISOFORM` and `GENE_PATHWAY` already have English names and retain their filenames. Operational metadata tables retain their names and stored historical manifests. The diagnostic file is now `report_gene_protein.tsv`. Legacy dump conversion produces `unikegg_updated.sql` and `excluded_relationships.tsv`.

## A previous 22-file processed bundle

Convert into a separate directory; the source bundle is preserved:

```bash
PYTHONPATH=src python tools/migrate_dataset_names.py \
  --source data/processed --output data/processed-english
export UNIKEGG_PROCESSED_DIR="$PWD/data/processed-english"
unikegg validate
```

Conversion verifies every original checksum, preserves TSV bytes and reviewed declarations, rewrites manifest file keys, and validates the complete English bundle before publication. Choose an unused output directory. The new manifest has a new fingerprint because filenames changed; use `update` for a loaded database, not `load`.

Alternatively regenerate from completed raw sources into a separate output directory:

```bash
export UNIKEGG_PROCESSED_DIR="$PWD/data/processed-english"
unikegg transform
unikegg validate
```

The original Italian-name output directory cannot be overwritten by the English transformer because its old TSVs are unrelated to the current destination contract. Keep it as the source snapshot and select another output directory. A 20-file bundle needs full regeneration with the current KO links, rather than the naming conversion utility.

## An existing database

Configure the existing MySQL connection environment and suspend external writers. Preview the renames, then apply the reviewed plan:

```bash
PYTHONPATH=src python tools/migrate_database_names.py
PYTHONPATH=src python tools/migrate_database_names.py --apply
```

The utility uses the ingestion lock and one `RENAME TABLE` statement, rejects old/new name collisions, and supports complete 20-table or 22-table schemas. Repeating it on an English schema makes no changes. It does not load records or alter version metadata. MySQL DDL has implicit commits; perform the schema step before an ETL update.

A database with twenty biological tables additionally needs `db/migrations/004_orthology_links.sql` **after** the naming step, before synchronizing a complete regenerated bundle. A database with twenty-two Italian tables can instead use `db/migrations/005_english_names.sql` once. The static SQL expects every old table to exist; use the utility for 20-table or already English installations.

With a validated English dataset selected:

```bash
unikegg update --dry-run
unikegg update --version-label "English domain names"
unikegg verify
unikegg history
```

For a rename-only dataset conversion, the preview should show no biological differences. The new fingerprint is recorded through the normal update transaction. Historical manifest and change records retain their original names as historical evidence. No database migration or update runs merely by installing the new source files.

## Legacy SQL dumps

`tools/migrate_legacy_dump.py` accepts either the previous Italian dump filenames or English filenames, resolves old imported lowercase table names and exports the current English schema. If both variants exist for the same table, it rejects the ambiguous input. Preserve original dumps and acquisition artifacts; regenerated exports use the new filenames.

## Installation path

Create or activate the virtual environment belonging to the main project, then install from its root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
python -c 'import unikegg; print(unikegg.__file__)'
```

The printed path must belong to the main project. Activating the test copy's environment continues to load that copy's editable installation even after changing directories.
