# Riferimento dei comandi UniKegg

[Guida di avvio: Python e SQL oppure Docker e SQL](command-guide.it.md) · [English](command-reference.md).

Consultare questo riferimento per opzioni, selezioni, percorsi e diagnosi; seguire la guida di avvio per installazione e database. Gli esempi `unikegg` usano la CLI locale; nel percorso Docker usare `ukdata` per acquisizione/trasformazione e `docker compose run --rm etl` per le operazioni sul database.

## 1. Scaricare singoli organismi, gruppi e blocchi

Gli esempi di questa sezione sono modalità alternative di acquisizione. I percorsi di output sono quelli configurati nella guida di avvio.

### 1.1 Un organismo o un gruppo manuale

```bash
# Solo Homo sapiens:
unikegg download-uniprot --organisms hsa

# Un gruppo preciso:
unikegg download-uniprot --organisms hsa,mmu,eco

# Gli stessi organismi in KEGG, se si vuole poi trasformare:
unikegg download-kegg --organisms hsa,mmu,eco
unikegg transform
unikegg validate
```

Usare i codici del catalogo, separati da virgole. Codici sconosciuti, vuoti o duplicati vengono rifiutati. L'ordine effettivo segue il catalogo anche se l'elenco è scritto in ordine diverso.

### 1.2 Tutti gli organismi o i primi N

```bash
# Tutti i 16, senza raggruppamento esplicito:
unikegg download-uniprot --all-organisms

# I primi 12 nell'ordine del catalogo:
unikegg download-uniprot --limit 12

# Tutti i 16, in blocchi consecutivi da 3: l'ultimo contiene un organismo.
unikegg download-uniprot --all-organisms --batch-size 3
```

`--limit 12` significa dodici **organismi**, non dodici proteine. Il download acquisisce tutte le proteine reviewed restituite per ciascun taxid selezionato.

### 1.3 Un blocco per sessione, accumulando tutti i sedici

Nella stessa directory dati, eseguire i comandi in ordine, anche in giornate/sessioni diverse:

```bash
unikegg download-uniprot --all-organisms --batch-size 4 --batch 1 --append
unikegg download-uniprot --all-organisms --batch-size 4 --batch 2 --append
unikegg download-uniprot --all-organisms --batch-size 4 --batch 3 --append
unikegg download-uniprot --all-organisms --batch-size 4 --batch 4 --append
```

`--batch` è numerato da 1. `--append` unisce il blocco alla selezione già registrata e ricontrolla i file precedenti, riutilizzandoli quando sono validi. Funziona anche quando non esiste ancora una selezione. Partendo da una directory nuova, le selezioni completate contengono rispettivamente 4, 8, 12 e 16 organismi.

Il comando può mostrare anche gli organismi precedenti come `Retained UniProt organisms`: sono inclusi nella verifica della selezione cumulativa. Senza `--append` il manifest rappresenta soltanto l'ultima selezione richiesta; gli altri file restano sul disco ma non sono inclusi automaticamente nella selezione disponibile alla trasformazione.

Il numero di blocco si riferisce sempre alla selezione indicata: con `--limit 8 --batch-size 4` esistono due blocchi, mentre con `--all-organisms --batch-size 4` ne esistono quattro.

### 1.4 Aggiungere gruppi scelti a mano

```bash
unikegg download-uniprot --organisms hsa,mmu
unikegg download-uniprot --organisms eco,spo --append
```

Al termine la selezione contiene `hsa,mmu,eco,spo`. Per ottenere il dataset integrato corrispondente:

```bash
unikegg download-kegg --organisms hsa,mmu,eco,spo
unikegg transform
unikegg validate
```

KEGG non accetta `--append`: richiedere l'intera selezione finale, lasciando al client il riuso della cache verificata.

### 1.5 Conservare anche il JSON originale

```bash
unikegg download-uniprot --organisms hsa,spo --include-json
```

Il TSV gzip è sempre acquisito; il JSON gzip è aggiuntivo. La trasformazione usa soltanto il TSV. Le pagine TSV sono riprendibili; un JSON interrotto riparte dall'inizio di quel file. Con `--append`, `--include-json` si applica anche agli organismi già selezionati.

### 1.6 Trasformare soltanto una parte di fonti complete

Dopo aver acquisito entrambe le fonti per una selezione più ampia:

```bash
unikegg transform --organisms hsa,eco
unikegg validate
```

Il nuovo bundle processed contiene solo il sottoinsieme richiesto e sostituisce quello precedente nella directory di destinazione. Per conservarli entrambi impostare prima un'altra `UNIKEGG_PROCESSED_DIR`. Applicare questo bundle con `update` restringerebbe anche il database a quel sottoinsieme.


