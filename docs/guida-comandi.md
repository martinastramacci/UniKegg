# Guida pratica a UniKegg: tutti i comandi, passo per passo

Questa guida accompagna dall'installazione al database interrogabile, con esempi per i 16 organismi disponibili. I comandi sono riferiti alla CLI presente nel progetto. Gli esempi di terminale usano Bash su Linux/macOS e vanno eseguiti dalla directory principale di UniKegg, quella che contiene `pyproject.toml` e `docker-compose.yml`.

I blocchi dei diversi percorsi sono **alternative**: scegliere quello adatto al proprio punto di partenza. Eseguire ogni passaggio successivo solo se il precedente termina senza errori.

Per aggiornare uno snapshot o un database precedente a 20 tabelle, seguire prima la [migrazione KO, download e rigenerazione dei TSV](orthology-migration.md). Il contratto attuale richiede anche `ortologia_pathway.tsv` e `ortologia_ec.tsv`.

## Indice

1. [Scegliere il percorso](#1-scegliere-il-percorso)
2. [Installare e configurare](#2-installare-e-configurare)
3. [Percorso completo: dai download ai 16 organismi nel database](#3-percorso-completo-dai-download-ai-16-organismi-nel-database)
4. [Scaricare singoli organismi, gruppi e blocchi](#4-scaricare-singoli-organismi-gruppi-e-blocchi)
5. [Caricare un dataset già pronto](#5-caricare-un-dataset-già-pronto)
6. [Aggiornare un database già caricato](#6-aggiornare-un-database-già-caricato)
7. [Riferimento di tutti i comandi UniKegg](#7-riferimento-di-tutti-i-comandi-unikegg)
8. [Riferimento di tutte le opzioni](#8-riferimento-di-tutte-le-opzioni)
9. [Directory e variabili di ambiente](#9-directory-e-variabili-di-ambiente)
10. [Comandi Docker e interrogazioni SQL](#10-comandi-docker-e-interrogazioni-sql)
11. [Prova con dati sintetici e controlli del codice](#11-prova-con-dati-sintetici-e-controlli-del-codice)
12. [Interruzioni ed errori frequenti](#12-interruzioni-ed-errori-frequenti)

## 1. Scegliere il percorso

| Situazione | Percorso |
|---|---|
| Voglio costruire il dataset completo dei 16 organismi | Installazione, poi sezione 3 |
| Mi servono soltanto i file reviewed UniProt | Installazione Python, poi sezione 4; MySQL e KEGG non servono |
| Ho già i ventidue TSV elaborati e il loro `manifest.json` | Sezione 5 |
| Ho già un database caricato e voglio aggiornarlo | Sezione 6 |
| Voglio provare il funzionamento senza scaricare dati biologici | Sezione 11 |
| Voglio sapere cosa fa un comando o un'opzione | Sezioni 7 e 8 |

Il flusso completo è:

```text
download-uniprot + download-kegg
                ↓
            transform
                ↓
             validate
                ↓
       load (primo caricamento)
          oppure update
                ↓
         verify + history
```

UniProt fornisce le proteine **reviewed / Swiss-Prot**; KEGG fornisce geni e altre entità/relazioni. Il solo download UniProt produce file utilizzabili separatamente, ma la trasformazione del dataset integrato richiede entrambe le fonti.

Senza opzioni, i download selezionano **tutti i 16 organismi**. Il clone pubblico non contiene i dati biologici: la presenza del codice non implica la presenza dei TSV.

## 2. Installare e configurare

### 2.1 Ambiente Python locale

Servono Python 3.11 o successivo e `pip`. La CI del progetto verifica Python 3.11 e 3.12. Dalla directory UniKegg:

```bash
python --version
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
unikegg --help
```

L'ultimo comando deve mostrare l'elenco dei comandi e delle opzioni. Se il sistema chiama Python `python3`, usarlo per creare l'ambiente virtuale. Dopo l'attivazione, `python` punta all'interprete dell'ambiente.

In una nuova sessione di terminale rientrare nella directory del progetto e riattivare l'ambiente:

```bash
source .venv/bin/activate
```

Per uscire dall'ambiente usare `deactivate`. In PowerShell l'attivazione è `.\.venv\Scripts\Activate.ps1`; gli esempi con `export`, `unset` e `source` di questa guida restano specifici di Bash.

### 2.2 Docker per il database

Per usare il database tramite la configurazione fornita, installare Docker Engine o Docker Desktop con Compose v2, quindi verificare:

```bash
docker --version
docker compose version
```

Preparare il file di configurazione, se non esiste già:

```bash
if [ ! -f .env ]; then
    cp .env.example .env
fi
```

Aprire `.env` e controllare database, utente, password e porta. I valori di esempio sono per una dimostrazione locale. La porta pubblicata predefinita è `3307` su `127.0.0.1`.

```bash
docker compose config --quiet
```

L'assenza di errori conferma che Compose riesce a leggere la configurazione. **Compose legge `.env`; la CLI Python locale non lo legge automaticamente.** Per i comandi locali che accedono a MySQL occorrono le variabili della sezione 9. I download e `transform` non richiedono credenziali MySQL.

### 2.3 Scegliere dove conservare il dataset

Per usare i percorsi standard del progetto, in una sessione in cui non si vogliono mantenere override precedenti:

```bash
unset UNIKEGG_HOME UNIKEGG_DATA_DIR UNIKEGG_PROCESSED_DIR UNIKEGG_REVIEWED_DIR
export UNIKEGG_DATASET_KIND=swissprot
```

I risultati saranno in `data/raw/` e `data/processed/`. Come alternativa, per conservare uno snapshot separato:

```bash
export UNIKEGG_DATA_DIR="$HOME/unikegg-data/catalogo16"
export UNIKEGG_PROCESSED_DIR="$UNIKEGG_DATA_DIR/processed"
unset UNIKEGG_REVIEWED_DIR
export UNIKEGG_DATASET_KIND=swissprot
```

`UNIKEGG_PROCESSED_DIR` rende esplicita anche a Compose la directory elaborata da montare. Mantenere queste variabili per tutti i passaggi dello stesso percorso; in un nuovo terminale impostarle nuovamente. I comandi creano le directory necessarie.

## 3. Percorso completo: dai download ai 16 organismi nel database

Questo percorso usa Python locale per acquisizione/trasformazione e Docker per MySQL e caricamento. Presuppone l'installazione della sezione 2. Per l'acquisizione KEGG fare riferimento alle condizioni richiamate nella [documentazione dei dati](data-governance.md).

### Passo 1 — Controllare il catalogo

```bash
unikegg list-organisms
```

L'ordine del catalogo determina anche i blocchi:

| Posizione | Codice | Organismo | Blocco con `--batch-size 4` |
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

Il comando mostra anche i taxid UniProt e KEGG. Alcuni differiscono intenzionalmente: la [guida all'acquisizione](acquisition.md) spiega le scelte di specie/ceppo.

### Passo 2 — Vedere il piano prima del download

```bash
unikegg download-uniprot --all-organisms --batch-size 4 --dry-run
unikegg download-kegg --all-organisms --dry-run
```

Queste anteprime non accedono alla rete e non creano file. UniProt mostra le query iniziali; le pagine effettive dipendono dal numero di proteine. KEGG mostra le richieste di base; i batch di dettagli dipendono dalle relazioni ottenute.

### Passo 3 — Scaricare entrambe le fonti

```bash
unikegg download-uniprot --all-organisms --batch-size 4
unikegg download-kegg --all-organisms
```

I quattro blocchi UniProt vengono elaborati in sequenza, con un TSV gzip per organismo. Ogni query richiede `reviewed:true`; i record ricevuti vengono controllati prima di completare l'export. Non è necessario che una proteina abbia un collegamento KEGG per essere scaricata.

I file raw si trovano sotto la directory dati scelta, in `raw/uniprot/` e `raw/kegg/`. Ciascuna fonte registra il completamento in `selection.json`. Per eseguire i blocchi in sessioni distinte usare invece la sezione 4.3.

### Passo 4 — Trasformare e validare

```bash
unikegg transform
unikegg validate
```

`transform` legge la selezione KEGG completata e richiede che UniProt copra tutti gli organismi selezionati. Produce i **ventidue TSV** delle tabelle biologiche e `manifest.json` nella directory processed. Valida i dati prima di pubblicarli e stampa l'evento `transformed` alla conclusione.

`validate` ricontrolla il bundle elaborato senza accedere a MySQL. Il successo include un messaggio simile a:

```json
{"event": "dataset_validated", "tables": 22, "kind": "swissprot"}
```

Se uno dei due comandi fallisce, risolvere l'errore prima del caricamento.

### Passo 5 — Avviare MySQL ed eseguire il primo caricamento

Per questo esempio si usa un progetto Compose dedicato, distinto dal demo predefinito, con una porta libera:

```bash
export COMPOSE_PROJECT_NAME=unikegg-catalogo16
export MYSQL_PORT=3317
docker compose up -d --wait mysql
docker compose build etl
docker compose run --rm etl load --version-label "Primo caricamento 16 organismi"
```

Mantenere nome del progetto, porta e directory processed anche nei comandi successivi. Cambiare la porta se `3317` è già occupata. Il nome Compose distinto crea un volume MySQL distinto al primo utilizzo; se quel progetto è già stato usato, riapre il volume esistente.

`load` richiede tabelle biologiche vuote al primo caricamento. Al termine stampa `event: ready`, `action: loaded` e `current_version: 1`. Ripetendo il comando con lo stesso dataset esegue una verifica; se il database contiene un dataset diverso, seguire la sezione 6.

L'immagine ETL riceve le credenziali da Compose e monta la directory processed in sola lettura. Download e trasformazione restano nei passaggi locali precedenti.

### Passo 6 — Verificare e leggere la versione

```bash
docker compose run --rm etl verify
docker compose run --rm etl history
```

La verifica riuscita stampa `event: ready` e `action: verified`. Lo storico mostra la versione corrente e le applicazioni registrate, dalla più recente. Per interrogare i dati vedere la sezione 10.2.

## 4. Scaricare singoli organismi, gruppi e blocchi

Gli esempi di questa sezione sono modalità alternative di acquisizione. I percorsi di output sono quelli configurati nella sezione 2.3.

### 4.1 Un organismo o un gruppo manuale

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

### 4.2 Tutti gli organismi o i primi N

```bash
# Tutti i 16, senza raggruppamento esplicito:
unikegg download-uniprot --all-organisms

# I primi 12 nell'ordine del catalogo:
unikegg download-uniprot --limit 12

# Tutti i 16, in blocchi consecutivi da 3: l'ultimo contiene un organismo.
unikegg download-uniprot --all-organisms --batch-size 3
```

`--limit 12` significa dodici **organismi**, non dodici proteine. Il download acquisisce tutte le proteine reviewed restituite per ciascun taxid selezionato.

### 4.3 Un blocco per sessione, accumulando tutti i sedici

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

### 4.4 Aggiungere gruppi scelti a mano

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

### 4.5 Conservare anche il JSON originale

```bash
unikegg download-uniprot --organisms hsa,spo --include-json
```

Il TSV gzip è sempre acquisito; il JSON gzip è aggiuntivo. La trasformazione usa soltanto il TSV. Le pagine TSV sono riprendibili; un JSON interrotto riparte dall'inizio di quel file. Con `--append`, `--include-json` si applica anche agli organismi già selezionati.

### 4.6 Trasformare soltanto una parte di fonti complete

Dopo aver acquisito entrambe le fonti per una selezione più ampia:

```bash
unikegg transform --organisms hsa,eco
unikegg validate
```

Il nuovo bundle processed contiene solo il sottoinsieme richiesto e sostituisce quello precedente nella directory di destinazione. Per conservarli entrambi impostare prima un'altra `UNIKEGG_PROCESSED_DIR`. Applicare questo bundle con `update` restringerebbe anche il database a quel sottoinsieme.

## 5. Caricare un dataset già pronto

Se si dispone già dei ventidue TSV e del relativo `manifest.json`, non servono i download né `transform`.

1. Collocare il bundle completo in `data/processed/` oppure impostare `UNIKEGG_PROCESSED_DIR` sulla sua directory.
2. Impostare `UNIKEGG_DATASET_KIND=swissprot` per un dataset reale.
3. Verificare la configurazione Docker della sezione 2.2.
4. Per un database nuovo eseguire:

```bash
docker compose build etl
docker compose run --rm etl validate
docker compose up -d --wait mysql
docker compose run --rm etl load
docker compose run --rm etl verify
```

Come alternativa per il demo già predisposto, `docker compose up --build` avvia MySQL e il servizio ETL, il cui comando predefinito è `load`. L'ETL termina dopo il caricamento o la verifica; MySQL continua a funzionare. In modalità collegata al terminale, interrompere Compose arresta i servizi; per lasciarli attivi usare `docker compose up --build -d` e consultarne i log.

Se il bundle non ha manifest, seguire la sezione 7.10: occorre l'export reviewed corrispondente per attestare la provenienza. Un manifest non si ricostruisce semplicemente dichiarando che i dati sono Swiss-Prot.

## 6. Aggiornare un database già caricato

`update` applica **l'intero dataset processed**: aggiunge, modifica e rimuove record per far coincidere il database con quel bundle. Per esempio, passare da sedici organismi a tre elimina dal database i tredici esclusi e i relativi dati dipendenti.

### 6.1 Acquisire e preparare un nuovo snapshot

Conservare il nome Compose e la porta del database da aggiornare. Impostare soltanto le directory del nuovo snapshot:

```bash
export UNIKEGG_DATA_DIR="$HOME/unikegg-data/catalogo16-aggiornato"
export UNIKEGG_PROCESSED_DIR="$UNIKEGG_DATA_DIR/processed"
unset UNIKEGG_REVIEWED_DIR
export UNIKEGG_DATASET_KIND=swissprot

unikegg download-uniprot --all-organisms --batch-size 4
unikegg download-kegg --all-organisms
unikegg transform
unikegg validate
```

Usare un nuovo nome di directory per ogni snapshot da conservare. Se la directory scelta contiene già acquisizioni, i download riusano la cache; aggiungere `--refresh` a entrambi per richiedere nuovamente i dati.

### 6.2 Vedere il confronto con il database

```bash
docker compose build etl
docker compose run --rm etl update --dry-run
```

L'evento `update_plan` contiene, per ogni tabella, i conteggi `added`, `modified` e `removed`. Questo dry-run **accede a MySQL**, crea tabelle temporanee e confronta i dati, senza cambiare dati persistenti, schema o versione. Richiede quindi database disponibile, credenziali valide e spazio per lo staging.

### 6.3 Applicare e verificare

```bash
docker compose run --rm etl update --version-label "Aggiornamento catalogo 16"
docker compose run --rm etl verify
docker compose run --rm etl history
```

Un aggiornamento riuscito stampa `event: ready`, `action: updated` e la nuova versione. Se il fingerprint coincide con quello corrente, il comando verifica i dati e restituisce `action: unchanged` senza incrementare la versione.

Lo storico registra metadati, date UTC e conteggi, non una copia delle vecchie righe biologiche. Non sostituisce un backup e non fornisce un comando di ripristino. Un fingerprint già presente come versione storica viene rifiutato come nuovo aggiornamento. Ulteriori dettagli sono nella [guida agli aggiornamenti](updates.md).

## 7. Riferimento di tutti i comandi UniKegg

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

### 7.1 `list-organisms`

```bash
unikegg list-organisms
unikegg list-organisms --search pombe
unikegg list-organisms --organisms hsa,eco
unikegg list-organisms --limit 4
```

La ricerca filtra per codice o nome scientifico senza distinguere maiuscole/minuscole. I taxid sono mostrati nell'output, ma `--search` non è una ricerca per taxid.

### 7.2 `download-uniprot`

```bash
unikegg download-uniprot --all-organisms --batch-size 4
unikegg download-uniprot --organisms hsa --interval 1.5 --attempts 8
```

Scarica solo reviewed. Verifica pagine, organismi, checksum e coerenza delle release. Le opzioni per selezioni cumulative, blocchi e JSON sono spiegate nella sezione 4. Il riuso di una cache verificata non controlla se sul server esistono dati più recenti: per acquisirli usare `--refresh` o una directory nuova.

### 7.3 `download-kegg`

```bash
unikegg download-kegg --all-organisms
unikegg download-kegg --organisms hsa,eco --interval 1.5 --attempts 8
```

Acquisisce gli organismi selezionati, i geni e i dati KEGG richiesti dalla trasformazione. I batch interni delle richieste di dettagli sono gestiti automaticamente. `--batch-size`, `--batch`, `--append` e `--include-json` non sono opzioni KEGG.

### 7.4 `transform`

```bash
unikegg transform
unikegg transform --organisms hsa,eco
unikegg transform --reviewed-export /percorso/export-uniprot
```

L'ultimo percorso è un esempio da sostituire con una directory reale. `--reviewed-export` seleziona una **directory**, non un singolo `.tsv.gz`. La sorgente KEGG resta quella della directory dati configurata.

Senza selezione esplicita usa il manifest KEGG completato; per export legacy senza selezione registrata usa tutti i 16 organismi predefiniti. Il report delle associazioni gene/proteina viene scritto nella directory artifacts come `report_gene_proteina.tsv`.

### 7.5 `validate`

```bash
unikegg validate
```

Controlla il manifest, i checksum, il formato TSV, le chiavi, i riferimenti, i vincoli dei valori e la coerenza delle sequenze. Usa la selezione registrata nel bundle. Non modifica il database e non accetta `--dry-run` né opzioni di selezione.

### 7.6 `load`

Con le variabili MySQL locali configurate come nella sezione 9.2:

```bash
unikegg load --version-label "Prima versione"
```

In alternativa usare `docker compose run --rm etl load --version-label "Prima versione"`. Richiede lo schema inizializzato; non crea autonomamente il database o le ventidue tabelle biologiche. Il primo caricamento richiede tabelle vuote. Lo stesso fingerprint già caricato viene verificato, un fingerprint differente viene rifiutato con l'indicazione di usare `update`.

### 7.7 `update`

```bash
unikegg update --dry-run
unikegg update --version-label "Nuovo snapshot"
```

Richiede una precedente versione caricata. Il comando sincronizza tutto il bundle e può rimuovere record. L'etichetta è facoltativa e deve contenere da 1 a 128 caratteri. Non scarica o trasforma le fonti: questi passaggi precedono l'aggiornamento.

### 7.8 `verify`

```bash
unikegg verify
```

Richiede il bundle processed corrispondente al database. Confronta fingerprint, conteggi, riferimenti e valori delle colonne tramite tabelle temporanee; non modifica i dati persistenti. `validate` controlla i file, `verify` controlla anche la loro corrispondenza al database.

### 7.9 `history`

```bash
unikegg history
```

Restituisce JSON con `current_version` e l'elenco `versions`: versione, data `applied_at`, operazione, etichetta, fingerprint, modifiche e indicatore `current`. Accede a MySQL e funziona anche senza il bundle processed locale. Non accetta filtri per organismo.

### 7.10 `manifest`

Da usare quando i ventidue TSV esistono già e si possiede l'export reviewed di riferimento:

```bash
unikegg manifest --reviewed-export data/raw/uniprot
unikegg validate
```

Il comando ricostruisce `manifest.json` confrontando le accession elaborate con l'export reviewed e poi valida il dataset. Ricava gli organismi dalla tabella elaborata `ORGANISMO`; una selezione esplicita deve coincidere con quella tabella. Non crea i TSV mancanti e non rende valido un dataset con record non reviewed. Nel percorso normale, `transform` genera già il manifest e questo comando non serve.

## 8. Riferimento di tutte le opzioni

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

## 9. Directory e variabili di ambiente

### 9.1 File locali

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

### 9.2 Connessione MySQL dalla CLI locale

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

Usare la password dell'utente applicativo configurata nel server, non necessariamente quella root. Se si è seguito l'esempio dedicato della sezione 3, la porta è `3317`. Il valore host predefinito del codice è `localhost`; qui è esplicitata la connessione TCP a `127.0.0.1`.

Per MySQL installato autonomamente occorre predisporre database, utente e schema con i file `db/init/001_schema.sql`, `002_load_state.sql` e `003_dataset_history.sql`, nell'ordine. Il server deve consentire `LOCAL INFILE` e l'utente deve poter operare sulle tabelle e creare tabelle temporanee. La configurazione Compose fornita esegue l'inizializzazione dello schema quando crea il volume vuoto.

### 9.3 Variabili Compose e percorsi nel container

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

## 10. Comandi Docker e interrogazioni SQL

### 10.1 Gestire i servizi

Usare sempre lo stesso nome Compose e la stessa configurazione dell'installazione interessata.

| Comando | Cosa fa |
|---|---|
| `docker compose config --quiet` | Controlla la configurazione Compose |
| `docker compose build etl` | Ricostruisce l'immagine ETL dal codice corrente |
| `docker compose up -d --wait mysql` | Avvia MySQL in background e attende la disponibilità |
| `docker compose up --build -d` | Avvia il demo completo; l'ETL esegue `load` |
| `docker compose ps -a` | Mostra servizi attivi e terminati |
| `docker compose logs -f etl` | Segue i log del servizio ETL del demo |
| `docker compose logs --tail 100 mysql` | Mostra gli ultimi messaggi di MySQL |
| `docker compose run --rm etl verify` | Esegue una verifica e rimuove il container temporaneo |
| `docker compose run --rm etl history` | Legge lo storico dal database |
| `docker compose stop` | Ferma i servizi conservando container e volumi |
| `docker compose down` | Rimuove container/rete del progetto, mantenendo i volumi dei dati |

L'entrypoint dell'immagine è già `unikegg`: dopo `etl` scrivere `verify`, non `unikegg verify`. I log dei comandi `run --rm` appaiono nel terminale di esecuzione; dopo la rimozione del container non sono i log del servizio `etl` del demo.

Per conservare il database evitare l'opzione `--volumes` di `down`, che elimina anche i volumi. Per rivedere modifiche recenti al codice dentro Docker, ricostruire l'immagine ETL.

### 10.2 Aprire MySQL e fare query

Questo comando usa database e utente configurati nel container e richiede la password applicativa:

```bash
docker compose exec mysql sh -c 'exec mysql -u"$MYSQL_USER" -p "$MYSQL_DATABASE"'
```

Nel prompt MySQL eseguire:

```sql
SELECT COUNT(*) AS organismi FROM ORGANISMO;
SELECT COUNT(*) AS proteine_reviewed FROM PROTEIN_UNIPROT;

SELECT COUNT(*) AS sequenze_non_coerenti
FROM PROTEIN_UNIPROT
WHERE CHAR_LENGTH(amino_acid_sequence) <> sequence_length;

SELECT o.kegg_code, COUNT(p.accession) AS proteine_reviewed
FROM ORGANISMO AS o
LEFT JOIN PROTEIN_UNIPROT AS p ON p.organism_id = o.organism_id
GROUP BY o.kegg_code
ORDER BY o.kegg_code;

SELECT current_version, dataset_sha256
FROM ETL_LOAD_STATE
WHERE singleton_id = 1;
```

Per un dataset completo dei sedici organismi il primo risultato deve essere `16`; il controllo delle lunghezze deve restituire `0`. Il numero di proteine dipende dalla release acquisita, non è un valore fisso.

Le trenta query di integrazione fornite dal progetto sono montate nel container:

```sql
SOURCE /queries/integration.sql;
exit
```

## 11. Prova con dati sintetici e controlli del codice

### 11.1 Demo senza acquisizione biologica

Le fixture contengono record inventati per tutte le ventidue tabelle e 16 organismi. Usare una sessione dedicata e un progetto Compose distinto da quello dei dati reali:

```bash
python tests/make_fixture.py

export UNIKEGG_PROCESSED_DIR="$PWD/tests/fixtures/processed"
export UNIKEGG_DATASET_KIND=synthetic
export COMPOSE_PROJECT_NAME=unikegg-synthetic
export MYSQL_PORT=3308

unikegg validate
docker compose up -d --wait mysql
docker compose build etl
docker compose run --rm etl load --version-label "Demo sintetico"
docker compose run --rm etl verify
docker compose run --rm etl history
```

La prova non contatta UniProt o KEGG; Docker e `pip` possono richiedere rete per immagini e dipendenze. La porta `3308` deve essere libera. Prima di tornare al dataset reale, ripristinare directory, tipo, nome Compose e porta dell'installazione reale.

Opzioni dello script di generazione:

| Opzione | Effetto |
|---|---|
| `--output DIRECTORY` | Directory di destinazione; default `tests/fixtures/processed` |
| `--edge-cases` | Include valori limite, testo particolare e una sequenza lunga |
| `--legacy-quoting` | Produce TSV con la modalità di quoting legacy |

Esempio per i controlli di compatibilità:

```bash
python tests/make_fixture.py --output /tmp/unikegg-fixture --edge-cases --legacy-quoting
```

Lo script scrive i file nella destinazione indicata: scegliere una directory per fixture, separata dai dati reali.

### 11.2 Controlli locali del codice

Con l'ambiente virtuale attivo:

```bash
python -m pip install -r requirements-dev.txt
ruff check src tests tools
sqlfluff lint db --dialect mysql
python tools/lint_ingest.py
pytest -q
```

Ruff controlla il Python; SQLFluff controlla SQL e stile; `lint_ingest.py` verifica separatamente le istruzioni di ingestione; Pytest esegue i test offline con dati inventati e HTTP simulato.

I test reali MySQL sono gestiti anche dalla CI. Il runner `python -m tests.mysql_integration` richiede un database di regressione vuoto chiamato `UniKeggRegression` e `UNIKEGG_MYSQL_TEST_DATABASE=UniKeggRegression`; non è un comando da eseguire sul database biologico. Preparazione, privilegi e condizioni del runner sono descritti in [operations.md](operations.md) e nel [workflow CI](../.github/workflows/ci.yml).

## 12. Interruzioni ed errori frequenti

### 12.1 Riprendere un download interrotto

Ripetere lo stesso comando nella stessa directory dati, mantenendo selezione, blocco, `--append` e formato. Se il comando iniziale aveva `--refresh`, ometterlo nella ripresa.

```bash
# Esempio: riprendere il blocco 2 di una selezione cumulativa.
unikegg download-uniprot --all-organisms --batch-size 4 --batch 2 --append

# Esempio: riprendere KEGG per tutti i sedici.
unikegg download-kegg --all-organisms
```

Le pagine TSV verificate e i file completati vengono riusati. Non aggiungere un nuovo blocco con `--append` mentre il precedente è incompleto. Non modificare manualmente `selection.json` per marcarlo completo.

### 12.2 La release UniProt è cambiata

L'errore `Mixed UniProt releases` indica che i gruppi appartengono a release diverse. Per riacquisire tutti i sedici:

```bash
unikegg download-uniprot --all-organisms --batch-size 4 --refresh
```

Se si vuole aggiornare soltanto la selezione cumulativa già iniziata, ripetere il comando del gruppo interessato aggiungendo `--refresh`, per esempio:

```bash
unikegg download-uniprot --organisms eco,spo --append --refresh
```

In questo secondo esempio vengono aggiornati anche gli organismi precedentemente accumulati. Se l'aggiornamento si interrompe, riprenderlo senza `--refresh`.

### 12.3 Tabella di diagnosi

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
| `KeyError: MYSQL_PASSWORD` nella CLI locale | Esportare la password come nella sezione 9.2; `.env` non viene caricato dalla CLI |
| Connessione MySQL rifiutata | Controllare `docker compose ps -a`, i log MySQL, host e porta; dal computer host usare la porta pubblicata |
| `Access denied` | Controllare credenziali effettive del volume; cambiare `.env` non modifica gli utenti già creati |
| `Dataset has not been committed` | Eseguire `load` sul database inizializzato prima di `verify` o `update` |
| `The database contains a different dataset` | Per applicare il nuovo bundle usare `update --dry-run`, poi `update`; per verificare il vecchio ripristinare il percorso al bundle corrispondente |
| `Nonempty database without load state` | Il database contiene dati senza stato di caricamento riconosciuto; usare un database/progetto vuoto o esaminare quello esistente |
| `Cannot update between synthetic and Swiss-Prot datasets` | Verificare progetto Compose e tipo di dataset; mantenere separati demo sintetico e dati reali |
| `This dataset is a historical version` | È uno snapshot già applicato in passato; non può essere ripresentato come nuovo aggiornamento |
| `Another ingestion owns the load lock` | Attendere il caricamento/aggiornamento già in corso sul database |
| Spazio insufficiente durante load/update/verify | Controllare directory temporanea, volume `etl_tmp` e spazio MySQL; anche il confronto richiede copie e tabelle temporanee |

Per i dettagli sul formato delle tabelle vedere [schema.md](schema.md); per sorgenti, checkpoint e catalogo vedere [acquisition.md](acquisition.md); per sincronizzazione e versioni vedere [updates.md](updates.md).
