# UniKegg command reference

[Startup guide: Python and SQL or Docker and SQL](command-guide.md) · [Italiano](command-reference.it.md).

Use this reference for options, selections, paths and troubleshooting; follow the startup guide for installation and database setup. The `unikegg` examples use the local CLI; in the Docker path use `ukdata` for acquisition/transformation and `docker compose run --rm etl` for database operations.

## 1. Download individual organisms, groups, and batches

The examples in this section are alternative acquisition methods. The output paths are those configured in the startup guide.

### 1.1 A single organism or a manual group

```bash
# Only Homo sapiens:
unikegg download-uniprot --organisms hsa

# A specific group:
unikegg download-uniprot --organisms hsa,mmu,eco

# The same organisms in KEGG, if you want to transform later:
unikegg download-kegg --organisms hsa,mmu,eco
unikegg transform
unikegg validate
```

Use the catalog codes, separated by commas. Unknown, empty, or duplicate codes are rejected. The actual order follows the catalog even if the list is written in a different order.

### 1.2 All organisms or the first N

```bash
# All 16, without explicit grouping:
unikegg download-uniprot --all-organisms

# The first 12 in catalog order:
unikegg download-uniprot --limit 12

# All 16, in consecutive batches of 3: the last one contains one organism.
unikegg download-uniprot --all-organisms --batch-size 3
```

`--limit 12` means twelve **organisms**, not twelve proteins. The download acquires all reviewed proteins returned for each selected taxid.

### 1.3 One batch per session, accumulating all sixteen

In the same data directory, execute the commands in order, even on different days/sessions:

```bash
unikegg download-uniprot --all-organisms --batch-size 4 --batch 1 --append
unikegg download-uniprot --all-organisms --batch-size 4 --batch 2 --append
unikegg download-uniprot --all-organisms --batch-size 4 --batch 3 --append
unikegg download-uniprot --all-organisms --batch-size 4 --batch 4 --append
```

`--batch` is numbered from 1. `--append` merges the batch with the already registered selection and rechecks previous files, reusing them when valid. It works even when a selection does not yet exist. Starting from a new directory, the completed selections contain 4, 8, 12, and 16 organisms, respectively.

The command may also show previous organisms as `Retained UniProt organisms`: they are included in the verification of the cumulative selection. Without `--append` the manifest represents only the last requested selection; other files remain on disk but are not automatically included in the selection available for transformation.

The batch number always refers to the indicated selection: with `--limit 8 --batch-size 4` there are two batches, while with `--all-organisms --batch-size 4` there are four.

### 1.4 Add hand-picked groups

```bash
unikegg download-uniprot --organisms hsa,mmu
unikegg download-uniprot --organisms eco,spo --append
```

At the end the selection contains `hsa,mmu,eco,spo`. To obtain the corresponding integrated dataset:

```bash
unikegg download-kegg --organisms hsa,mmu,eco,spo
unikegg transform
unikegg validate
```

KEGG does not accept `--append`: request the entire final selection, leaving it to the client to reuse the verified cache.

### 1.5 Also keep the original JSON

```bash
unikegg download-uniprot --organisms hsa,spo --include-json
```

The gzip TSV is always acquired; the gzip JSON is additional. Transformation uses only the TSV. TSV pages are resumable; an interrupted JSON restarts from the beginning of that file. With `--append`, `--include-json` also applies to already selected organisms.

### 1.6 Transform only a part of complete sources

After acquiring both sources for a larger selection:

```bash
unikegg transform --organisms hsa,eco
unikegg validate
```

The new processed bundle contains only the requested subset and replaces the previous one in the destination directory. To keep both, set another `UNIKEGG_PROCESSED_DIR` first. Applying this bundle with `update` would also restrict the database to that subset.


## 2. Reference of all UniKegg commands

| Command | Main input | Result | Network/database |
|---|---|---|---|
| `list-organisms` | Code-included catalog | Filterable list with codes and taxids | None |
| `download-uniprot` | Organism selection | Reviewed export and raw metadata | UniProt, except dry-run/cache |
| `download-kegg` | Organism selection | KEGG export and raw metadata | KEGG, except dry-run/cache |
| `transform` | Raw UniProt and KEGG | Twenty-two processed TSVs, manifest and report | None |
| `validate` | Processed bundle and manifest | Integrity checks | None |
| `load` | Processed bundle and MySQL schema | First load/version | MySQL |
| `update` | Processed bundle and loaded database | Synchronization and new version | MySQL |
| `verify` | Processed bundle and loaded database | Complete comparison | MySQL |
| `history` | Metadata in the database | JSON History | MySQL |
| `manifest` | Twenty-two TSVs and reviewed export | Regenerated manifest and validation | None |

### 2.1 `list-organisms`