## 2. Riferimento di tutti i comandi UniKegg

| Comando | Input principale | Risultato | Rete/database |
|---|---|---|---|
| `list-organisms` | Catalogo incluso nel codice | Elenco filtrabile con codici e taxid | Nessuno |
| `download-uniprot` | Selezione organismi | Export reviewed e metadati raw | UniProt, salvo dry-run/cache |
| `download-kegg` | Selezione organismi | Export KEGG e metadati raw | KEGG, salvo dry-run/cache |
| `transform` | Raw UniProt e KEGG | Venti TSV elaborati, manifest e report | Nessuno |
| `validate` | Bundle processed e manifest | Controlli di integrità | Nessuno |
| `load` | Bundle processed e schema MySQL | Primo caricamento/versione | MySQL |
| `update` | Bundle processed e database caricato | Sincronizzazione e nuova versione | MySQL |
| `verify` | Bundle processed e database caricato | Confronto completo | MySQL |
| `history` | Metadati nel database | Storico JSON | MySQL |
| `manifest` | Venti TSV ed export reviewed | Manifest rigenerato e validazione | Nessuno |

### 2.1 `list-organisms`

```bash
unikegg list-organisms
unikegg list-organisms --search pombe
unikegg list-organisms --organisms hsa,eco
unikegg list-organisms --limit 4
```

La ricerca filtra per codice o nome scientifico senza distinguere maiuscole/minuscole. I taxid sono mostrati nell'output, ma `--search` non è una ricerca per taxid.

### 2.2 `download-uniprot`

```bash
unikegg download-uniprot --all-organisms --batch-size 4
unikegg download-uniprot --organisms hsa --interval 1.5 --attempts 8
```

Scarica solo reviewed. Verifica pagine, organismi, checksum e coerenza delle release. Le opzioni per selezioni cumulative, blocchi e JSON sono spiegate nella sezione 1. Il riuso di una cache verificata non controlla se sul server esistono dati più recenti: per acquisirli usare `--refresh` o una directory nuova.

### 2.3 `download-kegg`

```bash
unikegg download-kegg --all-organisms
unikegg download-kegg --organisms hsa,eco --interval 1.5 --attempts 8
```

Acquisisce gli organismi selezionati, i geni e i dati KEGG richiesti dalla trasformazione. I batch interni delle richieste di dettagli sono gestiti automaticamente. `--batch-size`, `--batch`, `--append` e `--include-json` non sono opzioni KEGG.

### 2.4 `transform`

```bash
unikegg transform
unikegg transform --organisms hsa,eco
unikegg transform --reviewed-export /percorso/export-uniprot
```

L'ultimo percorso è un esempio da sostituire con una directory reale. `--reviewed-export` seleziona una **directory**, non un singolo `.tsv.gz`. La sorgente KEGG resta quella della directory dati configurata.

Senza selezione esplicita usa il manifest KEGG completato; per export legacy senza selezione registrata usa tutti i 16 organismi predefiniti. Il report delle associazioni gene/proteina viene scritto nella directory artifacts come `report_gene_protein.tsv`.

### 2.5 `validate`

```bash
unikegg validate
```

Controlla il manifest, i checksum, il formato TSV, le chiavi, i riferimenti, i vincoli dei valori e la coerenza delle sequenze. Usa la selezione registrata nel bundle. Non modifica il database e non accetta `--dry-run` né opzioni di selezione.

### 2.6 `load`

Con le variabili MySQL locali configurate come nella sezione 4.2:

```bash
unikegg load --version-label "Prima versione"
```

In alternativa usare `docker compose run --rm etl load --version-label "Prima versione"`. Richiede lo schema inizializzato; non crea autonomamente il database o le ventidue tabelle biologiche. Il primo caricamento richiede tabelle vuote. Lo stesso fingerprint già caricato viene verificato, un fingerprint differente viene rifiutato con l'indicazione di usare `update`.

### 2.7 `update`

```bash
unikegg update --dry-run
unikegg update --version-label "Nuovo snapshot"
```

Richiede una precedente versione caricata. Il comando sincronizza tutto il bundle e può rimuovere record. L'etichetta è facoltativa e deve contenere da 1 a 128 caratteri. Non scarica o trasforma le fonti: questi passaggi precedono l'aggiornamento.

### 2.8 `verify`

```bash
unikegg verify
```

Richiede il bundle processed corrispondente al database. Confronta fingerprint, conteggi, riferimenti e valori delle colonne tramite tabelle temporanee; non modifica i dati persistenti. `validate` controlla i file, `verify` controlla anche la loro corrispondenza al database.

