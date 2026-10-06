# Aggiornare il database e consultare le versioni

`unikegg update` sincronizza il database esistente con i ventidue TSV e il manifest in `data/processed/` (oppure `UNIKEGG_PROCESSED_DIR`). Aggiunge i record nuovi, modifica quelli cambiati e rimuove quelli assenti dal nuovo dataset, comprese le relazioni. Non ricrea il database, le tabelle biologiche o il volume MySQL.

Per database precedenti all’estensione KO, applicare prima la [migrazione delle relazioni KO](orthology-migration.md) e rigenerare i 22 TSV. `update` non crea automaticamente le nuove tabelle biologiche.

## Comandi

Con il nuovo dataset già trasformato e le variabili di connessione MySQL configurate:

```bash
unikegg update --dry-run
unikegg update --version-label "Aggiornamento settembre 2026"
unikegg history
```

Il dry-run mostra, per ogni tabella, `added`, `modified` e `removed`. Accede al database e carica tabelle temporanee per il confronto, senza modificare dati persistenti, versione o schema. L'etichetta è facoltativa, non vuota e lunga al massimo 128 caratteri. Il comando effettivo ricalcola il piano sullo stato corrente.

Se si usa Compose con il dataset montato nella configurazione del progetto:

```bash
docker compose build etl
docker compose run --rm etl update --dry-run
docker compose run --rm etl update --version-label "Aggiornamento settembre 2026"
docker compose run --rm etl history
```

Il primo caricamento di un database vuoto resta `unikegg load`, che registra la versione 1 e accetta anch'esso `--version-label`. Ripetere `load` con un manifest diverso invita a usare `update`. `history` funziona anche senza file locali del dataset e restituisce JSON, con le versioni dalla più recente alla più vecchia.

## Acquisire una nuova versione dalle fonti

`update` applica un dataset locale completo e validato; il download rimane un passaggio esplicito. Per mantenere i 16 organismi predefiniti:

```bash
unikegg download-kegg --refresh
unikegg download-uniprot --refresh
unikegg transform
unikegg update --dry-run
unikegg update
unikegg history
```

Per i sedici organismi curati aggiungere `--all-organisms` a entrambi i download; per una scelta specifica usare lo stesso `--organisms hsa,eco,spo` oppure `--limit N` su entrambi. `transform` ricava la selezione dalle fonti completate. Si può anche acquisire in una nuova `UNIKEGG_DATA_DIR` per conservare lo snapshot precedente, come nella [guida all'acquisizione](acquisition.md).

La sincronizzazione riguarda **l'intero nuovo dataset**: se si passa da sedici organismi a tre, vengono eliminati dal database gli organismi esclusi e i relativi record dipendenti. Non si tratta di una modifica parziale limitata agli organismi presenti nel file. I comandi `update`, `load` e `verify` non accettano opzioni di selezione: rispettano il manifest già validato.

## Versione corrente e storico persistente

La variabile persistente è `ETL_LOAD_STATE.current_version`. Ogni aggiornamento riuscito con un nuovo fingerprint incrementa il numero. `ETL_DATASET_HISTORY` conserva numero, data UTC, SHA-256 del manifest, tipo di dataset, operazione (`load`, `update`, `baseline`), eventuale etichetta, manifest e conteggi delle modifiche.

```sql
SELECT current_version, dataset_sha256, loaded_at
FROM ETL_LOAD_STATE WHERE singleton_id = 1;

SELECT version, applied_at, action, version_label, dataset_sha256
FROM ETL_DATASET_HISTORY ORDER BY version DESC;
```

`history` restituisce le date con offset `+00:00`. Per leggere `loaded_at` direttamente come UTC in una sessione SQL, impostare `SET time_zone = '+00:00'`; `applied_at` è già memorizzato come data UTC.

La versione identifica le applicazioni locali dei dataset, **non il numero di release KEGG o UniProt**. Un hash diverso non dimostra da solo che le annotazioni siano biologicamente più recenti: usare fonti aggiornate e conservare i metadati di acquisizione. Un fingerprint già nello storico viene rifiutato come aggiornamento; se coincide con quello corrente, il comando confronta i valori e termina con `unchanged`, senza incrementare la versione. Eventuali differenze dovute a modifiche manuali vengono segnalate anche quando il numero di righe coincide.

Lo storico conserva metadati e date, non le vecchie righe biologiche: **non è un backup e non permette da solo di ripristinare una versione precedente**. Non cambia la versione software nel `pyproject.toml`.

## Database esistenti, integrità e spazio

Al primo aggiornamento di un database precedente a questa funzione, il comando aggiunge solo la colonna e la tabella di metadati mancanti. Il dataset già caricato viene registrato come `baseline`, versione 1, conservando la data del caricamento originale; il nuovo diventa versione 2. Prima dell'aggiornamento, `history` mostra questa baseline in sola lettura. Non è possibile ricostruire applicazioni ancora più vecchie non registrate.

Il client valida una copia privata dei TSV, usa il lock MySQL condiviso con `load` e carica lo snapshot in tabelle temporanee. Le righe cambiate vengono sostituite insieme alle dipendenze necessarie, rispettando chiavi esterne e vincoli univoci, inclusi gli scambi di valori univoci. Le righe estranee a queste modifiche rimangono al loro posto. I conteggi dello storico descrivono le differenze logiche: una relazione identica reinserita per aggiornare il suo padre non conta come modifica.

Controlli finali verificano conteggi, riferimenti e valori di tutte le colonne. Dati, versione corrente e voce di storico vengono confermati nella stessa transazione; errori e warning SQL annullano le modifiche. L'eventuale migrazione iniziale dei soli metadati precede la transazione e può restare applicata anche in caso di errore, senza registrare una nuova versione. Questo ordine tiene conto dei [commit impliciti del DDL MySQL](https://dev.mysql.com/doc/refman/8.0/en/implicit-commit.html).

Sono richieste tabelle InnoDB e permessi per tabelle temporanee, inserimenti, cancellazioni e aggiornamenti; la prima migrazione richiede anche `ALTER`/`CREATE`. Si riutilizza l'account applicativo configurato. Il lock coordina i comandi UniKegg; scritture manuali o applicazioni esterne devono essere sospese durante la sincronizzazione.

Prevedere spazio per la copia privata dei TSV, lo staging MySQL dell'intero snapshot e i log della transazione. Anche il dry-run esegue lo staging completo: il tempo dipende dalla dimensione del dataset. La funzione evita la ricostruzione del database ma non evita il download, la trasformazione e il confronto del nuovo snapshot.