```bash
unikegg list-organisms
unikegg list-organisms --search pombe
unikegg list-organisms --organisms hsa,eco
unikegg list-organisms --limit 4
```

The search filters by code or scientific name case-insensitively. Taxids are shown in the output, but `--search` is not a taxid search.

### 2.2 `download-uniprot`

```bash
unikegg download-uniprot --all-organisms --batch-size 4
unikegg download-uniprot --organisms hsa --interval 1.5 --attempts 8
```

Downloads reviewed only. Verifies pages, organisms, checksums and release consistency. Options for cumulative selections, batches and JSON are explained in section 1. Reusing a verified cache does not check if newer data exists on the server: to acquire it use `--refresh` or a new directory.

### 2.3 `download-kegg`

```bash
unikegg download-kegg --all-organisms
unikegg download-kegg --organisms hsa,eco --interval 1.5 --attempts 8
```

Acquires selected organisms, genes and KEGG data required by transformation. Internal detail request batches are managed automatically. `--batch-size`, `--batch`, `--append` and `--include-json` are not KEGG options.

### 2.4 `transform`

```bash
unikegg transform
unikegg transform --organisms hsa,eco
unikegg transform --reviewed-export /path/to/export-uniprot
```

The last path is an example to replace with a real directory. `--reviewed-export` selects a **directory**, not a single `.tsv.gz`. The KEGG source remains that of the configured data directory.

Without explicit selection it uses the completed KEGG manifest; for legacy exports without a registered selection it uses the default 16 organisms. The gene/protein association report is written in the artifacts directory as `report_gene_protein.tsv`.

### 2.5 `validate`

```bash
unikegg validate
```

Checks manifest, checksums, TSV format, keys, references, value constraints and sequence consistency. Uses the selection registered in the bundle. Does not modify the database and does not accept `--dry-run` or selection options.

### 2.6 `load`

With local MySQL variables configured as in section 4.2:

```bash
unikegg load --version-label "First version"
```

Alternatively use `docker compose run --rm etl load --version-label "First version"`. Requires initialized schema; does not autonomously create the database or the twenty-two biological tables. The first load requires empty tables. The same fingerprint already loaded is verified, a different fingerprint is rejected with the instruction to use `update`.

### 2.7 `update`

```bash
unikegg update --dry-run
unikegg update --version-label "New snapshot"
```

Requires a previous loaded version. The command synchronizes the whole bundle and can remove records. The label is optional and must contain 1 to 128 characters. It does not download or transform sources: these steps precede the update.

### 2.8 `verify`

```bash
unikegg verify
```

Requires the processed bundle corresponding to the database. Compares fingerprints, counts, references and column values via temporary tables; does not modify persistent data. `validate` checks files, `verify` also checks their correspondence to the database.

### 2.9 `history`

```bash
unikegg history
```

Returns JSON with `current_version` and the `versions` list: version, `applied_at` date, operation, label, fingerprint, changes and `current` indicator. Accesses MySQL and works even without the local processed bundle. Does not accept organism filters.

### 2.10 `manifest`

To be used when the twenty-two TSVs already exist and you have the reference reviewed export:

```bash
unikegg manifest --reviewed-export data/raw/uniprot
unikegg validate
```

The command reconstructs `manifest.json` by comparing processed accessions with the reviewed export and then validates the dataset. It derives organisms from the processed `ORGANISM` table; an explicit selection must match that table. It does not create missing TSVs and does not make a dataset valid with unreviewed records. In the normal path, `transform` already generates the manifest and this command is not needed.

## 3. Reference of all options

For integrated help use `unikegg --help` or `unikegg -h`. The CLI uses a single parser: even `unikegg download-uniprot --help` shows the general help. The table specifies the supported combinations.

| Option | Commands accepting it | Meaning and example |
|---|---|---|
| `-h`, `--help` | All | Shows help and exits |
| `--organisms CODES` | `list-organisms`, both downloads, `transform`, `manifest` | List of distinct codes: `--organisms hsa,eco,spo` |
| `--limit N` | Same as explicit selection | First N catalog organisms; from 1 to 16 |
| `--all-organisms` | Same as explicit selection | All 16 from the curated catalog |
| `--search TEXT` | `list-organisms` | Filter code or scientific name: `--search pombe` |
| `--dry-run` | Both downloads, `update` | Preview without acquisition for downloads; MySQL comparison without persistent changes for `update` |
| `--refresh` | Both downloads | Reacquires exports; UniProt restarts checkpoints |
| `--include-json` | `download-uniprot` | Adds gzip JSON to gzip TSVs |
| `--batch-size N` | `download-uniprot` | Groups of N organisms; from 1 to 16 |
| `--batch N` | `download-uniprot` | Only batch N of the selection; from 1 to number of batches, requires `--batch-size` |
| `--append` | `download-uniprot` | Merges requested selection with previous one in the same directory |
| `--interval SECONDS` | Both downloads | Minimum pause per request; default `1.0`, range `0.34`–`3600` |
| `--attempts N` | Both downloads | Total attempts per request; default `4`, from 1 to 20 |
| `--reviewed-export DIRECTORY` | `transform`, `manifest` | Directory of reviewed exports to read |
| `--version-label TEXT` | `load`, `update` | Label of the applied version; from 1 to 128 characters |