### 2.9 `history`

```bash
unikegg history
```

Restituisce JSON con `current_version` e l'elenco `versions`: versione, data `applied_at`, operazione, etichetta, fingerprint, modifiche e indicatore `current`. Accede a MySQL e funziona anche senza il bundle processed locale. Non accetta filtri per organismo.

### 2.10 `manifest`

Da usare quando i ventidue TSV esistono già e si possiede l'export reviewed di riferimento:

```bash
unikegg manifest --reviewed-export data/raw/uniprot
unikegg validate
```

Il comando ricostruisce `manifest.json` confrontando le accession elaborate con l'export reviewed e poi valida il dataset. Ricava gli organismi dalla tabella elaborata `ORGANISM`; una selezione esplicita deve coincidere con quella tabella. Non crea i TSV mancanti e non rende valido un dataset con record non reviewed. Nel percorso normale, `transform` genera già il manifest e questo comando non serve.

## 3. Riferimento di tutte le opzioni

Per l'help integrato usare `unikegg --help` oppure `unikegg -h`. La CLI usa un parser unico: anche `unikegg download-uniprot --help` mostra l'help generale. La tabella specifica le combinazioni supportate.

| Opzione | Comandi che la accettano | Significato ed esempio |
|---|---|---|
| `-h`, `--help` | Tutti | Mostra l'help e termina |
| `--organisms CODICI` | `list-organisms`, entrambi i download, `transform`, `manifest` | Elenco di codici distinti: `--organisms hsa,eco,spo` |
| `--limit N` | Gli stessi della selezione esplicita | Primi N organismi del catalogo; da 1 a 16 |
| `--all-organisms` | Gli stessi della selezione esplicita | Tutti i 16 del catalogo curato |
| `--search TESTO` | `list-organisms` | Filtra codice o nome scientifico: `--search pombe` |
| `--dry-run` | Entrambi i download, `update` | Anteprima senza acquisizione per i download; confronto MySQL senza modifiche persistenti per `update` |
| `--refresh` | Entrambi i download | Riacquisisce gli export; UniProt ricomincia i checkpoint |
| `--include-json` | `download-uniprot` | Aggiunge JSON gzip ai TSV gzip |
| `--batch-size N` | `download-uniprot` | Gruppi da N organismi; da 1 a 16 |
| `--batch N` | `download-uniprot` | Solo il blocco N della selezione; da 1 al numero di blocchi, richiede `--batch-size` |
| `--append` | `download-uniprot` | Unisce la selezione richiesta a quella precedente nella stessa directory |
| `--interval SECONDI` | Entrambi i download | Pausa minima per richiesta; default `1.0`, intervallo `0.34`–`3600` |
| `--attempts N` | Entrambi i download | Tentativi totali per richiesta; default `4`, da 1 a 20 |
| `--reviewed-export DIRECTORY` | `transform`, `manifest` | Directory degli export reviewed da leggere |
| `--version-label TESTO` | `load`, `update` | Etichetta della versione applicata; da 1 a 128 caratteri |

`--organisms`, `--limit` e `--all-organisms` si escludono a vicenda. Le opzioni di selezione su `manifest` verificano la corrispondenza con le tabelle esistenti, non filtrano i TSV. `load`, `update`, `validate` e `verify` rispettano sempre il perimetro già registrato nel manifest processed.

Con `--append --refresh`, UniProt aggiorna **tutta la selezione cumulativa**, inclusi gli organismi precedenti. Per riprendere un refresh interrotto, ripetere il comando senza `--refresh`: il programma conserva lo stato necessario per completare l'aggiornamento iniziato.

Le opzioni non supportate da un comando vengono rifiutate. Per esempio, `unikegg validate --dry-run` e `unikegg download-kegg --append` sono errori di utilizzo, non anteprime valide.

## 4. Directory e variabili di ambiente

### 4.1 File locali

| Variabile | Default nella CLI locale | Utilizzo |
|---|---|---|
| `UNIKEGG_HOME` | Directory corrente | Radice del progetto, contenente anche `db/` |
| `UNIKEGG_DATA_DIR` | `UNIKEGG_HOME/data` | Radice delle sorgenti `raw/` e, se non ridefinita, di `processed/` |
| `UNIKEGG_PROCESSED_DIR` | `UNIKEGG_DATA_DIR/processed` | Directory dei ventidue TSV e del manifest |
| `UNIKEGG_REVIEWED_DIR` | `UNIKEGG_DATA_DIR/raw/uniprot` | Export letti da trasformazione/manifest; non cambia la destinazione del downloader |
| `UNIKEGG_ARTIFACTS_DIR` | `UNIKEGG_HOME/artifacts` | Report generati dalla trasformazione |
| `UNIKEGG_DATASET_KIND` | `swissprot` | Tipo atteso da validazione e operazioni sul DB; `synthetic` solo per le fixture |
| `TMPDIR` | Directory temporanea del sistema | Area di lavoro per copie temporanee e ordinamento |

