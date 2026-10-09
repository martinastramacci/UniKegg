# Migrate the KO–Pathway and KO–EC relationships

For installation, server startup and credentials, choose [Python and SQL without Docker](command-guide.md#a-python-and-sql-without-docker) or [Docker and SQL](command-guide.md#b-docker-and-sql). This page describes the individual operation in more detail.

For installations with previous Italian table or TSV names, first follow the [English naming migration](english-names-migration.md).

[Italian copy](orthology-migration.it.md). Installations with Italian domain names must first follow the [English naming migration](english-names-migration.md).

The model contains **22 biological tables: 11 entities and 11 associations**. `ORTHOLOGY_PATHWAY(ko_id, map_id)` joins `ORTHOLOGY_KEGG` to `PATHWAY_REFERENCE`; `ORTHOLOGY_EC(ko_id, ec_number)` joins KO to the existing `EC_NUMBER` catalog. Both use composite primary keys, non-null foreign keys, reverse-lookup indexes and `ON DELETE RESTRICT ON UPDATE RESTRICT`.

These optional many-to-many associations allow a KO to have multiple EC numbers and pathways, or none. Not every KO is an enzyme. KEGG maps also contain compounds and other components; reference representations can use KO, EC or reactions. An EC number describes a catalytic classification and does not necessarily identify one KEGG reaction. `EC → KO → Pathway` expresses shared annotations; it does not prove that every EC activity of a multifunctional KO participates in all its pathways. Sources: [KEGG PATHWAY](https://www.kegg.jp/kegg/pathway.html), [KEGG API manual](https://www.kegg.jp/kegg/rest/keggapi.html).

## Download and normalization

The API uses `link/<target>/<source>`. KO is the source, so the first raw column is KO:

| Endpoint | Raw under `data/raw/kegg/` | TSV under `data/processed/` |
|---|---|---|
| `/link/pathway/ko` | `relations/ko_pathway.tsv` | `orthology_pathway.tsv`: `ko_id`, `map_id` |
| `/link/enzyme/ko` | `relations/ko_ec.tsv` | `orthology_ec.tsv`: `ko_id`, `ec_number` |

`/link/ko/pathway` and `/link/ko/enzyme` use the reverse direction and return reversed columns. Do not substitute their exports for the files described here. The pipeline removes `ko:`, `path:` and `ec:`, converts both `path:ko00010` and `path:map00010` into `map00010`, and sorts and deduplicates pairs. Preliminary and incomplete EC numbers such as `3.5.1.n3` and `1.1.1.-` are preserved. The EC catalog is the union of UniProt annotations, selected reaction ENZYME fields and direct KO–EC links; EC numbers found only in the last source are retained.

Relationships cover all KOs and reference pathways in the downloaded catalogs, including those without genes in selected organisms. Malformed identifiers, unresolved parents and missing files stop transformation and preserve the previous bundle. Valid empty relationship exports produce header-only TSVs. Links are not inferred through reactions or proteins. Verified HTTP 404 KO–EC orphans are quarantined with warnings, using the evidence described in [operations](operations.md).

From the project root with the updated Python environment:

```bash
# Use the same KEGG/UniProt selection as the existing snapshot.
# Example: hsa,eco already available in UniProt.
unikegg download-kegg --organisms hsa,eco
unikegg transform
unikegg validate
```

Omit `--organisms` for all 16 only when the UniProt export also covers them. Downloads reuse verified cached files and acquire missing files; `--refresh` renews all requests. Authorized manual exports must provide both new raw files in the stated order. `transform` generates **all 22 TSVs and a new manifest**. Adding two files to an old manifest, or creating empty files to bypass checks, is insufficient.

## New schema or an existing populated database

`db/init/001_schema.sql` includes both bridges for new databases. After preparing the 22 TSVs, `docker compose up --build` initializes and imports the dataset using `db/load/001_ingest.sql`, loading catalogs before relationships.

Initialization files are not rerun for existing volumes. Back up the database and previous bundle, suspend other writers, and apply the additive migration using the configured Compose account. First migrate Italian table names if applicable.

```bash
docker compose up -d mysql
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -u"$MYSQL_USER" "$MYSQL_DATABASE"' < db/migrations/004_orthology_links.sql
docker compose build etl
docker compose run --rm etl update --dry-run
docker compose run --rm etl update --version-label "Direct KO-Pathway and KO-EC relationships"
docker compose run --rm etl verify
docker compose run --rm etl history
```

Without Compose, apply the same SQL through `mysql` to the configured database, then run `unikegg update --dry-run`, `unikegg update` and `unikegg verify`. If no dataset has been loaded, use `load` instead of `update`.

The migration requires `CREATE` and `REFERENCES`, preserves existing tables and values and does not disable foreign keys. `IF NOT EXISTS` permits resuming after interruption but does not repair same-name tables with another schema. MySQL DDL commits implicitly: migration precedes the update transaction and may leave empty bridges if ETL fails. `update` synchronizes the complete bundle, including the new associations, and records a new version after verification. Run the dry-run after migration. The current validator rejects old 20-file bundles.

## Verify the mapping

```sql
SELECT ko_id, COUNT(*) AS pathway_count
FROM ORTHOLOGY_PATHWAY GROUP BY ko_id;

SELECT oe.ec_number, oe.ko_id, op.map_id, p.name
FROM ORTHOLOGY_EC AS oe
INNER JOIN ORTHOLOGY_PATHWAY AS op ON op.ko_id = oe.ko_id
INNER JOIN PATHWAY_REFERENCE AS p ON p.map_id = op.map_id
WHERE oe.ec_number = '1.1.1.1';
```

See [schema.md](schema.md) for the ER diagram and constraints.

## Legacy dumps with lowercase names

The Windows `dump_progetto_completo` dump dated 30 September 2026 uses lowercase tables and lacks the current GO evidence columns. On Linux, where table names can be case-sensitive, the preceding SQL migration alone is insufficient for that schema.

`tools/migrate_legacy_dump.py` restores the twenty files into a temporary MySQL instance without a TCP listener, aligns table names, adds GO evidence columns as NULL, and populates the two bridges from checksummed KEGG raw files. It accepts legacy Italian dump filenames as well as English filenames, preserves original values, adds missing catalog parents, exports SQL/TSV and verifies the dump by reimporting into a second database. Native `mysqld`, `mysql`, `mysqldump` binaries and Python dependencies are required. It does not connect to existing servers. Import the resulting SQL dump into an empty schema.

The real migration performed on 5 October preserved 2,006,370 original rows and produced 2,066,856 rows across 22 tables. The delivery included raw sources, report, instructions and checksums. One KO–EC link for K10658, absent from the catalog and independently confirmed HTTP 404, was excluded with recorded evidence. Ordinary transformation and the legacy tool both require matching independent evidence before quarantine.

No Swiss-Prot manifest is fabricated from a dump alone: reviewed provenance requires verified exports. The delivery is a standalone SQL dump without invented ETL history, and is not a complete biological annotation refresh.