`--organisms`, `--limit` and `--all-organisms` are mutually exclusive. Selection options on `manifest` check correspondence with existing tables, they do not filter TSVs. `load`, `update`, `validate` and `verify` always respect the perimeter already registered in the processed manifest.

With `--append --refresh`, UniProt updates **the entire cumulative selection**, including previous organisms. To resume an interrupted refresh, repeat the command without `--refresh`: the program keeps the necessary state to complete the started update.

Options not supported by a command are rejected. For example, `unikegg validate --dry-run` and `unikegg download-kegg --append` are usage errors, not valid previews.

## 4. Directories and environment variables

### 4.1 Local files

| Variable | Default in local CLI | Use |
|---|---|---|
| `UNIKEGG_HOME` | Current directory | Project root, also containing `db/` |
| `UNIKEGG_DATA_DIR` | `UNIKEGG_HOME/data` | Root of `raw/` sources and, if not redefined, `processed/` |
| `UNIKEGG_PROCESSED_DIR` | `UNIKEGG_DATA_DIR/processed` | Directory of the twenty-two TSVs and manifest |
| `UNIKEGG_REVIEWED_DIR` | `UNIKEGG_DATA_DIR/raw/uniprot` | Exports read by transform/manifest; does not change downloader destination |
| `UNIKEGG_ARTIFACTS_DIR` | `UNIKEGG_HOME/artifacts` | Reports generated by transformation |
| `UNIKEGG_DATASET_KIND` | `swissprot` | Type expected by validation and DB operations; `synthetic` only for fixtures |
| `TMPDIR` | System temporary directory | Workspace for temporary copies and sorting |

An explicit `--reviewed-export` option overrides `UNIKEGG_REVIEWED_DIR`. `UNIKEGG_PROCESSED_DIR`, if set, overrides the processed directory derived from `UNIKEGG_DATA_DIR`: remember this when switching to another snapshot.

Essential structure in the data directory:

```text
raw/
  uniprot/
    9606_hsa.tsv.gz
    selection.json
    manifest.jsonl
    .pages/
  kegg/
    genes/
    relations/
    batches/
    details/
    selection.json
    manifest.jsonl
processed/
  manifest.json
  ... twenty-two TSV files ...
```

`selection.json` describes the selection and its completion; `manifest.jsonl` keeps the provenance of exports; the processed `manifest.json` identifies the bundle to load. Raw pages and batches remain available for resumption and occupy space beyond the final files.

### 4.2 MySQL connection from the local CLI

The local CLI requires `MYSQL_PASSWORD`; other parameters have the defaults indicated here:

```bash
export MYSQL_HOST=127.0.0.1
export MYSQL_PORT=3307
export MYSQL_DATABASE=UniKegg
export MYSQL_USER=unikegg
read -r -s -p 'Application MySQL password: ' MYSQL_PASSWORD
export MYSQL_PASSWORD
echo

unikegg history
```

Use the application user's password configured in the server, not necessarily the root one. Use `3306` for native MySQL or the published port, normally `3307`, for Compose. The default host value in the code is `localhost`; here the TCP connection to `127.0.0.1` is made explicit.

For an autonomously installed MySQL you need to set up the database, user and schema with files `db/init/001_schema.sql`, `002_load_state.sql` and `003_dataset_history.sql`, in that order. The server must allow `LOCAL INFILE` and the user must be able to operate on tables and create temporary tables. The provided Compose configuration performs schema initialization when creating the empty volume.

### 4.3 Compose variables and paths in the container

| Setting | Behavior |
|---|---|
| `COMPOSE_PROJECT_NAME` | Separates names and volumes of installations; project default `unikegg` |
| `MYSQL_PORT` | Port on the host computer; inside containers MySQL stays on `3306` |
| `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD` | Initial configuration of the MySQL service; ETL receives only application credentials |
| `UNIKEGG_PROCESSED_DIR` | Path on the host computer to mount in `/data/processed` |
| `UNIKEGG_DATASET_KIND` | Dataset type expected by the ETL service |

Variables exported in the terminal override corresponding values in `.env`. The ETL configuration internally sets `MYSQL_HOST=mysql` and `MYSQL_PORT=3306`; do not use the hostname `mysql` in the CLI executed on the host computer.

