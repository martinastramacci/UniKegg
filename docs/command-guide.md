# Practical guide to UniKegg: all commands, step by step

This guide takes you from installation to a queryable database, with examples for the 16 available organisms. The commands refer to the CLI present in the project. The terminal examples use Bash on Linux/macOS and must be executed from the main UniKegg directory, which contains `pyproject.toml` and `docker-compose.yml`.

The blocks of the different paths are **alternatives**: choose the one suited to your starting point. Execute each subsequent step only if the previous one ends without errors.

For an existing 20-table snapshot or database, first follow the [KO migration, acquisition and TSV regeneration procedure](orthology-migration.md). The current contract also requires `ortologia_pathway.tsv` and `ortologia_ec.tsv`.

## Index

1. [Choose the path](#1-choose-the-path)
2. [Install and configure](#2-install-and-configure)
3. [Complete path: from downloads to 16 organisms in the database](#3-complete-path-from-downloads-to-16-organisms-in-the-database)
4. [Download individual organisms, groups, and batches](#4-download-individual-organisms-groups-and-batches)
5. [Load a ready-made dataset](#5-load-a-ready-made-dataset)
6. [Update an already loaded database](#6-update-an-already-loaded-database)
7. [Reference of all UniKegg commands](#7-reference-of-all-unikegg-commands)
8. [Reference of all options](#8-reference-of-all-options)
9. [Directories and environment variables](#9-directories-and-environment-variables)
10. [Docker commands and SQL queries](#10-docker-commands-and-sql-queries)
11. [Test with synthetic data and code checks](#11-test-with-synthetic-data-and-code-checks)
12. [Interruptions and frequent errors](#12-interruptions-and-frequent-errors)

## 1. Choose the path

| Situation | Path |
|---|---|
| I want to build the complete dataset of the 16 organisms | Installation, then section 3 |
| I only need the UniProt reviewed files | Python installation, then section 4; MySQL and KEGG are not needed |
| I already have the twenty-two processed TSVs and their `manifest.json` | Section 5 |
| I already have a loaded database and I want to update it | Section 6 |
| I want to test how it works without downloading biological data | Section 11 |
| I want to know what a command or option does | Sections 7 and 8 |

The complete flow is:

```text
download-uniprot + download-kegg
                ↓
            transform
                ↓
             validate
                ↓
       load (first load)
           or update
                ↓
         verify + history
```

UniProt provides the **reviewed / Swiss-Prot** proteins; KEGG provides genes and other entities/relationships. The UniProt download alone produces files that can be used separately, but transforming the integrated dataset requires both sources.

Without options, downloads select **all 16 organisms**. The public clone does not contain biological data: the presence of the code does not imply the presence of the TSVs.

## 2. Install and configure

### 2.1 Local Python environment

Python 3.11 or later and `pip` are required. The project's CI verifies Python 3.11 and 3.12. From the UniKegg directory:

```bash
python --version
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
unikegg --help
```

The last command must show the list of commands and options. If the system calls Python `python3`, use it to create the virtual environment. After activation, `python` points to the environment's interpreter.

In a new terminal session, re-enter the project directory and reactivate the environment:

```bash
source .venv/bin/activate
```

To exit the environment, use `deactivate`. In PowerShell, the activation is `.\.venv\Scripts\Activate.ps1`; the examples with `export`, `unset`, and `source` in this guide remain specific to Bash.

### 2.2 Docker for the database

To use the database through the provided configuration, install Docker Engine or Docker Desktop with Compose v2, then verify:

```bash
docker --version
docker compose version
```

Prepare the configuration file, if it doesn't already exist:

```bash
if [ ! -f .env ]; then
    cp .env.example .env
fi
```

Open `.env` and check database, user, password, and port. The example values are for a local demonstration. The default published port is `3307` on `127.0.0.1`.

```bash
docker compose config --quiet
```

The absence of errors confirms that Compose can read the configuration. **Compose reads `.env`; the local Python CLI does not read it automatically.** Local commands accessing MySQL require the variables from section 9. Downloads and `transform` do not require MySQL credentials.

### 2.3 Choose where to store the dataset

To use the standard project paths, in a session where you do not want to keep previous overrides:

```bash
unset UNIKEGG_HOME UNIKEGG_DATA_DIR UNIKEGG_PROCESSED_DIR UNIKEGG_REVIEWED_DIR
export UNIKEGG_DATASET_KIND=swissprot
```

The results will be in `data/raw/` and `data/processed/`. Alternatively, to keep a separate snapshot:

```bash
export UNIKEGG_DATA_DIR="$HOME/unikegg-data/catalogo16"
export UNIKEGG_PROCESSED_DIR="$UNIKEGG_DATA_DIR/processed"
unset UNIKEGG_REVIEWED_DIR
export UNIKEGG_DATASET_KIND=swissprot
```

`UNIKEGG_PROCESSED_DIR` makes the processed directory explicit to Compose to mount. Keep these variables for all steps in the same path; in a new terminal, set them again. The commands create the necessary directories.

## 3. Complete path: from downloads to 16 organisms in the database

This path uses local Python for acquisition/transformation and Docker for MySQL and loading. It assumes the installation from section 2. For KEGG acquisition, refer to the conditions mentioned in the [data documentation](data-governance.md).

### Step 1 — Check the catalog

```bash
unikegg list-organisms
```

The catalog order also determines the batches:

| Position | Code | Organism | Batch with `--batch-size 4` |
|---:|---|---|---:|
| 1 | `hsa` | Homo sapiens | 1 |
| 2 | `mmu` | Mus musculus | 1 |
| 3 | `rno` | Rattus norvegicus | 1 |
| 4 | `dre` | Danio rerio | 1 |
| 5 | `dme` | Drosophila melanogaster | 2 |
| 6 | `cel` | Caenorhabditis elegans | 2 |
| 7 | `ath` | Arabidopsis thaliana | 2 |
| 8 | `sce` | Saccharomyces cerevisiae S288c | 2 |
| 9 | `eco` | Escherichia coli K-12 | 3 |
| 10 | `bsu` | Bacillus subtilis 168 | 3 |
| 11 | `spo` | Schizosaccharomyces pombe 972h− | 3 |
| 12 | `ddi` | Dictyostelium discoideum | 3 |
| 13 | `gga` | Gallus gallus | 4 |
| 14 | `xtr` | Xenopus tropicalis | 4 |
| 15 | `mtu` | Mycobacterium tuberculosis H37Rv | 4 |
| 16 | `pae` | Pseudomonas aeruginosa PAO1 | 4 |

The command also shows the UniProt and KEGG taxids. Some intentionally differ: the [acquisition guide](acquisition.md) explains the species/strain choices.

### Step 2 — See the plan before downloading

```bash
unikegg download-uniprot --all-organisms --batch-size 4 --dry-run
unikegg download-kegg --all-organisms --dry-run
```

These previews do not access the network and do not create files. UniProt shows the initial queries; the actual pages depend on the number of proteins. KEGG shows the base requests; the detail batches depend on the obtained relationships.

### Step 3 — Download both sources

```bash
unikegg download-uniprot --all-organisms --batch-size 4
unikegg download-kegg --all-organisms
```

The four UniProt batches are processed in sequence, with one gzip TSV per organism. Each query requests `reviewed:true`; received records are checked before completing the export. A protein does not need a KEGG link to be downloaded.

Raw files are located under the chosen data directory, in `raw/uniprot/` and `raw/kegg/`. Each source logs completion in `selection.json`. To run batches in separate sessions, use section 4.3 instead.

### Step 4 — Transform and validate

```bash
unikegg transform
unikegg validate
```

`transform` reads the completed KEGG selection and requires UniProt to cover all selected organisms. It produces the **twenty-two TSVs** of the biological tables and `manifest.json` in the processed directory. It validates the data before publishing it and prints the `transformed` event at the end.

`validate` rechecks the processed bundle without accessing MySQL. Success includes a message like:

```json
{"event": "dataset_validated", "tables": 22, "kind": "swissprot"}
```

If either command fails, resolve the error before loading.

### Step 5 — Start MySQL and perform the first load

For this example, a dedicated Compose project is used, distinct from the default demo, with a free port:

```bash
export COMPOSE_PROJECT_NAME=unikegg-catalogo16
export MYSQL_PORT=3317
docker compose up -d --wait mysql
docker compose build etl
docker compose run --rm etl load --version-label "First load 16 organisms"
```

Keep the Compose name, port, and processed directory in subsequent commands too. Change the port if `3317` is already in use. The distinct Compose name creates a distinct MySQL volume on first use; if that project has already been used, it reopens the existing volume.

`load` requires empty biological tables on the first load. Upon completion, it prints `event: ready`, `action: loaded`, and `current_version: 1`. Repeating the command with the same dataset performs a verification; if the database contains a different dataset, follow section 6.

The ETL image receives credentials from Compose and mounts the processed directory as read-only. Download and transformation remain in the previous local steps.

### Step 6 — Verify and read the version

```bash
docker compose run --rm etl verify
docker compose run --rm etl history
```

Successful verification prints `event: ready` and `action: verified`. The history shows the current version and applied records, starting from the most recent. To query the data, see section 10.2.

## 4. Download individual organisms, groups, and batches

The examples in this section are alternative acquisition methods. The output paths are those configured in section 2.3.

### 4.1 A single organism or a manual group

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

### 4.2 All organisms or the first N

```bash
# All 16, without explicit grouping:
unikegg download-uniprot --all-organisms

# The first 12 in catalog order:
unikegg download-uniprot --limit 12

# All 16, in consecutive batches of 3: the last one contains one organism.
unikegg download-uniprot --all-organisms --batch-size 3
```

`--limit 12` means twelve **organisms**, not twelve proteins. The download acquires all reviewed proteins returned for each selected taxid.

### 4.3 One batch per session, accumulating all sixteen

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

### 4.4 Add hand-picked groups

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

### 4.5 Also keep the original JSON

```bash
unikegg download-uniprot --organisms hsa,spo --include-json
```

The gzip TSV is always acquired; the gzip JSON is additional. Transformation uses only the TSV. TSV pages are resumable; an interrupted JSON restarts from the beginning of that file. With `--append`, `--include-json` also applies to already selected organisms.

### 4.6 Transform only a part of complete sources

After acquiring both sources for a larger selection:

```bash
unikegg transform --organisms hsa,eco
unikegg validate
```

The new processed bundle contains only the requested subset and replaces the previous one in the destination directory. To keep both, set another `UNIKEGG_PROCESSED_DIR` first. Applying this bundle with `update` would also restrict the database to that subset.

## 5. Load a ready-made dataset

If you already have the twenty-two TSVs and the corresponding `manifest.json`, downloads and `transform` are not needed.

1. Place the complete bundle in `data/processed/` or set `UNIKEGG_PROCESSED_DIR` to its directory.
2. Set `UNIKEGG_DATASET_KIND=swissprot` for a real dataset.
3. Verify the Docker configuration from section 2.2.
4. For a new database execute:

```bash
docker compose build etl
docker compose run --rm etl validate
docker compose up -d --wait mysql
docker compose run --rm etl load
docker compose run --rm etl verify
```

Alternatively for the already set up demo, `docker compose up --build` starts MySQL and the ETL service, whose default command is `load`. The ETL terminates after loading or verifying; MySQL continues to run. In terminal-attached mode, stopping Compose stops the services; to keep them active use `docker compose up --build -d` and check its logs.

If the bundle lacks a manifest, follow section 7.10: the corresponding reviewed export is required to attest provenance. A manifest cannot be rebuilt simply by declaring the data is Swiss-Prot.

## 6. Update an already loaded database

`update` applies **the entire processed dataset**: adds, modifies and removes records to match the database with that bundle. For example, moving from sixteen organisms to three deletes the thirteen excluded ones and related dependent data from the database.

### 6.1 Acquire and prepare a new snapshot

Keep the Compose name and database port to update. Set only the directories of the new snapshot:

```bash
export UNIKEGG_DATA_DIR="$HOME/unikegg-data/catalogo16-updated"
export UNIKEGG_PROCESSED_DIR="$UNIKEGG_DATA_DIR/processed"
unset UNIKEGG_REVIEWED_DIR
export UNIKEGG_DATASET_KIND=swissprot

unikegg download-uniprot --all-organisms --batch-size 4
unikegg download-kegg --all-organisms
unikegg transform
unikegg validate
```

Use a new directory name for each snapshot to keep. If the chosen directory already contains acquisitions, downloads reuse the cache; add `--refresh` to both to request data again.

### 6.2 See the comparison with the database

```bash
docker compose build etl
docker compose run --rm etl update --dry-run
```

The `update_plan` event contains, for each table, the `added`, `modified` and `removed` counts. This dry-run **accesses MySQL**, creates temporary tables and compares data, without changing persistent data, schema or version. It therefore requires an available database, valid credentials and staging space.

### 6.3 Apply and verify

```bash
docker compose run --rm etl update --version-label "Catalog 16 update"
docker compose run --rm etl verify
docker compose run --rm etl history
```

A successful update prints `event: ready`, `action: updated` and the new version. If the fingerprint matches the current one, the command verifies data and returns `action: unchanged` without incrementing the version.

The history records metadata, UTC dates and counts, not a copy of old biological rows. It does not replace a backup and does not provide a restore command. A fingerprint already present as a historical version is rejected as a new update. Further details are in the [updates guide](updates.md).

## 7. Reference of all UniKegg commands

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

### 7.1 `list-organisms`

```bash
unikegg list-organisms
unikegg list-organisms --search pombe
unikegg list-organisms --organisms hsa,eco
unikegg list-organisms --limit 4
```

The search filters by code or scientific name case-insensitively. Taxids are shown in the output, but `--search` is not a taxid search.

### 7.2 `download-uniprot`

```bash
unikegg download-uniprot --all-organisms --batch-size 4
unikegg download-uniprot --organisms hsa --interval 1.5 --attempts 8
```

Downloads reviewed only. Verifies pages, organisms, checksums and release consistency. Options for cumulative selections, batches and JSON are explained in section 4. Reusing a verified cache does not check if newer data exists on the server: to acquire it use `--refresh` or a new directory.

### 7.3 `download-kegg`

```bash
unikegg download-kegg --all-organisms
unikegg download-kegg --organisms hsa,eco --interval 1.5 --attempts 8
```

Acquires selected organisms, genes and KEGG data required by transformation. Internal detail request batches are managed automatically. `--batch-size`, `--batch`, `--append` and `--include-json` are not KEGG options.

### 7.4 `transform`

```bash
unikegg transform
unikegg transform --organisms hsa,eco
unikegg transform --reviewed-export /path/to/export-uniprot
```

The last path is an example to replace with a real directory. `--reviewed-export` selects a **directory**, not a single `.tsv.gz`. The KEGG source remains that of the configured data directory.

Without explicit selection it uses the completed KEGG manifest; for legacy exports without a registered selection it uses the default 16 organisms. The gene/protein association report is written in the artifacts directory as `report_gene_proteina.tsv`.

### 7.5 `validate`

```bash
unikegg validate
```

Checks manifest, checksums, TSV format, keys, references, value constraints and sequence consistency. Uses the selection registered in the bundle. Does not modify the database and does not accept `--dry-run` or selection options.

### 7.6 `load`

With local MySQL variables configured as in section 9.2:

```bash
unikegg load --version-label "First version"
```

Alternatively use `docker compose run --rm etl load --version-label "First version"`. Requires initialized schema; does not autonomously create the database or the twenty-two biological tables. The first load requires empty tables. The same fingerprint already loaded is verified, a different fingerprint is rejected with the instruction to use `update`.

### 7.7 `update`

```bash
unikegg update --dry-run
unikegg update --version-label "New snapshot"
```

Requires a previous loaded version. The command synchronizes the whole bundle and can remove records. The label is optional and must contain 1 to 128 characters. It does not download or transform sources: these steps precede the update.

### 7.8 `verify`

```bash
unikegg verify
```

Requires the processed bundle corresponding to the database. Compares fingerprints, counts, references and column values via temporary tables; does not modify persistent data. `validate` checks files, `verify` also checks their correspondence to the database.

### 7.9 `history`

```bash
unikegg history
```

Returns JSON with `current_version` and the `versions` list: version, `applied_at` date, operation, label, fingerprint, changes and `current` indicator. Accesses MySQL and works even without the local processed bundle. Does not accept organism filters.

### 7.10 `manifest`

To be used when the twenty-two TSVs already exist and you have the reference reviewed export:

```bash
unikegg manifest --reviewed-export data/raw/uniprot
unikegg validate
```

The command reconstructs `manifest.json` by comparing processed accessions with the reviewed export and then validates the dataset. It derives organisms from the processed `ORGANISMO` table; an explicit selection must match that table. It does not create missing TSVs and does not make a dataset valid with unreviewed records. In the normal path, `transform` already generates the manifest and this command is not needed.

## 8. Reference of all options

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

## 9. Directories and environment variables

### 9.1 Local files

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

### 9.2 MySQL connection from the local CLI

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

Use the application user's password configured in the server, not necessarily the root one. If the dedicated example in section 3 was followed, the port is `3317`. The default host value in the code is `localhost`; here the TCP connection to `127.0.0.1` is made explicit.

For an autonomously installed MySQL you need to set up the database, user and schema with files `db/init/001_schema.sql`, `002_load_state.sql` and `003_dataset_history.sql`, in that order. The server must allow `LOCAL INFILE` and the user must be able to operate on tables and create temporary tables. The provided Compose configuration performs schema initialization when creating the empty volume.

### 9.3 Compose variables and paths in the container

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

## 10. Docker commands and SQL queries

### 10.1 Manage services

Always use the same Compose name and configuration for the installation of interest.

| Command | What it does |
|---|---|
| `docker compose config --quiet` | Checks Compose configuration |
| `docker compose build etl` | Rebuilds the ETL image from current code |
| `docker compose up -d --wait mysql` | Starts MySQL in background and waits for availability |
| `docker compose up --build -d` | Starts the full demo; ETL executes `load` |
| `docker compose ps -a` | Shows active and terminated services |
| `docker compose logs -f etl` | Follows logs of the demo's ETL service |
| `docker compose logs --tail 100 mysql` | Shows last MySQL messages |
| `docker compose run --rm etl verify` | Runs verification and removes the temporary container |
| `docker compose run --rm etl history` | Reads history from the database |
| `docker compose stop` | Stops services while preserving containers and volumes |
| `docker compose down` | Removes containers/network of the project, keeping data volumes |

The image's entrypoint is already `unikegg`: after `etl` write `verify`, not `unikegg verify`. Logs from `run --rm` commands appear in the executing terminal; after container removal they are not the logs of the demo's `etl` service.

To preserve the database, avoid the `--volumes` option of `down`, which also deletes volumes. To see recent code changes inside Docker, rebuild the ETL image.

### 10.2 Open MySQL and run queries

This command uses the database and user configured in the container and requires the application password:

```bash
docker compose exec mysql sh -c 'exec mysql -u"$MYSQL_USER" -p "$MYSQL_DATABASE"'
```

At the MySQL prompt execute:

```sql
SELECT COUNT(*) AS organisms FROM ORGANISMO;
SELECT COUNT(*) AS reviewed_proteins FROM PROTEIN_UNIPROT;

SELECT COUNT(*) AS inconsistent_sequences
FROM PROTEIN_UNIPROT
WHERE CHAR_LENGTH(amino_acid_sequence) <> sequence_length;

SELECT o.kegg_code, COUNT(p.accession) AS reviewed_proteins
FROM ORGANISMO AS o
LEFT JOIN PROTEIN_UNIPROT AS p ON p.organism_id = o.organism_id
GROUP BY o.kegg_code
ORDER BY o.kegg_code;

SELECT current_version, dataset_sha256
FROM ETL_LOAD_STATE
WHERE singleton_id = 1;
```

For a complete 16-organism dataset the first result must be `16`; the length check must return `0`. The number of proteins depends on the acquired release, it is not a fixed value.

The thirty integration queries provided by the project are mounted in the container:

```sql
SOURCE /queries/integration.sql;
exit
```

## 11. Test with synthetic data and code checks

### 11.1 Demo without biological acquisition

Fixtures contain invented records for all twenty-two tables and 16 organisms. Use a dedicated session and a distinct Compose project from the real data one:

```bash
python tests/make_fixture.py

export UNIKEGG_PROCESSED_DIR="$PWD/tests/fixtures/processed"
export UNIKEGG_DATASET_KIND=synthetic
export COMPOSE_PROJECT_NAME=unikegg-synthetic
export MYSQL_PORT=3308

unikegg validate
docker compose up -d --wait mysql
docker compose build etl
docker compose run --rm etl load --version-label "Synthetic demo"
docker compose run --rm etl verify
docker compose run --rm etl history
```

The test does not contact UniProt or KEGG; Docker and `pip` may require network for images and dependencies. Port `3308` must be free. Before returning to the real dataset, restore the directory, type, Compose name and port of the real installation.

Generation script options:

| Option | Effect |
|---|---|
| `--output DIRECTORY` | Destination directory; default `tests/fixtures/processed` |
| `--edge-cases` | Includes edge cases, special text and one long sequence |
| `--legacy-quoting` | Produces TSV with legacy quoting mode |

Example for compatibility checks:

```bash
python tests/make_fixture.py --output /tmp/unikegg-fixture --edge-cases --legacy-quoting
```

The script writes files to the indicated destination: choose a directory for fixtures, separate from real data.

### 11.2 Local code checks

With the virtual environment active:

```bash
python -m pip install -r requirements-dev.txt
ruff check src tests tools
sqlfluff lint db --dialect mysql
python tools/lint_ingest.py
pytest -q
```

Ruff checks the Python; SQLFluff checks SQL and style; `lint_ingest.py` separately verifies ingestion instructions; Pytest runs offline tests with invented data and simulated HTTP.

Real MySQL tests are also handled by CI. The `python -m tests.mysql_integration` runner requires an empty regression database named `UniKeggRegression` and `UNIKEGG_MYSQL_TEST_DATABASE=UniKeggRegression`; it is not a command to run on the biological database. Preparation, privileges and runner conditions are described in [operations.md](operations.md) and in the [CI workflow](../.github/workflows/ci.yml).

## 12. Interruptions and frequent errors

### 12.1 Resume an interrupted download

Repeat the same command in the same data directory, keeping selection, batch, `--append` and format. If the initial command had `--refresh`, omit it when resuming.

```bash
# Example: resume batch 2 of a cumulative selection.
unikegg download-uniprot --all-organisms --batch-size 4 --batch 2 --append

# Example: resume KEGG for all sixteen.
unikegg download-kegg --all-organisms
```

Verified TSV pages and completed files are reused. Do not add a new batch with `--append` while the previous one is incomplete. Do not manually modify `selection.json` to mark it complete.

### 12.2 The UniProt release has changed

The `Mixed UniProt releases` error indicates that groups belong to different releases. To reacquire all sixteen:

```bash
unikegg download-uniprot --all-organisms --batch-size 4 --refresh
```

If you only want to update the already started cumulative selection, repeat the command of the group involved adding `--refresh`, for example:

```bash
unikegg download-uniprot --organisms eco,spo --append --refresh
```

In this second example, previously accumulated organisms are also updated. If the update is interrupted, resume it without `--refresh`.

### 12.3 Diagnosis table

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
| `KeyError: MYSQL_PASSWORD` in local CLI | Export the password as in section 9.2; `.env` is not loaded by the CLI |
| MySQL connection refused | Check `docker compose ps -a`, MySQL logs, host and port; from the host computer use the published port |
| `Access denied` | Check actual volume credentials; changing `.env` does not modify already created users |
| `Dataset has not been committed` | Execute `load` on the initialized database before `verify` or `update` |
| `The database contains a different dataset` | To apply the new bundle use `update --dry-run`, then `update`; to verify the old one restore the path to the corresponding bundle |
| `Nonempty database without load state` | The database contains data without recognized load state; use an empty database/project or examine the existing one |
| `Cannot update between synthetic and Swiss-Prot datasets` | Verify Compose project and dataset type; keep synthetic demo and real data separate |
| `This dataset is a historical version` | This is a snapshot already applied in the past; it cannot be presented again as a new update |
| `Another ingestion owns the load lock` | Wait for the load/update already in progress on the database |
| Insufficient space during load/update/verify | Check temporary directory, `etl_tmp` volume and MySQL space; comparison also requires copies and temporary tables |

For details on table format see [schema.md](schema.md); for sources, checkpoints and catalog see [acquisition.md](acquisition.md); for synchronization and versions see [updates.md](updates.md).