Un'opzione `--reviewed-export` esplicita prevale su `UNIKEGG_REVIEWED_DIR`. `UNIKEGG_PROCESSED_DIR`, se impostata, prevale sulla directory processed derivata da `UNIKEGG_DATA_DIR`: ricordarlo quando si passa a un altro snapshot.

Struttura essenziale nella directory dati:

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
  ... ventidue file TSV ...
```

`selection.json` descrive la selezione e il suo completamento; `manifest.jsonl` conserva la provenienza degli export; il `manifest.json` processed identifica il bundle da caricare. Pagine e batch raw restano disponibili per la ripresa e occupano spazio oltre ai file finali.

### 4.2 Connessione MySQL dalla CLI locale

La CLI locale richiede `MYSQL_PASSWORD`; gli altri parametri hanno i default indicati qui:

```bash
export MYSQL_HOST=127.0.0.1
export MYSQL_PORT=3307
export MYSQL_DATABASE=UniKegg
export MYSQL_USER=unikegg
read -r -s -p 'Password MySQL applicativa: ' MYSQL_PASSWORD
export MYSQL_PASSWORD
echo

unikegg history
```

Usare la password dell'utente applicativo configurata nel server, non necessariamente quella root. Per MySQL nativo usare `3306`; per Compose usare la porta pubblicata, normalmente `3307`. Il valore host predefinito del codice è `localhost`; qui è esplicitata la connessione TCP a `127.0.0.1`.

Per MySQL installato autonomamente occorre predisporre database, utente e schema con i file `db/init/001_schema.sql`, `002_load_state.sql` e `003_dataset_history.sql`, nell'ordine. Il server deve consentire `LOCAL INFILE` e l'utente deve poter operare sulle tabelle e creare tabelle temporanee. La configurazione Compose fornita esegue l'inizializzazione dello schema quando crea il volume vuoto.

### 4.3 Variabili Compose e percorsi nel container

| Impostazione | Comportamento |
|---|---|
| `COMPOSE_PROJECT_NAME` | Separa nomi e volumi delle installazioni; default del progetto `unikegg` |
| `MYSQL_PORT` | Porta sul computer host; dentro i container MySQL resta sulla `3306` |
| `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD` | Configurazione iniziale del servizio MySQL; l'ETL riceve solo le credenziali applicative |
| `UNIKEGG_PROCESSED_DIR` | Percorso sul computer host da montare in `/data/processed` |
| `UNIKEGG_DATASET_KIND` | Tipo di dataset atteso dal servizio ETL |

Le variabili esportate nel terminale prevalgono sui valori corrispondenti di `.env`. La configurazione ETL imposta internamente `MYSQL_HOST=mysql` e `MYSQL_PORT=3306`; non usare l'hostname `mysql` nella CLI eseguita sul computer host.

`UNIKEGG_DATA_DIR` non riconfigura automaticamente i volumi Compose: per il caricamento indicare `UNIKEGG_PROCESSED_DIR`. Il mount raw predefinito resta `./data/raw`, ma `load`, `update` e `verify` usano il bundle processed. I mount di dati e il filesystem ETL sono in sola lettura; il volume `etl_tmp` fornisce l'area temporanea scrivibile `/app/tmp`.

Cambiare le password in `.env` dopo l'inizializzazione non cambia le credenziali memorizzate nel volume MySQL esistente.


## 5. Interruzioni ed errori frequenti

### 5.1 Riprendere un download interrotto

Ripetere lo stesso comando nella stessa directory dati, mantenendo selezione, blocco, `--append` e formato. Se il comando iniziale aveva `--refresh`, ometterlo nella ripresa.

```bash
# Esempio: riprendere il blocco 2 di una selezione cumulativa.
unikegg download-uniprot --all-organisms --batch-size 4 --batch 2 --append

