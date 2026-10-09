# Migrazione delle relazioni KO–Pathway e KO–EC

Per installazione, avvio del server e credenziali scegliere il percorso [Python e SQL senza Docker](command-guide.it.md#a-python-e-sql-senza-docker) oppure [Docker e SQL](command-guide.it.md#b-docker-e-sql). Questa pagina approfondisce la singola operazione.

Prima di usare i nuovi nomi inglesi, seguire la [migrazione dei nomi](english-names-migration.it.md). La rinomina delle tabelle precede la migrazione KO nei database esistenti.

Il modello comprende **22 tabelle biologiche: 11 entità e 11 associazioni**.
`ORTHOLOGY_PATHWAY(ko_id, map_id)` collega `ORTHOLOGY_KEGG` a
`PATHWAY_REFERENCE`; `ORTHOLOGY_EC(ko_id, ec_number)` collega KO al catalogo
esistente `EC_NUMBER`. Entrambe hanno PK composite, FK non nulle, indici per
la ricerca inversa e vincoli `ON DELETE RESTRICT ON UPDATE RESTRICT`.

Le associazioni sono N:M e facoltative: un KO può avere più EC e più pathway,
oppure nessuno. Non tutti i KO sono enzimi. Le mappe KEGG comprendono anche
composti e altre componenti; le rappresentazioni di riferimento possono essere
basate su KO, EC o reazioni. Un EC descrive una classificazione catalitica,
non identifica necessariamente una singola reazione KEGG. Il collegamento
`EC → KO → Pathway` indica annotazioni condivise, non dimostra che ogni attività
EC di un KO multifunzionale sia impiegata in ciascuno dei suoi pathway.
Fonti: [KEGG PATHWAY](https://www.kegg.jp/kegg/pathway.html) e
[manuale API KEGG](https://www.kegg.jp/kegg/rest/keggapi.html).

## Download e pulizia

L'API usa `link/<target>/<source>`; scegliamo KO come sorgente, quindi la prima
colonna dei raw è il KO:

| Endpoint | Raw sotto `data/raw/kegg/` | TSV sotto `data/processed/` |
|---|---|---|
| `/link/pathway/ko` | `relations/ko_pathway.tsv` | `orthology_pathway.tsv`: `ko_id`, `map_id` |
| `/link/enzyme/ko` | `relations/ko_ec.tsv` | `orthology_ec.tsv`: `ko_id`, `ec_number` |

`/link/ko/pathway` e `/link/ko/enzyme` interrogano la direzione inversa e
restituiscono colonne invertite: non sostituire quei raw ai file qui descritti.
La pipeline elimina i prefissi `ko:`, `path:` ed `ec:`, converte sia
`path:ko00010` sia `path:map00010` in `map00010`, ordina e deduplica le pairs.
Mantiene gli EC preliminari e incompleti, per esempio `3.5.1.n3` e `1.1.1.-`.
Il catalogo EC è l'unione di UniProt, campi ENZYME delle reazioni selezionate e
link diretti KO–EC; un EC presente solo in questi ultimi viene conservato.

Le relazioni coprono tutti i KO e reference pathway dei cataloghi scaricati,
anche quelli senza geni negli organismi selezionati. Identificatori malformati,
KO/pathway privi del rispettivo padre e file mancanti interrompono la
trasformazione, preservando il precedente bundle. File di relazione vuoti ma
validi producono TSV con sola intestazione. Non si deducono collegamenti
attraverso reazioni o proteine.

Con l'ambiente Python aggiornato, dalla radice del progetto:

```bash
# Usare la stessa selezione KEGG/UniProt dello snapshot esistente.
# Esempio per una selezione hsa,eco già disponibile in UniProt:
unikegg download-kegg --organisms hsa,eco
unikegg transform
unikegg validate
```

Per tutti i 16 organismi, omettere `--organisms` solo se anche l'export UniProt
li copre. Il download riusa i file con cache verificata e acquisisce quelli
mancanti; `--refresh` rinnova tutte le richieste. Per esportazioni manuali
autorizzate fornire i due nuovi raw nell'ordine indicato. `transform` genera
tutti i **22 TSV e un nuovo manifest**: non basta aggiungere due file al vecchio
manifest, né crearli vuoti per aggirare i controlli.

## Schema nuovo o database già popolato

Per un database nuovo, `db/init/001_schema.sql` comprende già le due tabelle.
Dopo avere preparato i 22 TSV, `docker compose up --build` inizializza e importa
il dataset con `db/load/001_ingest.sql`, caricando i cataloghi prima dei link.

Per un volume esistente, i file `db/init` non vengono rieseguiti. Conservare un
backup del database e del bundle precedente, sospendere altri writer e applicare
la migrazione additiva con l'account del database configurato in Compose:

```bash
docker compose up -d mysql
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -u"$MYSQL_USER" "$MYSQL_DATABASE"' < db/migrations/004_orthology_links.sql
docker compose build etl
docker compose run --rm etl update --dry-run
docker compose run --rm etl update --version-label "Relazioni dirette KO-Pathway e KO-EC"
docker compose run --rm etl verify
docker compose run --rm etl history
```

Senza Compose, applicare lo stesso SQL con il client `mysql` al database
configurato, poi usare `unikegg update --dry-run`, `unikegg update` e
`unikegg verify`. Se il database non ha ancora un dataset caricato, usare
`load` al posto di `update`.

La migrazione richiede `CREATE` e `REFERENCES`, conserva le tabelle e i dati
esistenti e non disabilita le FK. `IF NOT EXISTS` permette di riprenderla dopo
un'interruzione, ma non corregge tabelle omonime con uno schema diverso.
Il DDL MySQL effettua commit impliciti: la migrazione precede la transazione
di aggiornamento e può restare applicata con tabelle vuote se l'ETL fallisce.
`update` sincronizza l'intero bundle, comprese le nuove associazioni, e registra
la nuova versione solo dopo la verifica. Il dry-run va eseguito dopo la migrazione.
Un vecchio bundle a 20 file viene rifiutato dal validatore attuale.

## Verifica del mapping

```sql
SELECT ko_id, COUNT(*) AS pathway_count
FROM ORTHOLOGY_PATHWAY GROUP BY ko_id;

SELECT oe.ec_number, oe.ko_id, op.map_id, p.name
FROM ORTHOLOGY_EC AS oe
INNER JOIN ORTHOLOGY_PATHWAY AS op ON op.ko_id = oe.ko_id
INNER JOIN PATHWAY_REFERENCE AS p ON p.map_id = op.map_id
WHERE oe.ec_number = '1.1.1.1';
```

Il diagramma ER aggiornato e i vincoli sono descritti in [schema.md](schema.md).

## Dump legacy con nomi minuscoli

Il dump Windows `dump_progetto_completo` del 30 settembre 2026 usa nomi di
tabella minuscoli e non comprende le colonne di evidenza GO del contratto
attuale. Su Linux, dove i nomi possono essere case-sensitive, la sola migrazione
SQL precedente non basta per questo specifico schema.

`tools/migrate_legacy_dump.py` ripristina i venti file in un MySQL temporaneo senza
listener TCP, allinea i nomi, aggiunge le colonne GO come NULL e popola i due
collegamenti da raw KEGG con checksum verificati. Conserva tutti i valori
originali, aggiunge i cataloghi mancanti, esporta SQL/TSV e verifica il dump
reimportandolo in un secondo database. Richiede i binari nativi `mysqld`,
`mysql`, `mysqldump` e le dipendenze Python del progetto. Non si collega a un
server preesistente. Il dump SQL risultante va importato in uno schema vuoto.

La migrazione reale del 5 ottobre ha preservato 2.006.370 righe originali e
prodotto 2.066.856 righe in 22 tabelle. Il pacchetto consegnato include i raw,
il rapporto, le istruzioni e tutti i checksum. Un solo link KO–EC, relativo
a K10658 assente dal catalogo e confermato HTTP 404 da KEGG, è stato escluso
con evidenza registrata. La pipeline ordinaria mantiene il rifiuto degli
orfani; lo strumento legacy richiede una verifica esplicita prima di escluderli.

Non viene fabbricato un manifest Swiss-Prot dal solo dump: la provenienza
reviewed necessita degli export verificati. Questa consegna è un dump SQL
autonomo, senza uno storico ETL inventato; non costituisce un refresh completo
di tutte le annotazioni biologiche.
