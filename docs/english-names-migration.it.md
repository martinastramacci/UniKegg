# Migrazione dei nomi e dei file del dataset in inglese

Per avviare e configurare il server, seguire prima i percorsi [Python e SQL oppure Docker e SQL](command-guide.it.md). La sezione C3 mostra anche come eseguire gli strumenti di migrazione nei container.

[Versione inglese](english-names-migration.it.md).

Le nuove installazioni usano nomi inglesi per tabelle biologiche, TSV e documenti. Colonne, chiavi, identificatori biologici e valori delle fonti rimangono invariati. Le guide italiane hanno lo stesso nome inglese della versione principale, con suffisso `.it.md`.

La [tabella dei nomi precedenti e nuovi](english-names-migration.md#name-mapping) elenca le 18 tabelle rinominate. `GENE_KEGG`, `PROTEIN_UNIPROT`, `PROTEIN_ISOFORM` e `GENE_PATHWAY` erano già in inglese. Il report diventa `report_gene_protein.tsv`; lo strumento per i dump produce `unikegg_updated.sql` e `excluded_relationships.tsv`. Le tabelle operative e i manifest storici conservano nomi e contenuti originali.

## Dataset precedente con 22 TSV

Convertire in una directory separata e non ancora esistente:

```bash
PYTHONPATH=src python tools/migrate_dataset_names.py \
  --source data/processed --output data/processed-english
export UNIKEGG_PROCESSED_DIR="$PWD/data/processed-english"
unikegg validate
```

Lo strumento verifica i checksum originali, conserva tutti i byte dei TSV e le dichiarazioni reviewed, rinomina i file, aggiorna le chiavi nel manifest e valida l'intero risultato prima di pubblicarlo. La directory sorgente resta intatta. Il fingerprint cambia perché cambiano i nomi: per un database popolato usare `update`, non `load`.

In alternativa, rigenerare dalle fonti raw completate:

```bash
export UNIKEGG_PROCESSED_DIR="$PWD/data/processed-english"
unikegg transform
unikegg validate
```

Il trasformatore inglese rifiuta di sovrascrivere una directory che contiene i vecchi TSV italiani, poiché sono estranei al nuovo contratto. Conservare quella directory e scegliere un output distinto. Un bundle precedente con 20 TSV richiede la rigenerazione completa, comprese le relazioni KO attuali; non basta rinominare i file.

## Database esistente

Configurare le variabili di connessione MySQL e sospendere gli altri writer. Visualizzare il piano, poi applicarlo:

```bash
PYTHONPATH=src python tools/migrate_database_names.py
PYTHONPATH=src python tools/migrate_database_names.py --apply
```

Lo strumento usa il lock dell'ingestione e un solo `RENAME TABLE`, rifiuta collisioni fra vecchi e nuovi nomi e supporta schemi completi a 20 o 22 tabelle. Se i nomi sono già inglesi non modifica nulla. Non carica righe né cambia lo storico delle versioni. Il DDL MySQL esegue commit impliciti: questa fase precede l'aggiornamento ETL.

Per un database a 20 tabelle applicare anche `db/migrations/004_orthology_links.sql` **dopo** la rinomina, prima di sincronizzare il nuovo bundle completo. Per un database a 22 tabelle tutte italiane è disponibile anche `db/migrations/005_english_names.sql`, da eseguire una volta sola. Il file SQL statico richiede tutte le vecchie tabelle; per schemi a 20 tabelle o già inglesi usare lo strumento Python.

Selezionato il dataset inglese validato:

```bash
unikegg update --dry-run
unikegg update --version-label "Nomi biologici in inglese"
unikegg verify
unikegg history
```

Per una conversione che cambia solo i nomi, l'anteprima deve mostrare zero differenze biologiche. Il nuovo fingerprint viene registrato dalla normale transazione di aggiornamento. Manifest e conteggi storici restano evidenza del precedente contratto. Installare i sorgenti non esegue migrazioni del database.

## Dump SQL precedenti

`tools/migrate_legacy_dump.py` accetta nomi di file italiani o inglesi, risolve i vecchi nomi minuscoli delle tabelle importate ed esporta lo schema inglese corrente. Se sono presenti entrambe le varianti dello stesso file, l'input ambiguo viene rifiutato. I dump originali e gli artefatti di acquisizione vanno conservati; le nuove esportazioni usano i nomi inglesi.

## Ambiente virtuale del progetto principale

Dalla radice del progetto principale:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
python -c 'import unikegg; print(unikegg.__file__)'
```

Il percorso stampato deve appartenere al progetto principale. L'ambiente virtuale della copia di prova continua a usare la sua installazione modificabile anche dopo un `cd`.
