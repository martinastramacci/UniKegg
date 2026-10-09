# Start UniKegg: Python and SQL or Docker and SQL

[Versione italiana](command-guide.it.md) · [Complete command and option reference](command-reference.md).

UniKegg consists of a Python CLI that acquires and prepares data and a **MySQL** database that stores it for SQL queries. There is no web application to start. Installing Python or running `unikegg load` does not start MySQL or create its schema.

Choose **one** complete path:

- [A. Python and SQL, without Docker](#a-python-and-sql-without-docker): Python and MySQL on your computer, with Ubuntu/systemd setup commands.
- [B. Docker and SQL](#b-docker-and-sql): Python and MySQL in containers; no host Python installation required.
- [C. Queries, existing dumps, migrations and checks](#c-queries-existing-dumps-migrations-and-checks): shared tasks with explicit environment alternatives.

Run `bash` blocks in Bash **from the UniKegg repository root**, containing `pyproject.toml` and `docker-compose.yml`. Run `sql` blocks in the MySQL client. Continue only after the preceding command succeeds. The native installation/service instructions target Ubuntu; they are not universal macOS or Windows commands.

| Starting point | Procedure |
|---|---|
| Code clone without data | Follow A or B, including acquisition and transformation |
| 22 English TSVs and valid `manifest.json` | Select their directory, skip downloads, validate, then load an empty schema |
| Complete SQL dump, including the migrated export | Follow C2: SQL import into an empty schema, without `load` |
| Populated database | Back up, apply required C3 migrations, then preview/apply `update`; do not initialize again |

`raw/` holds source exports, `processed/` the 22 TSVs and manifest, and MySQL a queryable copy. Allow disk space for these copies, temporary staging and transaction logs; requirements depend on selection size. Git does not distribute biological datasets. See [source provenance and access conditions](data-governance.md) before KEGG acquisition.

## A. Python and SQL, without Docker

### A1. Install the tools and start MySQL

You need Python 3.11+, `venv`, `pip`, MySQL Server and the `mysql`/`mysqldump` clients. The schema uses MySQL 8 features and `utf8mb4_0900_ai_ci`; MariaDB is not a verified replacement. Compose uses MySQL 8.0.44 and native checks used 8.4.11.

On Ubuntu, if these components are not already installed:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip mysql-server mysql-client
sudo systemctl enable --now mysql
systemctl status mysql --no-pager
mysql --version
python3 --version
```

| Command | Purpose and reason |
|---|---|
| `apt update` | Refresh package indexes before installation |
| `apt install ...` | Install Python, environment tools, server and clients; a client alone cannot host the database |
| `systemctl enable --now mysql` | Start the server now and enable it at computer startup |
| `systemctl status ...` | Require `active (running)`; this checks the service, not just client availability |
| Version commands | Check installed tools; later `SELECT VERSION()` checks the actual connected server |

If Ubuntu offers a version outside the verified series, use the [official MySQL APT procedure](https://dev.mysql.com/doc/mysql-apt-repo-quick-guide/en/) to select 8.0/8.4. Inspect an existing installation before installing another server over it. [Ubuntu's MySQL documentation](https://ubuntu.com/server/docs/databases-mysql/) covers the packages and service.

### A2. Install the CLI from the correct checkout

Before creating or activating the environment, enter the **main checkout root**. On this computer:

```bash
cd /home/primo/Scaricati/UniKegg
pwd
ls pyproject.toml db/init/001_schema.sql
```

On another computer replace the path with your updated checkout. `pwd` must show its root, not `db/`; `ls` checks the expected files. Changing directory does not switch an already active virtual environment: the following `source` must activate this checkout's environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
python -c 'import unikegg; print(unikegg.__file__)'
unikegg --help
```

`venv` isolates dependencies; `source` selects that interpreter in this terminal. The first installation installs declared runtime dependencies; the editable installation registers the CLI against this checkout. `--no-deps` avoids resolving dependencies again. The printed module path must belong to **this project**, not `prova_unikegg`. Help confirms CLI availability. Reactivate `.venv` in each new terminal. `deactivate` leaves the Python environment but does not stop MySQL.

### A3. Create the database, application account and server setting

For a **new installation**, open the administrative client:

```bash
sudo mysql
```

Ubuntu normally permits local administrator authentication this way. If root uses password authentication, use `mysql -u root -p` instead; `-p` prompts for it. Do not change root authentication just to run the application.

At the MySQL prompt, replace the example password with your own (double any apostrophe inside the SQL string literal):

```sql
SELECT VERSION(), @@port, @@local_infile;
CREATE DATABASE UniKegg CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'unikegg'@'127.0.0.1' IDENTIFIED BY 'REPLACE_WITH_YOUR_PASSWORD';
GRANT ALL PRIVILEGES ON UniKegg.* TO 'unikegg'@'127.0.0.1';
SET PERSIST local_infile = ON;
SHOW GLOBAL VARIABLES LIKE 'local_infile';
exit
```

| Statement | Purpose and reason |
|---|---|
| Initial `SELECT` | Check server version, port and current local loading setting |
| `CREATE DATABASE` | Create an empty Unicode schema with the project's collation |
| `CREATE USER` | Create the application account for local TCP connections to `127.0.0.1` |
| `GRANT ... ON UniKegg.*` | Allow loading, temporary staging and migrations within this schema; no global privileges or `GRANT OPTION` |
| `SET PERSIST ...` | Enable local TSV loading immediately and after restart; requires an administrator and changes a server setting |
| `SHOW ...` | Require `ON`; server permission is needed alongside the CLI's client configuration |
| `exit` | Return to Bash without stopping the server |

The creation statements deliberately omit `IF NOT EXISTS`: if objects already exist, inspect them rather than treating an existing installation as new. Global `FILE` privilege is unnecessary because ingestion uses `LOCAL`. See [MySQL local loading](https://dev.mysql.com/doc/refman/8.4/en/load-data-local-security.html) and [persisted settings](https://dev.mysql.com/doc/refman/8.4/en/persisted-system-variables.html).

### A4. Configure Python connectivity and initialize tables

Before opening the client, check your directory in Bash:

```bash
cd /home/primo/Scaricati/UniKegg
ls db/init/001_schema.sql db/init/002_load_state.sql db/init/003_dataset_history.sql
```

Adapt the checkout path when necessary. **Do not enter `db/`**: MySQL inherits the launch directory, and `SOURCE db/init/...` is relative to it. `/init/...` means a directory at the filesystem root. If the client is already open from the wrong directory, use `exit`, correct the Bash directory and reopen it. Do not repeat initialization scripts that already succeeded.

In Bash:

```bash
export MYSQL_HOST=127.0.0.1
export MYSQL_PORT=3306
export MYSQL_DATABASE=UniKegg
export MYSQL_USER=unikegg
read -r -s -p 'MySQL application password: ' MYSQL_PASSWORD
export MYSQL_PASSWORD
echo
mysql --protocol=TCP -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p "$MYSQL_DATABASE"
```

`export` passes configuration to Python. `read -s` reads the A3 password without displaying it. The CLI **does not automatically read `.env`**. The `mysql` client prompts separately with `-p`; it does not use `MYSQL_PASSWORD`. `--protocol=TCP` and `127.0.0.1` select TCP explicitly; uppercase `-P` is the port. Export `3306` for this server because the CLI defaults to `3307` for Compose.

In the client:

```sql
SELECT DATABASE(), CURRENT_USER(), @@local_infile;
SHOW TABLES;
SOURCE db/init/001_schema.sql;
SOURCE db/init/002_load_state.sql;
SOURCE db/init/003_dataset_history.sql;
SHOW TABLES;
SELECT COUNT(*) AS table_count
FROM information_schema.tables
WHERE table_schema = DATABASE();
exit
```

**Run the three `SOURCE` commands only if the first `SHOW TABLES` is empty.** `SOURCE` reads files on the client machine, relative to the repository root. File `001` creates 22 biological tables and constraints, `002` the load state, and `003` version history. This order satisfies dependencies. Expect **24 empty tables**. Do not execute `db/load/001_ingest.sql` directly: it is a template whose paths the Python loader renders.

A count of 24 alone does not identify the schema version: expect `ORGANISM`, `ORTHOLOGY_KEGG`, `EC_NUMBER`, not `ORGANISMO`, `ORTOLOGIA_KEGG`, `NUMERO_EC`. Italian names mean an older schema was used: follow C3 to rename it without recreating tables.

### A5. Prepare data or select an existing bundle

For a new acquisition, use a dedicated directory and retain these variables for the whole session:

```bash
export UNIKEGG_HOME="$PWD"
export UNIKEGG_DATA_DIR="$PWD/data/native"
export UNIKEGG_PROCESSED_DIR="$UNIKEGG_DATA_DIR/processed"
export UNIKEGG_DATASET_KIND=swissprot
unset UNIKEGG_REVIEWED_DIR
unikegg list-organisms
unikegg download-uniprot --organisms hsa,eco --dry-run
unikegg download-kegg --organisms hsa,eco --dry-run
unikegg download-uniprot --organisms hsa,eco
unikegg download-kegg --organisms hsa,eco
unikegg transform
unikegg validate
```

| Command/setting | Purpose and reason |
|---|---|
| `UNIKEGG_HOME` | Fix the project root containing SQL schema/templates |
| Data directory variables | Isolate this snapshot and select its processed output |
| `UNIKEGG_DATASET_KIND=swissprot` | Require the reviewed biological data contract |
| `unset UNIKEGG_REVIEWED_DIR` | Remove any previous override of the UniProt export directory |
| `list-organisms` | Show the 16 supported organisms and accepted codes |
| Download dry runs | Preview requests without remote access or new files |
| Actual downloads | Acquire both sources, record provenance/selection and reuse verified cache |
| `transform` | Integrate completed raw sources into 22 TSVs, a manifest and report without MySQL |
| `validate` | Check checksums, values and references before database writes |

`hsa,eco` is an explicit example selection. For **all 16 organisms**, replace `--organisms hsa,eco` with `--all-organisms` in both downloads and previews; UniProt also accepts `--batch-size 4`. Both sources must cover the selection being transformed. See [batches, cumulative selections and options](command-reference.md).

If you already have 22 TSVs and a valid manifest, **skip downloads and transformation**, set `UNIKEGG_PROCESSED_DIR` to their actual directory and run `unikegg validate`. Standalone dump TSVs without a manifest belong to C2 instead.

### A6. First load, verification and SQL access

Before loading, check interpreter, project and manifest location:

```bash
python -c 'import unikegg; from unikegg.config import PROJECT, PROCESSED; print("Code:", unikegg.__file__); print("Project:", PROJECT); print("Dataset:", PROCESSED); print("Manifest exists:", (PROCESSED / "manifest.json").is_file())'
unikegg validate
```

Code must come from the main checkout, data from A5's selected directory, and `Manifest exists` must be `True`. A path under `.../db/data/processed` means execution started in `db/` without explicit path configuration. A code path under `prova_unikegg` means you need to activate the main checkout's environment. Resolve these checks first: 24 empty database tables do not mean the TSV bundle is ready.

Run the following commands **one at a time**, stopping at the first error. An empty `history` result after a failed load does not mean loading succeeded.

```bash
unikegg load --version-label "Initial load"
unikegg verify
unikegg history
mysql --protocol=TCP -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p "$MYSQL_DATABASE"
```

`load` transactionally populates the empty schema and records version 1; expect `action: loaded` and `current_version: 1`. `verify` compares database values with the bundle; expect `action: verified`. `history` shows versions, UTC dates and metadata. The last command opens the client for C1 queries. Repeating `load` with the same fingerprint verifies it; a different bundle requires `update`.

### A7. Backups, updates and restarting

Suspend other writers and take a backup before updates:

```bash
mkdir -p artifacts/backups
backup_file="artifacts/backups/unikegg-$(date +%Y%m%d-%H%M%S).sql"
mysqldump --protocol=TCP -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p \
  --single-transaction --no-tablespaces --set-gtid-purged=OFF \
  "$MYSQL_DATABASE" > "$backup_file"
test -s "$backup_file"
```

`mkdir -p` prepares storage; the timestamp distinguishes backups. `--single-transaction` reads a consistent InnoDB snapshot; avoid concurrent DDL migrations. The other flags omit tablespace and GTID administration metadata unnecessary for a single-schema restore. Check **the dump command's exit status**: `test -s` only checks that the file is not empty, not that it is a valid backup.

Repeat A5 with a new snapshot directory, then:

```bash
unikegg update --dry-run
unikegg update --version-label "Data update"
unikegg verify
unikegg history
```

The preview uses MySQL to compare additions, modifications and removals without persistent changes. Inspect it before applying the next command. `update` synchronizes **the entire bundle**: a smaller selection removes excluded organisms and related data. History is metadata, not old row copies or a replacement for backups. Follow C3 first for Italian names or a 20-table schema.

| Command | When to use it |
|---|---|
| `sudo systemctl stop mysql` | Stop the native server, including other databases hosted by that service |
| `sudo systemctl start mysql` | Restart without recreating schema or data |
| `journalctl -u mysql -n 100 --no-pager` | Inspect recent service messages after startup failure |
| `source .venv/bin/activate` | Restore the CLI in a new terminal; also repeat A4/A5 exports and password entry |

## B. Docker and SQL

### B1. Requirements and configuration

Install Docker Engine or Docker Desktop with Linux containers and Compose v2. Images provide Python and MySQL. Check client/daemon availability and prepare `.env`:

```bash
docker --version
docker compose version
docker info
if [ ! -f .env ]; then cp .env.example .env; fi
```

The version commands check clients; `docker info` checks daemon access. The conditional copy preserves existing configuration. Edit `.env` to set database, application user/password and root password. Template values are local demonstration credentials. Compose reads `.env`, but exported Bash variables take precedence; avoid accidentally carrying A's connection settings into this path.

For a separate new installation:

```bash
export COMPOSE_PROJECT_NAME=unikegg-docker
export MYSQL_PORT=3307
export UNIKEGG_PROCESSED_DIR="$PWD/data/docker/processed"
export UNIKEGG_DATASET_KIND=swissprot
mkdir -p data/docker/processed data/docker/tmp artifacts
docker compose config --quiet
docker compose build etl
```

The project name identifies network and volumes: retain it in later sessions. Changing it selects another installation; reusing it reopens existing data. The host port binds to `127.0.0.1`; MySQL inside containers always uses `3306`. `UNIKEGG_*` selects the host bundle and its kind. `mkdir` prepares real mount directories. `config --quiet` checks configuration without printing credentials. `build etl` builds the current Python code and must be repeated after code changes.

### B2. Acquire and transform inside containers

If a complete English bundle with manifest already exists, point `UNIKEGG_PROCESSED_DIR` to it and skip to B3. Otherwise define this Bash function in the same session:

```bash
ukdata() {
  docker compose run --rm --no-deps \
    --user "$(id -u):$(id -g)" \
    -v "$PWD/data/docker:/workspace-data" \
    -v "$PWD/artifacts:/app/artifacts" \
    -e UNIKEGG_DATA_DIR=/workspace-data \
    -e UNIKEGG_PROCESSED_DIR=/workspace-data/processed \
    -e TMPDIR=/workspace-data/tmp \
    etl "$@"
}
ukdata list-organisms
ukdata download-uniprot --organisms hsa,eco --dry-run
ukdata download-kegg --organisms hsa,eco --dry-run
ukdata download-uniprot --organisms hsa,eco
ukdata download-kegg --organisms hsa,eco
ukdata transform
ukdata validate
```

Default ETL mounts are read-only, suitable for loading but not acquisition. The function adds explicit writable data/report mounts. `--rm` removes each completed command container while retaining mounted files; `--no-deps` avoids starting MySQL during preparation. `--user` uses host UID/GID to keep generated Linux files accessible. The `-v` flags mount storage; `-e` sets **container** paths. `TMPDIR` places staging on disk instead of the small memory-backed `/tmp`. `"$@"` forwards function arguments to the CLI. See [Compose run reference](https://docs.docker.com/reference/cli/docker/compose/run/).

The commands list codes, preview acquisition, download both sources, transform and validate. Host results are in `data/docker/raw`, `data/docker/processed` and `artifacts`. For all 16 organisms replace `--organisms hsa,eco` with `--all-organisms` in both downloads and previews. See the [reference](command-reference.md) for other selections. Use normal B3 commands, not `ukdata`, for database operations.

### B3. Start MySQL, load and open SQL

```bash
docker compose run --rm --no-deps etl validate
docker compose up -d --wait mysql
docker compose ps -a
docker compose run --rm etl load --version-label "Initial Docker load"
docker compose run --rm etl verify
docker compose run --rm etl history
docker compose exec mysql sh -c 'exec mysql -u"$MYSQL_USER" -p "$MYSQL_DATABASE"'
```

| Command | Purpose and reason |
|---|---|
| Validation with `--no-deps` | Validate the mounted bundle without starting MySQL |
| `up -d --wait mysql` | Start the server in the background and wait for its health check |
| `ps -a` | Inspect service state and health |
| `run --rm etl load` | Perform initial loading using Compose network and credentials |
| `run --rm etl verify` | Compare all values with the bundle; expect `verified` |
| `run --rm etl history` | Inspect committed versions |
| `exec mysql ...` | Open the client inside MySQL; `-p` requests the application password from `.env` |

**On first initialization of an empty volume**, the MySQL image creates the database/account and imports `001_schema.sql`, `002_load_state.sql` and `003_dataset_history.sql` in order from `db/init`. This creates 22 biological and 2 operational tables. The service already enables `local_infile`; do not repeat A3/A4. Existing volumes do not rerun initialization: use C3 migrations. Changing `.env` passwords does not change accounts already stored in a volume.

Use C1 queries at the prompt. The container query file is `/queries/integration.sql`. Host clients connect to `127.0.0.1:3307` or your chosen published port; the hostname `mysql` only belongs to the Compose network.

### B4. Backups and updates

With other writers suspended:

```bash
mkdir -p artifacts/backups
backup_file="artifacts/backups/unikegg-docker-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T mysql sh -c \
  'MYSQL_PWD="$MYSQL_PASSWORD" exec mysqldump -u"$MYSQL_USER" --single-transaction --no-tablespaces --set-gtid-purged=OFF "$MYSQL_DATABASE"' \
  > "$backup_file"
test -s "$backup_file"
```

Host redirection saves the dump outside the container. `-T` disables pseudo-terminal formatting; `MYSQL_PWD` uses the already configured container password. Dump flags mean the same as A7. Require command success: a nonempty file can still be incomplete.

Prepare a complete new snapshot in a separate directory. To use `ukdata`, change its host `data/docker` mount to that new directory, create its `processed` and `tmp` subdirectories, and point the host `UNIKEGG_PROCESSED_DIR` there. Internal `/workspace-data/...` paths stay the same. Then:

```bash
docker compose build etl
docker compose run --rm etl validate
docker compose run --rm etl update --dry-run
docker compose run --rm etl update --version-label "Docker data update"
docker compose run --rm etl verify
docker compose run --rm etl history
```

Build refreshes the code, validation checks the bundle, and the preview shows differences. Inspect removals before applying the full synchronization. Verification and history confirm the result. Retain the same Compose project name, database and port to update the intended installation.

### B5. Stop and resume

| Command | Purpose |
|---|---|
| `docker compose logs --tail 100 mysql` | Read recent server diagnostics |
| `docker compose stop` | Stop services and retain containers/volumes |
| `docker compose up -d --wait mysql` | Resume MySQL on its existing volume |
| `docker compose down` | Remove containers/network but retain named volumes |

Do not add `--volumes` for a normal shutdown: that removes database storage. Repeat B1 exports in a new terminal; redefine `ukdata` only for data preparation. `docker compose up --build -d` also starts ETL with its default `load` command, so it requires an already prepared bundle and compatible schema. Explicit B3 steps expose validation, startup and loading separately.

## C. Queries, existing dumps, migrations and checks

### C1. SQL queries and expected results

Open the client as in A6 or B3:

```sql
SELECT DATABASE(), VERSION();
SHOW TABLES;
SELECT COUNT(*) AS organism_count FROM ORGANISM;
SELECT COUNT(*) AS protein_count FROM PROTEIN_UNIPROT;
SELECT COUNT(*) AS invalid_sequence_lengths
FROM PROTEIN_UNIPROT
WHERE CHAR_LENGTH(amino_acid_sequence) <> sequence_length;
SELECT o.kegg_code, COUNT(p.accession) AS protein_count
FROM ORGANISM AS o
LEFT JOIN PROTEIN_UNIPROT AS p ON p.organism_id = o.organism_id
GROUP BY o.kegg_code
ORDER BY o.kegg_code;
SELECT current_version, dataset_sha256 FROM ETL_LOAD_STATE WHERE singleton_id = 1;
```

The initial statements identify schema/server and tables. Expect 2 organisms for `hsa,eco` or 16 for the full catalog. Protein counts depend on the source release. Invalid sequence lengths must be 0. The grouped query includes organisms without proteins. The final query reads ETL state and does not apply to standalone dumps without operational tables.

Run **one** of these alternatives to execute all thirty integration queries:

```sql
-- Local client started from the repository root:
SOURCE db/queries/integration.sql;
```

```sql
-- Client inside the MySQL container:
SOURCE /queries/integration.sql;
```

`SOURCE` executes the query file; `exit` closes the client only.

### C2. Import an existing complete SQL dump

A SQL dump contains table creation and data statements. It is not an ETL bundle: **do not run `load`, `manifest` or the three `db/init` files to import it**. The October 8 migrated package, locally under `artifacts/legacy-dump-english-2026-10-08-verified/`, contains 22 biological tables without a Swiss-Prot manifest or ETL history. Its TSVs alone cannot establish reviewed provenance.

Verify checksums from inside the package directory:

```bash
(cd artifacts/legacy-dump-english-2026-10-08-verified && sha256sum -c SHA256SUMS)
```

Parentheses confine the directory change to this command. For another dump follow its inventory and instructions. This local package is not distributed through Git.

**Native MySQL:** after A1, open `sudo mysql` or `mysql -u root -p` and create a separate schema:

```sql
CREATE DATABASE UniKeggImported CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
exit
```

Then, for Ubuntu socket administrator authentication:

```bash
sudo mysql UniKeggImported < artifacts/legacy-dump-english-2026-10-08-verified/unikegg_updated.sql
sudo mysql UniKeggImported
```

For password authentication replace `sudo mysql` with `mysql -u root -p`. `<` feeds the SQL file into the client. The second command opens the imported schema for C1 queries, excluding the ETL-state query.

**Docker:** after B1 and `docker compose up -d --wait mysql`, open root's client:

```bash
docker compose exec mysql mysql -uroot -p
```

Enter `.env`'s root password and execute the same `CREATE DATABASE UniKeggImported ...` above. In Bash:

```bash
docker compose exec -T mysql sh -c \
  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot UniKeggImported' \
  < artifacts/legacy-dump-english-2026-10-08-verified/unikegg_updated.sql
docker compose exec mysql mysql -uroot -p UniKeggImported
```

A separate schema is necessary because Compose already initialized `UniKegg`; the dump needs an **empty** schema. stdin with `-T` transfers the dump without mounting it. These commands do not automatically grant the application account access to `UniKeggImported`; the inspection commands use the administrator.

### C3. Italian table/file names or a 20-table schema

First take an A7/B4 backup and suspend other writers. See the [naming migration](english-names-migration.md) and [KO migration](orthology-migration.md) for preconditions. Do not rerun `001_schema.sql` on a populated database.

For a complete old 22-file bundle with manifest, using the Python environment:

```bash
python tools/migrate_dataset_names.py --source data/processed --output data/processed-english
export UNIKEGG_PROCESSED_DIR="$PWD/data/processed-english"
unikegg validate
python tools/migrate_database_names.py
python tools/migrate_database_names.py --apply
```

The converter verifies checksums and publishes a separate English bundle; the destination must be new. The database commands preview and apply renaming using A4's connection. Inspect the plan first; DDL renames do not roll back with ETL. A 20-file bundle requires complete raw regeneration, not just renaming.

For **Docker**, `tools/` is absent from the image. Mount it explicitly to preview/apply the database rename:

```bash
docker compose run --rm -v "$PWD/tools:/app/tools:ro" --entrypoint python etl tools/migrate_database_names.py
docker compose run --rm -v "$PWD/tools:/app/tools:ro" --entrypoint python etl tools/migrate_database_names.py --apply
```

The entrypoint override runs a Python script while retaining ETL network/credentials. To convert the bundle using Docker:

```bash
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD/tools:/app/tools:ro" -v "$PWD/data:/migration-data" \
  --entrypoint python etl tools/migrate_dataset_names.py \
  --source /migration-data/processed --output /migration-data/processed-english
export UNIKEGG_PROCESSED_DIR="$PWD/data/processed-english"
docker compose run --rm --no-deps etl validate
```

Adapt the host `data` mount to your bundle location. Script paths are container paths; the subsequent export is a host path.

If the previous database had **20 biological tables**, after renaming add the missing bridges using one alternative:

```bash
# Native MySQL, A4 connection:
mysql --protocol=TCP -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p "$MYSQL_DATABASE" < db/migrations/004_orthology_links.sql
```

```bash
# Docker MySQL:
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -u"$MYSQL_USER" "$MYSQL_DATABASE"' < db/migrations/004_orthology_links.sql
```

This creates the bridges but does not populate them. With the complete English bundle validated, follow A7/B4 preview, update, verify and history. A names-only conversion should preview zero biological differences. Lowercase legacy dumps with missing GO columns instead need the dedicated legacy tool described in the KO guide.

### C4. Synthetic demo and code checks

Using the Python environment, generate a **synthetic** bundle:

```bash
python tests/make_fixture.py --edge-cases --legacy-quoting
export UNIKEGG_PROCESSED_DIR="$PWD/tests/fixtures/processed"
export UNIKEGG_DATASET_KIND=synthetic
unikegg validate
```

The generator creates invented records and quoting edge cases. Before `load`, create a separate new schema such as `UniKeggSynthetic` by following A3/A4 with that name. If reusing the existing `unikegg` account, skip `CREATE USER` and grant access to the new schema with `GRANT ALL PRIVILEGES ON UniKeggSynthetic.* TO 'unikegg'@'127.0.0.1';`. Do not synchronize this bundle into a biological database.

Without host Python, after B1:

```bash
mkdir -p tests/fixtures/processed
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD/tests:/app/tests" --entrypoint python etl \
  tests/make_fixture.py --edge-cases --legacy-quoting
export COMPOSE_PROJECT_NAME=unikegg-synthetic
export MYSQL_PORT=3317
export UNIKEGG_PROCESSED_DIR="$PWD/tests/fixtures/processed"
export UNIKEGG_DATASET_KIND=synthetic
docker compose build etl
```

The mount supplies the generator and persists its files. `build etl` prepares the image under the new Compose project name. Separate project/port isolate this demo; continue with B3. Afterwards restore the intended installation's exports.

Development checks in A2's environment:

```bash
python -m pip install -r requirements-dev.txt
ruff check src tests tools
sqlfluff lint db --dialect mysql
python tools/lint_ingest.py
pytest -q
```

The install adds development tools. Ruff checks Python, SQLFluff checks SQL style, `lint_ingest.py` checks the ingestion template's projections, and pytest runs unit/regression tests without downloading biological data. Full MySQL tests need a dedicated disposable database; see [operations](operations.md) and [CI](../.github/workflows/ci.yml).

Use the [command reference](command-reference.md) for options, resumable acquisition, manifests and diagnostics. Connection refused: check service/port; missing `MYSQL_PASSWORD`: repeat A4; disabled `local_infile`: A3; missing tables: A4 or B3 initialization logs; missing manifest: distinguish an ETL bundle from a SQL dump first.
