# Avviare UniKegg: Python e SQL oppure Docker e SQL

[English version](command-guide.md) · [Riferimento completo di comandi e opzioni](command-reference.it.md).

UniKegg comprende una CLI Python che acquisisce e prepara i dati e un database **MySQL** che li conserva e permette le interrogazioni SQL. Non c'è un sito web da avviare. Installare Python o eseguire `unikegg load` non avvia MySQL e non crea automaticamente lo schema.

Scegliere **uno** dei due percorsi completi:

- [A. Python e SQL, senza Docker](#a-python-e-sql-senza-docker): Python e MySQL installati sul computer; esempio operativo Ubuntu con systemd.
- [B. Docker e SQL](#b-docker-e-sql): Python e MySQL nei container; non serve Python sul computer host.
- [C. Query, dump esistenti, migrazioni e controlli](#c-query-dump-esistenti-migrazioni-e-controlli): passaggi comuni, distinguendo i due ambienti.

Eseguire i blocchi `bash` nel terminale **dalla radice di UniKegg**, dove si trovano `pyproject.toml` e `docker-compose.yml`. I blocchi `sql` vanno nel client MySQL. Procedere solo quando il comando precedente termina senza errori. Gli esempi di shell richiedono Bash; installazione e gestione del servizio nativo qui sono specifiche di Ubuntu, non comandi universali per macOS o Windows.

| Punto di partenza | Cosa fare |
|---|---|
| Clone del codice senza dati | Seguire A o B, inclusa acquisizione e trasformazione |
| 22 TSV inglesi e `manifest.json` valido | Selezionare la loro directory, saltare i download e usare `validate`, poi `load` su schema vuoto |
| File SQL completo, incluso il dump migrato | Seguire C2: importazione SQL in schema vuoto, senza `load` |
| Database già popolato | Backup, eventuali migrazioni C3, poi `update --dry-run` e `update`; non ripetere l'inizializzazione |

`raw/` contiene le fonti, `processed/` i 22 TSV e il manifest, MySQL una copia interrogabile dei dati. Servono spazio per tutte queste copie, staging temporaneo e log delle transazioni; il fabbisogno cresce con la selezione. Il clone Git non contiene i dati biologici. Per l'accesso KEGG consultare [provenienza e condizioni delle fonti](data-governance.md).

## A. Python e SQL, senza Docker

### A1. Installare gli strumenti e avviare davvero MySQL

Servono Python 3.11 o successivo, `venv`, `pip`, MySQL Server e i client `mysql`/`mysqldump`. Il progetto usa funzionalità MySQL 8 e la collation `utf8mb4_0900_ai_ci`: MariaDB non è un sostituto verificato. Compose usa MySQL 8.0.44; le verifiche native sono state eseguite con 8.4.11.

Su Ubuntu, se questi componenti non sono già installati:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip mysql-server mysql-client
sudo systemctl enable --now mysql
systemctl status mysql --no-pager
mysql --version
python3 --version
```

| Comando | Cosa fa e perché |
|---|---|
| `apt update` | Aggiorna l'indice dei pacchetti prima dell'installazione |
| `apt install ...` | Installa interprete, ambiente Python e server/client MySQL; il solo client non può ospitare il database |
| `systemctl enable --now mysql` | Avvia il server adesso e lo abilita ai successivi avvii del computer |
| `systemctl status ...` | Deve mostrare `active (running)`; verifica il servizio, non soltanto la presenza del client |
| `mysql --version`, `python3 --version` | Mostrano le versioni installate; più avanti `SELECT VERSION()` controlla il server effettivamente raggiunto |

Se Ubuntu propone una versione diversa da quelle verificate, scegliere MySQL 8.0/8.4 con la [procedura APT ufficiale MySQL](https://dev.mysql.com/doc/mysql-apt-repo-quick-guide/en/). Non installare un secondo server sopra un'installazione esistente senza prima verificarla. La [guida Ubuntu](https://ubuntu.com/server/docs/databases-mysql/) descrive installazione e servizio.

### A2. Installare la CLI nel progetto corretto

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
python -c 'import unikegg; print(unikegg.__file__)'
unikegg --help
```

`venv` isola le dipendenze; `source` seleziona quell'interprete nel terminale corrente. Il primo `pip install` installa le dipendenze dichiarate; il secondo registra UniKegg in modalità modificabile, così la CLI usa i sorgenti di questa directory. `--no-deps` evita una seconda risoluzione delle dipendenze. Il percorso stampato deve appartenere a **questo progetto**, non alla copia `prova_unikegg`. L'help conferma che la CLI è disponibile. In un nuovo terminale riattivare `.venv`; `deactivate` esce dall'ambiente, ma non ferma MySQL.

### A3. Creare database, account applicativo e configurazione server

Per una **nuova installazione**, aprire il client amministrativo:

```bash
sudo mysql
```

Su Ubuntu questo usa normalmente l'autenticazione locale dell'amministratore. Se il proprio server usa una password root, usare invece `mysql -u root -p`; `-p` la richiede senza inserirla nel comando. Non modificare l'autenticazione root per far funzionare la CLI.

Nel prompt MySQL, sostituire la password di esempio con una propria (se contiene un apostrofo, raddoppiarlo nel letterale SQL):

```sql
SELECT VERSION(), @@port, @@local_infile;
CREATE DATABASE UniKegg CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'unikegg'@'127.0.0.1' IDENTIFIED BY 'SOSTITUIRE_CON_PASSWORD_PROPRIA';
GRANT ALL PRIVILEGES ON UniKegg.* TO 'unikegg'@'127.0.0.1';
SET PERSIST local_infile = ON;
SHOW GLOBAL VARIABLES LIKE 'local_infile';
exit
```

| Istruzione | Cosa fa e perché |
|---|---|
| `SELECT VERSION(), ...` | Conferma versione, porta e configurazione del server raggiunto |
| `CREATE DATABASE` | Crea il contenitore vuoto con Unicode e collation coerenti con il progetto |
| `CREATE USER` | Crea l'account usato dalla CLI per la connessione TCP locale a `127.0.0.1` |
| `GRANT ... ON UniKegg.*` | Consente caricamento, staging temporaneo e migrazioni **solo nello schema UniKegg**; non concede privilegi globali né `GRANT OPTION` |
| `SET PERSIST local_infile = ON` | Abilita il caricamento locale dei TSV subito e dopo i riavvii; richiede l'amministratore e modifica un'impostazione del server |
| `SHOW ...` | Deve restituire `ON`; l'abilitazione server è necessaria anche se la CLI configura già il proprio client |
| `exit` | Chiude il client e torna a Bash; il server rimane attivo |

`CREATE DATABASE` e `CREATE USER` sono volutamente senza `IF NOT EXISTS`: se esistono già, fermarsi e verificarli anziché confondere una nuova installazione con una migrazione. I privilegi sullo schema sono sufficienti per l'uso locale documentato; non serve `FILE` globale perché il caricamento usa `LOCAL`. Vedere [MySQL: caricamento locale](https://dev.mysql.com/doc/refman/8.4/en/load-data-local-security.html) e [impostazioni persistenti](https://dev.mysql.com/doc/refman/8.4/en/persisted-system-variables.html).

### A4. Collegare Python al server e inizializzare le tabelle

In Bash:

```bash
export MYSQL_HOST=127.0.0.1
export MYSQL_PORT=3306
export MYSQL_DATABASE=UniKegg
export MYSQL_USER=unikegg
read -r -s -p 'Password dell’account unikegg: ' MYSQL_PASSWORD
export MYSQL_PASSWORD
echo
mysql --protocol=TCP -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p "$MYSQL_DATABASE"
```

Gli `export` rendono la configurazione visibile ai processi Python. `read -s` acquisisce la password senza visualizzarla; deve coincidere con A3. La CLI **non legge `.env`** automaticamente. Il client `mysql` chiede nuovamente la password con `-p`: non usa `MYSQL_PASSWORD`. `--protocol=TCP` e `127.0.0.1` rendono esplicito il collegamento; `-P` maiuscola indica la porta. Qui è `3306`, mentre il default della CLI è `3307` per Compose, quindi va impostata.

Nel client, controllare di essere nel database appena creato:

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

**Eseguire i tre `SOURCE` solo se il primo `SHOW TABLES` è vuoto.** `SOURCE` legge un file dal computer su cui gira il client; i percorsi sono relativi alla radice del progetto. Il file `001` crea le 22 tabelle biologiche con chiavi e vincoli, `002` lo stato dell'ultimo caricamento, `003` lo storico delle versioni. L'ordine evita dipendenze mancanti. Il risultato finale atteso è **24 tabelle**, ancora senza dati. Non eseguire direttamente `db/load/001_ingest.sql`: è un template con percorsi sostituiti dal loader Python.

### A5. Preparare i dati o selezionare un bundle già pronto

Per una nuova acquisizione, usare una directory dedicata e mantenere queste variabili per l'intera sessione:

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

| Comando/impostazione | Cosa fa e perché |
|---|---|
| `UNIKEGG_HOME` | Fissa la radice da cui leggere schema e template SQL |
| `UNIKEGG_DATA_DIR`, `UNIKEGG_PROCESSED_DIR` | Separano questo snapshot da altri dati e selezionano il bundle finale |
| `UNIKEGG_DATASET_KIND=swissprot` | Richiede il contratto dei dati reviewed reali |
| `unset UNIKEGG_REVIEWED_DIR` | Elimina un eventuale override precedente degli export UniProt |
| `list-organisms` | Elenca i 16 organismi supportati e i codici accettati |
| Download con `--dry-run` | Mostrano il piano senza richieste remote né file nuovi |
| Download senza `--dry-run` | Acquisiscono entrambe le fonti e registrano selezione/provenienza; riusano la cache verificata |
| `transform` | Integra raw completati e produce 22 TSV, manifest e rapporto; non usa MySQL |
| `validate` | Controlla checksum, contenuti e riferimenti prima di scrivere nel database |

`hsa,eco` è una selezione esplicita di esempio. Per **tutti i 16 organismi**, sostituire `--organisms hsa,eco` con `--all-organisms` in entrambi i download e nelle rispettive anteprime; UniProt accetta anche `--batch-size 4`. KEGG e UniProt devono coprire la stessa selezione da trasformare. [Blocchi, selezioni cumulative e tutte le opzioni](command-reference.it.md).

Se si possiedono già 22 TSV e un manifest valido, **saltare i download e `transform`**, impostare `UNIKEGG_PROCESSED_DIR` alla directory reale e lanciare soltanto `unikegg validate`. Non puntare la CLI ai TSV di un dump standalone privo di manifest: seguire C2.

### A6. Primo caricamento, verifica e query

```bash
unikegg load --version-label "Primo caricamento"
unikegg verify
unikegg history
mysql --protocol=TCP -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p "$MYSQL_DATABASE"
```

`load` carica lo schema vuoto con una transazione e registra la prima versione; il risultato atteso comprende `action: loaded` e `current_version: 1`. `verify` confronta il database con il bundle, anche nei valori; deve restituire `action: verified`. `history` mostra versioni, date UTC e metadati. Il client finale permette le [query C1](#c1-query-sql-e-risultati-attesi). Un secondo `load` con lo stesso fingerprint verifica i dati; con un bundle diverso bisogna usare `update`.

### A7. Backup, aggiornamenti e riavvio

Prima di aggiornare, sospendere gli altri writer ed esportare un backup:

```bash
mkdir -p artifacts/backups
backup_file="artifacts/backups/unikegg-$(date +%Y%m%d-%H%M%S).sql"
mysqldump --protocol=TCP -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p \
  --single-transaction --no-tablespaces --set-gtid-purged=OFF \
  "$MYSQL_DATABASE" > "$backup_file"
test -s "$backup_file"
```

`mkdir -p` prepara la cartella, la data distingue i backup. `--single-transaction` legge uno snapshot coerente delle tabelle InnoDB; evitare migrazioni DDL concorrenti. `--no-tablespaces` e `--set-gtid-purged=OFF` evitano metadati amministrativi non necessari al ripristino del singolo schema. Controllare **l'esito di `mysqldump`**: `test -s` conferma soltanto che il file non è vuoto, non che sia un backup valido.

Preparare un nuovo snapshot ripetendo A5 con una directory nuova, quindi:

```bash
unikegg update --dry-run
unikegg update --version-label "Aggiornamento dati"
unikegg verify
unikegg history
```

Il dry-run accede a MySQL e confronta aggiunte, modifiche e rimozioni senza cambiare lo stato persistente. Esaminare il piano prima del comando successivo. `update` sincronizza **l'intero bundle**: una selezione ridotta elimina dal database gli organismi esclusi e i relativi dati. Lo storico non conserva una copia delle vecchie righe e non sostituisce il backup. Per nomi italiani o uno schema a 20 tabelle seguire prima C3.

| Comando | Quando serve |
|---|---|
| `sudo systemctl stop mysql` | Ferma il server nativo, compresi eventuali altri database ospitati dallo stesso servizio |
| `sudo systemctl start mysql` | Riavvia il server senza ricreare schema o dati |
| `journalctl -u mysql -n 100 --no-pager` | Mostra gli ultimi messaggi del servizio quando l'avvio fallisce |
| `source .venv/bin/activate` | Ripristina la CLI nel nuovo terminale; ripetere anche gli export di A4/A5 e la lettura della password |

## B. Docker e SQL

### B1. Requisiti e configurazione

Servono Docker Engine o Docker Desktop con container Linux e Compose v2. Python e MySQL vengono installati nelle immagini. Verificare il daemon e preparare `.env`:

```bash
docker --version
docker compose version
docker info
if [ ! -f .env ]; then cp .env.example .env; fi
```

I primi due comandi controllano i client; `docker info` verifica che il daemon sia raggiungibile. La copia condizionale conserva un'eventuale configurazione già presente. Aprire `.env` e impostare database, utente, password applicativa e root. I valori del modello sono soltanto credenziali dimostrative locali. Compose legge `.env`; le variabili già esportate in Bash hanno precedenza. Evitare di ereditare per errore quelle del percorso A.

Per una nuova installazione separata:

```bash
export COMPOSE_PROJECT_NAME=unikegg-docker
export MYSQL_PORT=3307
export UNIKEGG_PROCESSED_DIR="$PWD/data/docker/processed"
export UNIKEGG_DATASET_KIND=swissprot
mkdir -p data/docker/processed data/docker/tmp artifacts
docker compose config --quiet
docker compose build etl
```

`COMPOSE_PROJECT_NAME` identifica rete e volumi: conservarlo in tutte le sessioni. Cambiarlo seleziona un'altra installazione; riusarlo riapre i suoi dati. `MYSQL_PORT` è la porta pubblicata su `127.0.0.1` dell'host; dentro i container MySQL usa sempre `3306`. Le due variabili `UNIKEGG_*` selezionano directory e tipo del bundle. `mkdir` prepara mount realmente esistenti; `config --quiet` controlla la configurazione senza stampare credenziali. `build etl` costruisce l'immagine Python dai sorgenti correnti e va ripetuto dopo modifiche al codice.

### B2. Acquisire e trasformare nei container

Se il bundle inglese con manifest esiste già, impostare `UNIKEGG_PROCESSED_DIR` alla sua directory e passare a B3. Per partire dalle fonti definire questa funzione Bash nella stessa sessione:

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

La configurazione standard di `etl` monta i dati in sola lettura, adatta al caricamento ma non ai download. Questa funzione aggiunge directory scrivibili dedicate. `--rm` rimuove il container del comando dopo l'esecuzione, conservando i file montati; `--no-deps` evita l'avvio di MySQL, inutile in questa fase. `--user` usa UID/GID dell'utente host per creare file accessibili anche dal terminale su Linux. I due `-v` montano dati e report; gli `-e` selezionano i percorsi **interni** al container. `TMPDIR` colloca lo staging su disco anziché nel piccolo `/tmp` in memoria. `"$@"` inoltra alla CLI tutti gli argomenti della funzione. Vedere il [riferimento ufficiale di `compose run`](https://docs.docker.com/reference/cli/docker/compose/run/).

`list-organisms` mostra i codici; i dry-run mostrano il piano; i download acquisiscono le due fonti; `transform` le integra e `validate` controlla il bundle. I risultati host sono in `data/docker/raw`, `data/docker/processed` e `artifacts`. Per tutti i 16 organismi sostituire `--organisms hsa,eco` con `--all-organisms` in entrambi i download e nelle anteprime. Per dettagli, [riferimento](command-reference.it.md). Non usare `ukdata` per `load`/`update`: questi richiedono il collegamento MySQL normale di B3.

### B3. Avviare il database, caricare e aprire SQL

```bash
docker compose run --rm --no-deps etl validate
docker compose up -d --wait mysql
docker compose ps -a
docker compose run --rm etl load --version-label "Primo caricamento Docker"
docker compose run --rm etl verify
docker compose run --rm etl history
docker compose exec mysql sh -c 'exec mysql -u"$MYSQL_USER" -p "$MYSQL_DATABASE"'
```

| Comando | Cosa fa e perché |
|---|---|
| `run --rm --no-deps etl validate` | Valida il bundle montato senza avviare il database |
| `up -d --wait mysql` | Avvia MySQL in background e attende il controllo di disponibilità |
| `ps -a` | Mostra stato e salute dei servizi |
| `run --rm etl load` | Esegue il primo caricamento usando credenziali e rete Compose |
| `run --rm etl verify` | Confronta tutti i dati con il bundle; deve riportare `verified` |
| `run --rm etl history` | Mostra le versioni applicate |
| `exec mysql ...` | Apre il client nel container MySQL; `-p` richiede la password applicativa di `.env` |

**Alla prima creazione del volume vuoto**, l'immagine MySQL crea database/account dalle variabili e importa in ordine `db/init/001_schema.sql`, `002_load_state.sql` e `003_dataset_history.sql`. Sono 22 tabelle biologiche più 2 operative. Il comando del servizio abilita già `local_infile`; non occorre eseguire A3/A4. Con un volume esistente gli script di inizializzazione non vengono rieseguiti: usare le migrazioni C3. Modificare la password in `.env` non cambia quella già memorizzata nel database.

Dal prompt eseguire le query C1. Nel container il file di query è `/queries/integration.sql`. L'hostname `mysql` è interno a Compose; un client sul computer host usa `127.0.0.1:3307` (o la porta scelta).

### B4. Backup e aggiornamento

Con gli altri writer sospesi:

```bash
mkdir -p artifacts/backups
backup_file="artifacts/backups/unikegg-docker-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T mysql sh -c \
  'MYSQL_PWD="$MYSQL_PASSWORD" exec mysqldump -u"$MYSQL_USER" --single-transaction --no-tablespaces --set-gtid-purged=OFF "$MYSQL_DATABASE"' \
  > "$backup_file"
test -s "$backup_file"
```

Il dump viene salvato sull'host dal reindirizzamento `>`. `-T` disabilita lo pseudo-terminale per ottenere un file SQL pulito. `MYSQL_PWD` usa la password già configurata nel container; non occorre scriverla nel comando. Le opzioni di `mysqldump` hanno lo stesso significato di A7. Verificare che il comando termini con successo; un file non vuoto potrebbe comunque essere incompleto.

Preparare un nuovo snapshot completo in una directory distinta. Per acquisirlo con `ukdata`, modificare il mount host `data/docker` in quella nuova directory, crearne `processed` e `tmp`, e impostare `UNIKEGG_PROCESSED_DIR` al nuovo `processed` host. I percorsi interni `/workspace-data/...` restano gli stessi. Quindi:

```bash
docker compose build etl
docker compose run --rm etl validate
docker compose run --rm etl update --dry-run
docker compose run --rm etl update --version-label "Aggiornamento dati Docker"
docker compose run --rm etl verify
docker compose run --rm etl history
```

`build` aggiorna il codice dell'immagine; `validate` controlla il nuovo bundle; il dry-run mostra il confronto. Leggere le rimozioni prima di applicare `update`, che sincronizza l'intero dataset. Verifica e storico confermano il risultato. Conservare il medesimo `COMPOSE_PROJECT_NAME`, database e porta per aggiornare l'installazione scelta.

### B5. Fermare e riprendere

| Comando | Cosa fa e perché |
|---|---|
| `docker compose logs --tail 100 mysql` | Mostra gli ultimi log del server per diagnosi |
| `docker compose stop` | Ferma i servizi conservando container e volumi |
| `docker compose up -d --wait mysql` | Riprende MySQL sul volume esistente |
| `docker compose down` | Rimuove container e rete, mantenendo i volumi nominati |

Non aggiungere `--volumes` a `down` per un normale arresto: eliminerebbe il volume del database. In un nuovo terminale ripetere gli export di B1; ridefinire `ukdata` solo se serve acquisire o trasformare. `docker compose up --build -d` avvia anche il servizio ETL con il comando predefinito `load`: usarlo solo con un bundle già pronto e uno schema compatibile. I passaggi espliciti B3 rendono separatamente visibili validazione, avvio e caricamento.

## C. Query, dump esistenti, migrazioni e controlli

### C1. Query SQL e risultati attesi

Aprire il client come in A6 o B3, quindi:

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

Le prime istruzioni identificano server/schema e tabelle; i conteggi verificano la selezione caricata. Con `hsa,eco` ci si aspetta 2 organismi, con tutti i codici 16. Il numero di proteine dipende dalle fonti. `invalid_sequence_lengths` deve essere 0; il raggruppamento mostra la distribuzione per organismo, includendo quelli senza proteine. L'ultima query legge la versione ETL: non è applicabile a un dump standalone senza tabelle operative.

Per eseguire le trenta query di integrazione, usare **uno** dei seguenti comandi nel client:

```sql
-- Client locale aperto dalla radice del progetto:
SOURCE db/queries/integration.sql;
```

```sql
-- Client nel container MySQL:
SOURCE /queries/integration.sql;
```

`SOURCE` esegue tutto il file di interrogazioni; `exit` chiude soltanto il client.

### C2. Importare un dump SQL completo già esistente

Un dump SQL contiene istruzioni per creare e popolare tabelle. Non è un bundle ETL: **non eseguire `load`, `manifest` o i tre `db/init` per importarlo**. Il pacchetto migrato dell'8 ottobre, disponibile localmente sotto `artifacts/legacy-dump-english-2026-10-08-verified/`, contiene 22 tabelle biologiche, senza manifest Swiss-Prot e senza storico ETL. I suoi TSV da soli non autorizzano a inventare una provenienza reviewed.

Verificare i checksum dalla directory del pacchetto:

```bash
(cd artifacts/legacy-dump-english-2026-10-08-verified && sha256sum -c SHA256SUMS)
```

Le parentesi cambiano directory soltanto per quel comando. Se si usa un altro dump, seguire il suo inventario e le istruzioni incluse. Il pacchetto locale non è distribuito da Git.

**MySQL nativo:** dopo A1 aprire `sudo mysql` (oppure `mysql -u root -p`) e creare uno schema separato:

```sql
CREATE DATABASE UniKeggImported CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
exit
```

Poi, su Ubuntu con autenticazione amministrativa socket:

```bash
sudo mysql UniKeggImported < artifacts/legacy-dump-english-2026-10-08-verified/unikegg_updated.sql
sudo mysql UniKeggImported
```

Se root usa password, sostituire `sudo mysql` con `mysql -u root -p`. La redirezione `<` invia il dump al client; il secondo comando apre lo schema importato per le query C1, esclusa quella sullo stato ETL.

**Docker:** dopo B1 e `docker compose up -d --wait mysql`, aprire un client root:

```bash
docker compose exec mysql mysql -uroot -p
```

Inserire la password root di `.env` e creare lo schema separato con lo stesso `CREATE DATABASE UniKeggImported ...` sopra. Quindi in Bash:

```bash
docker compose exec -T mysql sh -c \
  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot UniKeggImported' \
  < artifacts/legacy-dump-english-2026-10-08-verified/unikegg_updated.sql
docker compose exec mysql mysql -uroot -p UniKeggImported
```

Si sceglie uno schema separato perché Compose ha già inizializzato `UniKegg`; un dump completo va invece importato in uno schema **vuoto**. Non serve montare il dump nel container: lo trasmette stdin con `-T`. Questi comandi non assegnano automaticamente al normale account applicativo l'accesso a `UniKeggImported`; le query di verifica qui usano l'amministratore.

### C3. Database e file con nomi italiani o schema a 20 tabelle

Conservare prima un backup A7/B4 e sospendere gli altri writer. La [guida italiana alla migrazione dei nomi](english-names-migration.it.md) e la [migrazione KO](orthology-migration.it.md) spiegano le precondizioni. Non rieseguire `001_schema.sql` su un database popolato.

Per un bundle precedente completo con 22 TSV e manifest, dal percorso Python:

```bash
python tools/migrate_dataset_names.py --source data/processed --output data/processed-english
export UNIKEGG_PROCESSED_DIR="$PWD/data/processed-english"
unikegg validate
python tools/migrate_database_names.py
python tools/migrate_database_names.py --apply
```

Il primo comando verifica i checksum e crea un bundle separato con nomi inglesi; la destinazione deve essere nuova. I due comandi database mostrano e poi applicano la rinomina delle tabelle usando la connessione A4. Il piano va controllato prima di `--apply`; la rinomina DDL non si annulla con un rollback ETL. Un bundle a 20 TSV richiede rigenerazione dalle fonti complete, non solo rinomina.

Nel percorso **Docker**, gli strumenti `tools/` non sono inclusi nell'immagine. Per eseguire il piano e applicarlo montare esplicitamente la directory:

```bash
docker compose run --rm -v "$PWD/tools:/app/tools:ro" --entrypoint python etl tools/migrate_database_names.py
docker compose run --rm -v "$PWD/tools:/app/tools:ro" --entrypoint python etl tools/migrate_database_names.py --apply
```

`--entrypoint python` sostituisce la CLI predefinita per eseguire lo script; rete e credenziali restano quelle del servizio ETL. Per convertire il bundle con Docker:

```bash
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD/tools:/app/tools:ro" -v "$PWD/data:/migration-data" \
  --entrypoint python etl tools/migrate_dataset_names.py \
  --source /migration-data/processed --output /migration-data/processed-english
export UNIKEGG_PROCESSED_DIR="$PWD/data/processed-english"
docker compose run --rm --no-deps etl validate
```

Adattare il mount `data` alla cartella dei propri bundle. Gli input e output dello script sono percorsi interni al container, mentre l'export successivo è il percorso host.

Se il database precedente aveva **20 tabelle biologiche**, dopo la rinomina aggiungere i collegamenti KO con una delle due alternative:

```bash
# MySQL nativo, connessione A4:
mysql --protocol=TCP -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p "$MYSQL_DATABASE" < db/migrations/004_orthology_links.sql
```

```bash
# MySQL Docker:
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -u"$MYSQL_USER" "$MYSQL_DATABASE"' < db/migrations/004_orthology_links.sql
```

Questa migrazione crea le due tabelle mancanti, non ne popola i dati. Dopo avere validato il bundle inglese completo, seguire `update --dry-run`, `update`, `verify`, `history` di A7 o B4. Per la sola rinomina, il piano deve mostrare zero differenze biologiche. Il vecchio dump con nomi minuscoli e colonne GO mancanti richiede invece lo strumento legacy e la procedura dedicata della guida KO.

### C4. Prova senza download e verifiche del codice

Nel percorso Python, si può generare un bundle **sintetico** per provare l'infrastruttura:

```bash
python tests/make_fixture.py --edge-cases --legacy-quoting
export UNIKEGG_PROCESSED_DIR="$PWD/tests/fixtures/processed"
export UNIKEGG_DATASET_KIND=synthetic
unikegg validate
```

Il generatore crea record inventati, inclusi casi limite di quoting. Scegliere uno schema MySQL nuovo e separato, ad esempio `UniKeggSynthetic`, riprendendo A3/A4 con quel nome, prima di `load`. Se si riusa l’account `unikegg` già creato, saltare `CREATE USER` e concedergli i privilegi anche sul nuovo schema con `GRANT ALL PRIVILEGES ON UniKeggSynthetic.* TO 'unikegg'@'127.0.0.1';`. Non applicare questi dati a un database biologico.

Per generarli senza Python host, dopo B1:

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

Il mount rende visibile il generatore e conserva i file sull'host. `build etl` prepara l’immagine per il nuovo nome Compose. Nome Compose e porta distinti separano la prova dall'installazione reale; continuare con B3. Alla fine ripristinare gli export dell'installazione che si intende usare.

I controlli di sviluppo, nella `.venv` A2, sono:

```bash
python -m pip install -r requirements-dev.txt
ruff check src tests tools
sqlfluff lint db --dialect mysql
python tools/lint_ingest.py
pytest -q
```

L'installazione aggiunge gli strumenti di sviluppo. Ruff controlla Python; SQLFluff controlla lo stile SQL; `lint_ingest.py` verifica separatamente le proiezioni del template `LOAD DATA`; pytest esegue i test unitari e di regressione. Non scaricano dati reali. Le prove MySQL complete richiedono un database usa e getta dedicato: vedere [operations.md](operations.md) e il [workflow CI](../.github/workflows/ci.yml).

Per opzioni, ripresa dei download, manifest e diagnosi dettagliate consultare il [riferimento dei comandi](command-reference.it.md). In particolare: connessione rifiutata → verificare servizio e porta; `MYSQL_PASSWORD` mancante → ripetere A4; `local_infile` disabilitato → A3; tabelle assenti → A4 o log di inizializzazione B3; manifest mancante → distinguere bundle e dump prima di procedere.