`UNIKEGG_DATA_DIR` does not automatically reconfigure Compose volumes: indicate `UNIKEGG_PROCESSED_DIR` for loading. The default raw mount remains `./data/raw`, but `load`, `update` and `verify` use the processed bundle. Data mounts and the ETL filesystem are read-only; the `etl_tmp` volume provides the writable temporary area `/app/tmp`.

Changing passwords in `.env` after initialization does not change the credentials stored in the existing MySQL volume.


## 5. Interruptions and frequent errors

### 5.1 Resume an interrupted download

Repeat the same command in the same data directory, keeping selection, batch, `--append` and format. If the initial command had `--refresh`, omit it when resuming.

```bash
# Example: resume batch 2 of a cumulative selection.
unikegg download-uniprot --all-organisms --batch-size 4 --batch 2 --append

# Example: resume KEGG for all sixteen.
unikegg download-kegg --all-organisms
```

Verified TSV pages and completed files are reused. Do not add a new batch with `--append` while the previous one is incomplete. Do not manually modify `selection.json` to mark it complete.

### 5.2 The UniProt release has changed

The `Mixed UniProt releases` error indicates that groups belong to different releases. To reacquire all sixteen:

```bash
unikegg download-uniprot --all-organisms --batch-size 4 --refresh
```

If you only want to update the already started cumulative selection, repeat the command of the group involved adding `--refresh`, for example:

```bash
unikegg download-uniprot --organisms eco,spo --append --refresh
```

In this second example, previously accumulated organisms are also updated. If the update is interrupted, resume it without `--refresh`.

### 5.3 Diagnosis table

| Message or symptom | What to check/do |
|---|---|
| `unikegg: command not found` | Activate `.venv` and verify installation with `python -m pip install --no-deps -e .` |
| `Expected distinct codes from list-organisms` | Use catalog codes, without duplicates or empty elements |
| `--batch requires --batch-size` | Specify both options; numbering starts from 1 |
| `Incomplete acquisition` | Resume the download of the indicated source before transforming |
| `resume the same selection and formats` | Repeat the interrupted group with the same selection, append and JSON options |
| `UniProt acquisition does not cover selected organisms` | Complete UniProt for the entire KEGG selection, using `--append` where necessary, or transform a complete subset |
| `Missing/duplicate selected UniProt exports` | Verify that the selection contains only one export per organism; resume acquisition if files are missing |
| `Duplicate UniProt exports` | Both current name and legacy `.index.tsv.gz` are present; keep a consistent snapshot, possibly acquiring in a new directory |
| HTTP `429` or temporary errors | Let retries and cooldown act; increase `--interval` and, if necessary, `--attempts` |
| HTTP `400` or `404` | These are permanent client errors; check request/configuration instead of repeating without changes |
| `Acquisition already running` | Wait for the end of the downloader/transformer using that source; the lock file can exist even when the lock is not active |
| `Transformation lock exists` | Verify there is no active writer and follow recovery described in [operations.md](operations.md), inspecting any backups before removing a residual lock |
| `Output directory contains unrelated files` | Choose a dedicated processed destination for the twenty-two TSVs and manifest |
| `Checksum mismatch`, duplicate keys or missing references | Check snapshot consistency and regenerate from correct raw; regenerating only the manifest does not correct data |
| Processed files or manifest not found | Verify `UNIKEGG_PROCESSED_DIR`; execute `transform` or provide the complete bundle |
| `KeyError: MYSQL_PASSWORD` in local CLI | Export the password as in section 4.2; `.env` is not loaded by the CLI |
| MySQL connection refused | Check `systemctl status mysql` for native MySQL or `docker compose ps -a` for Docker, then logs, host and port; from the host computer use the published port |
| `Access denied` | Check actual volume credentials; changing `.env` does not modify already created users |
| `Dataset has not been committed` | Execute `load` on the initialized database before `verify` or `update` |
| `The database contains a different dataset` | To apply the new bundle use `update --dry-run`, then `update`; to verify the old one restore the path to the corresponding bundle |
| `Nonempty database without load state` | The database contains data without recognized load state; use an empty database/project or examine the existing one |
| `Cannot update between synthetic and Swiss-Prot datasets` | Verify Compose project and dataset type; keep synthetic demo and real data separate |
| `This dataset is a historical version` | This is a snapshot already applied in the past; it cannot be presented again as a new update |
| `Another ingestion owns the load lock` | Wait for the load/update already in progress on the database |
| Insufficient space during load/update/verify | Check temporary directory, `etl_tmp` volume and MySQL space; comparison also requires copies and temporary tables |

For details on table format see [schema.md](schema.md); for sources, checkpoints and catalog see [acquisition.md](acquisition.md); for synchronization and versions see [updates.md](updates.md).