# Esempio: riprendere KEGG per tutti i sedici.
unikegg download-kegg --all-organisms
```

Le pagine TSV verificate e i file completati vengono riusati. Non aggiungere un nuovo blocco con `--append` mentre il precedente è incompleto. Non modificare manualmente `selection.json` per marcarlo completo.

### 5.2 La release UniProt è cambiata

L'errore `Mixed UniProt releases` indica che i gruppi appartengono a release diverse. Per riacquisire tutti i sedici:

```bash
unikegg download-uniprot --all-organisms --batch-size 4 --refresh
```

Se si vuole aggiornare soltanto la selezione cumulativa già iniziata, ripetere il comando del gruppo interessato aggiungendo `--refresh`, per esempio:

```bash
unikegg download-uniprot --organisms eco,spo --append --refresh
```

In questo secondo esempio vengono aggiornati anche gli organismi precedentemente accumulati. Se l'aggiornamento si interrompe, riprenderlo senza `--refresh`.

### 5.3 Tabella di diagnosi

| Messaggio o sintomo | Cosa controllare/fare |
|---|---|
| `unikegg: command not found` | Attivare `.venv` e verificare l'installazione con `python -m pip install --no-deps -e .` |
| `Expected distinct codes from list-organisms` | Usare codici del catalogo, senza duplicati o elementi vuoti |
| `--batch requires --batch-size` | Specificare entrambe le opzioni; la numerazione parte da 1 |
| `Incomplete acquisition` | Riprendere il download della fonte indicata prima di trasformare |
| `resume the same selection and formats` | Ripetere il gruppo interrotto con le stesse opzioni di selezione, append e JSON |
| `UniProt acquisition does not cover selected organisms` | Completare UniProt per tutta la selezione KEGG, usando `--append` dove necessario, oppure trasformare un sottoinsieme completo |
| `Missing/duplicate selected UniProt exports` | Verificare che la selezione contenga un solo export per organismo; riprendere l'acquisizione se mancano file |
| `Duplicate UniProt exports` | Sono presenti sia il nome corrente sia quello legacy `.index.tsv.gz`; conservare uno snapshot coerente, eventualmente acquisendo in una nuova directory |
| HTTP `429` o errori temporanei | Lasciare agire i retry e il cooldown; aumentare `--interval` e, se necessario, `--attempts` |
| HTTP `400` o `404` | Sono errori permanenti per il client; controllare richiesta/configurazione invece di ripetere senza modifiche |
| `Acquisition already running` | Attendere la fine del downloader/trasformatore che usa quella sorgente; il file del lock può esistere anche quando il lock non è attivo |
| `Transformation lock exists` | Verificare che non ci sia un writer attivo e seguire il recupero descritto in [operations.md](operations.md), ispezionando eventuali backup prima di rimuovere un lock residuo |
| `Output directory contains unrelated files` | Scegliere una destinazione processed dedicata ai ventidue TSV e al manifest |
| `Checksum mismatch`, chiavi duplicate o riferimenti mancanti | Controllare la coerenza dello snapshot e rigenerare dal raw corretto; rigenerare solo il manifest non corregge i dati |
| File processed o manifest non trovati | Verificare `UNIKEGG_PROCESSED_DIR`; eseguire `transform` o fornire il bundle completo |
| `KeyError: MYSQL_PASSWORD` nella CLI locale | Esportare la password come nella sezione 4.2; `.env` non viene caricato dalla CLI |
| Connessione MySQL rifiutata | Controllare `systemctl status mysql` per MySQL nativo oppure `docker compose ps -a` per Docker, quindi i log, host e porta; dal computer host usare la porta pubblicata |
| `Access denied` | Controllare credenziali effettive del volume; cambiare `.env` non modifica gli utenti già creati |
| `Dataset has not been committed` | Eseguire `load` sul database inizializzato prima di `verify` o `update` |
| `The database contains a different dataset` | Per applicare il nuovo bundle usare `update --dry-run`, poi `update`; per verificare il vecchio ripristinare il percorso al bundle corrispondente |
| `Nonempty database without load state` | Il database contiene dati senza stato di caricamento riconosciuto; usare un database/progetto vuoto o esaminare quello esistente |
| `Cannot update between synthetic and Swiss-Prot datasets` | Verificare progetto Compose e tipo di dataset; mantenere separati demo sintetico e dati reali |
| `This dataset is a historical version` | È uno snapshot già applicato in passato; non può essere ripresentato come nuovo aggiornamento |
| `Another ingestion owns the load lock` | Attendere il caricamento/aggiornamento già in corso sul database |
| Spazio insufficiente durante load/update/verify | Controllare directory temporanea, volume `etl_tmp` e spazio MySQL; anche il confronto richiede copie e tabelle temporanee |

Per i dettagli sul formato delle tabelle vedere [schema.md](schema.md); per sorgenti, checkpoint e catalogo vedere [acquisition.md](acquisition.it.md); per sincronizzazione e versioni vedere [updates.md](updates.it.md).
