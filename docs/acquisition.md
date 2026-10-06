# Download degli organismi modello

Per il percorso completo dall'installazione al database, con il riferimento di tutti i comandi, vedere la [guida pratica passo per passo](guida-comandi.md).

UniKegg supporta un catalogo curato di **16 organismi**, con proteine UniProtKB/Swiss-Prot (`reviewed:true`). Tutti i 16 organismi sono il default. `--all-organisms` seleziona tutti i 16 organismi del catalogo, non l'intero catalogo KEGG. Gli ID locali dei dieci organismi originali rimangono invariati.

## Organismi disponibili

| Codice KEGG | Organismo / ceppo | Taxid nella query UniProt | Taxid KEGG | Selezione |
|---|---|---:|---:|---|
| hsa | Homo sapiens | 9606 | 9606 | Default |
| mmu | Mus musculus | 10090 | 10090 | Default |
| rno | Rattus norvegicus | 10116 | 10116 | Default |
| dre | Danio rerio | 7955 | 7955 | Default |
| dme | Drosophila melanogaster | 7227 | 7227 | Default |
| cel | Caenorhabditis elegans | 6239 | 6239 | Default |
| ath | Arabidopsis thaliana | 3702 | 3702 | Default |
| sce | Saccharomyces cerevisiae S288c | 559292 | 559292 | Default |
| eco | Escherichia coli K-12 | 83333 | 511145 | Default |
| bsu | Bacillus subtilis 168 | 224308 | 224308 | Default |
| spo | Schizosaccharomyces pombe 972h− | 284812 | 284812 | Aggiunto |
| ddi | Dictyostelium discoideum | 44689 | 352472 | Aggiunto |
| gga | Gallus gallus | 9031 | 9031 | Aggiunto |
| xtr | Xenopus tropicalis | 8364 | 8364 | Aggiunto |
| mtu | Mycobacterium tuberculosis H37Rv | 83332 | 83332 | Aggiunto |
| pae | Pseudomonas aeruginosa PAO1 | 208964 | 208964 | Aggiunto |

Il 30 settembre 2026 sono stati confrontati campioni di cinque proteine reviewed per ciascuno dei sei organismi aggiunti con `/conv/uniprot/{codice}`: tutti i cinque collegamenti per organismo coincidevano nelle due fonti. Il catalogo KEGG e le query UniProt dei dieci organismi originali sono stati verificati nell'audit precedente. Queste prove verificano la compatibilità del perimetro; non garantiscono che ogni gene abbia una proteina reviewed o che le annotazioni restino immutate.

Le differenze di taxid per `eco` e `ddi` sono intenzionali: il codice conserva esplicitamente entrambi gli identificativi, senza sostituire automaticamente il taxid della query UniProt con quello del genoma KEGG. Per `spo` si usa il ceppo 972h−: la query sul taxid generico 4896 non ha restituito proteine reviewed con collegamenti KEGG nella verifica. I 16 taxid UniProt selezionati sono distinti, quindi non è necessaria una migrazione dello schema SQL. L'estensione a ceppi con taxid condivisi richiederebbe una diversa modellazione.

## Comandi

Dalla directory del progetto, dopo l'installazione del pacchetto:

```bash
unikegg list-organisms
unikegg list-organisms --search pombe

# Tutti i 16 organismi del catalogo curato (comportamento predefinito):
unikegg download-kegg
unikegg download-uniprot
unikegg transform

unikegg validate

# Una lista precisa:
unikegg download-kegg --organisms hsa,eco,spo
unikegg download-uniprot --organisms hsa,eco,spo
unikegg transform

# I primi 12, nell'ordine della tabella:
unikegg download-kegg --limit 12 --dry-run
unikegg download-uniprot --limit 12 --dry-run
```

Le modalità `--organisms`, `--limit` e `--all-organisms` sono alternative. `--limit` accetta un intero da 1 a 16, senza ridurre silenziosamente un numero maggiore. Codici sconosciuti, vuoti o ripetuti sono rifiutati prima di scaricare. Il dry-run non accede alla rete e non crea file. Per KEGG mostra il numero esatto di richieste di base (86 per tutti i 16 organismi); i batch aggiuntivi dipendono dalle relazioni scaricate. UniProt mostra le query delle pagine; il numero complessivo di pagine è noto solo dopo la prima risposta di ciascuna query.

`transform` legge la selezione completata di KEGG e richiede che UniProt la copra. Per trasformare solo una parte di fonti già scaricate:

```bash
unikegg transform --organisms hsa,eco
```

I manifest processed registrano i codici effettivi. `validate`, `load`, `update` e `verify` utilizzano quel perimetro; non accettano opzioni per cambiarlo. I vecchi manifest senza questo campo continuano a richiedere i dieci organismi originali. Per sincronizzare un database già caricato con il nuovo dataset usare `unikegg update`; `load` continua a rifiutare un fingerprint diverso. La sincronizzazione rimuove anche gli organismi esclusi dalla nuova selezione. Versione corrente e storico sono descritti nella [guida agli aggiornamenti](updates.md).

## UniProt: singoli organismi, gruppi e blocchi automatici

Tutti i comandi UniProt richiedono esclusivamente record `reviewed:true` e verificano lo stato reviewed nelle risposte. Ogni organismo conserva il proprio file TSV gzip con sequenze e annotazioni, anche quando viene scaricato in un blocco. Non serve che una proteina abbia un collegamento KEGG per essere inclusa nel download.

```bash
# Un organismo:
unikegg download-uniprot --organisms hsa

# Un gruppo scelto manualmente:
unikegg download-uniprot --organisms hsa,mmu,eco

# Tutti i 16, in quattro blocchi consecutivi da quattro organismi:
unikegg download-uniprot --all-organisms --batch-size 4

# Solo il secondo blocco (dme,cel,ath,sce), senza scaricare gli altri:
unikegg download-uniprot --all-organisms --batch-size 4 --batch 2

# Anteprima dei blocchi, senza rete o scritture:
unikegg download-uniprot --all-organisms --batch-size 4 --dry-run
```

`--batch-size` accetta da 1 a 16 organismi; `--batch` richiede `--batch-size` ed è numerato da 1. I blocchi seguono l'ordine del catalogo e si applicano alla selezione indicata (`--all-organisms`, `--organisms` o `--limit`); senza selezione esplicita si usano tutti i 16 organismi predefiniti. L'ultimo blocco può contenere meno organismi. Senza `--batch` il comando esegue tutti i blocchi in sequenza. Il raggruppamento riguarda gli organismi; la paginazione HTTP resta di massimo 500 proteine per pagina.

Per costruire progressivamente una selezione in più sessioni usare **`--append`**:

```bash
# Gruppi manuali: al termine la selezione disponibile è hsa,mmu,eco,spo.
unikegg download-uniprot --organisms hsa,mmu
unikegg download-uniprot --organisms eco,spo --append

# In una directory dedicata, quattro sessioni per ottenere tutti i 16:
export UNIKEGG_DATA_DIR="$PWD/data-uniprot-16"
unikegg download-uniprot --all-organisms --batch-size 4 --batch 1 --append
unikegg download-uniprot --all-organisms --batch-size 4 --batch 2 --append
unikegg download-uniprot --all-organisms --batch-size 4 --batch 3 --append
unikegg download-uniprot --all-organisms --batch-size 4 --batch 4 --append
```

`--append` unisce il gruppo richiesto alla selezione registrata nella stessa directory e ricontrolla i file precedenti, riutilizzando la cache verificata. Funziona anche per il primo gruppo. Gli organismi sovrapposti vengono inclusi una sola volta. Senza `--append`, il manifest continua a rappresentare solo la selezione dell'ultimo comando; gli altri file restano sul disco e possono essere riutilizzati con una successiva selezione più ampia.

In caso di interruzione, ripetere lo stesso comando (stessa selezione, blocco, `--append` e formato) **senza `--refresh`** prima di aggiungere un altro gruppo. La selezione cumulativa resta incompleta fino alla conclusione della ripresa. Release diverse tra i gruppi vengono rifiutate: ripetere il comando con `--append --refresh` aggiorna **l'intera selezione cumulativa**, compresi gli organismi precedenti. Anche `--include-json` si applica all'intera selezione cumulativa. Per passare a una selezione differente dopo un'interruzione, eseguire un comando senza `--append`; per aggiornare tutti i sedici usare `--all-organisms --refresh`.

Le opzioni `--batch-size`, `--batch` e `--append` sono specifiche di `download-uniprot`. Per la trasformazione integrata serve anche la corrispondente acquisizione KEGG, ad esempio `unikegg download-kegg --all-organisms` nella stessa directory dati; poi eseguire `unikegg transform`.

## Interruzioni, cache e aggiornamento

Entrambi i client usano una pausa predefinita di un secondo per richiesta, fino a quattro tentativi e un limite minimo configurabile di 0,34 secondi. I processi dello stesso utente che condividono la directory temporanea coordinano le chiamate allo stesso host; processi su altre macchine/utenti che condividono l'IP non sono coordinabili da questo programma. HTTP 429, 408, 500, 502, 503 e 504 ammettono tentativi successivi. Le attese crescono e rispettano `Retry-After`, sia numerico sia come data HTTP. Il cooldown del server persiste anche se si esaurisce l'ultimo tentativo. Errori permanenti, come HTTP 400/404, falliscono subito.

```bash
unikegg download-kegg --all-organisms --interval 1.5 --attempts 8
unikegg download-uniprot --all-organisms --interval 1.5 --attempts 8
```

Se un lavoro si interrompe, rilanciare lo stesso comando **senza `--refresh`**. I file completati sono riutilizzati solo dopo verifica di richiesta, checksum e contenuto. UniProt conserva l'identità del refresh interrotto: riprende le nuove pagine già salvate, anche quando esiste ancora il vecchio archivio, e aggiorna gli export non ancora raggiunti. Il JSON facoltativo riparte dall'inizio del singolo file. Una selezione incompleta non può essere trasformata. I lock sull'acquisizione sono liberati dal sistema operativo alla chiusura del processo; il file del lock può restare sul disco. Una trasformazione di fonti gestite non parte mentre un downloader le sta modificando.

UniProt TSV usa `/search` con pagine fino a 500 proteine, ordinamento stabile per accession e checkpoint in `raw/uniprot/.pages/`. Ogni pagina conserva checksum e URL; una pagina danneggiata invalida solo quella parte del checkpoint e le successive. Colonne, organismi, stato reviewed, accession duplicate, totale e release sono verificati prima di pubblicare il gzip finale. Una release cambiata durante l'acquisizione richiede un aggiornamento completo, evitando di mescolare le release tra pagine o organismi.

Il JSON UniProt è facoltativo:

```bash
unikegg download-uniprot --organisms hsa,spo --include-json
```

Il JSON usa lo stream originale e, in caso di interruzione del singolo file, riparte dall'inizio; la trasformazione legge soltanto il TSV. La modalità predefinita evita di scaricare il JSON inutilizzato.

Per acquisire dati nuovi, è preferibile usare una nuova directory:

```bash
export UNIKEGG_DATA_DIR="$PWD/data-snapshot-2026-09"
unikegg download-kegg --all-organisms
unikegg download-uniprot --all-organisms
unikegg transform
```

In alternativa `--refresh` aggiorna i file nella directory attuale e ricomincia i checkpoint UniProt. Finché l'acquisizione non termina, il relativo stato resta incompleto. I file finali precedenti sono preservati quando il nuovo trasferimento del singolo file fallisce. Un gzip valido ma senza provenienza verificabile viene acquisito nuovamente. La cache verificata non è una verifica di freschezza sul server.

KEGG conserva i batch scaricati sotto `raw/kegg/batches/`, poi produce record per identificatore con un indice `details/{categoria}/active.json`. Solo i record attivi sono letti dalla trasformazione; batch vecchi sovrapposti non generano duplicati e una selezione più piccola non reintroduce dettagli precedenti. Gli export manuali legacy senza indice restano leggibili con i controlli originali sui duplicati.

## Memoria, disco e verifica

Geni e proteine vengono scritti progressivamente; le principali relazioni vengono deduplicate e ordinate in un database SQLite temporaneo, con cache limitata, evitando più copie in memoria. Gli indici di validazione e appartenenza rimangono in RAM: il consumo non è costante rispetto al numero di record. L'obiettivo è il catalogo curato, non un import di tutti i genomi KEGG.

`TMPDIR` controlla la directory di lavoro temporanea. Nell'immagine Docker è `/app/tmp`, montata dal volume su disco `etl_tmp`; i grandi snapshot non consumano il tmpfs `/tmp`. Checkpoint e batch raw restano disponibili per la ripresa e consumano spazio anche dopo il completamento; non sono cancellati automaticamente. Usare directory separate per conservare o archiviare gli snapshot.

I test offline verificano selezioni di 1/2/16 organismi, pipeline ripetuta, risposta reviewed vuota, retry e cooldown, lock concorrenti, pagine interrotte/danneggiate, cambio di release, conteggi errati, cache e dettagli KEGG. Le prove live sui client aggiornati hanno verificato due pagine UniProt effettive, un batch KEGG e il successivo riuso della cache senza rete. Non è stato scaricato l'intero dataset dei 16 organismi.

I test dei blocchi UniProt coprono inoltre tutti i 16 organismi in una singola esecuzione o in sessioni cumulative, blocchi incompleti nell'ultima posizione, gruppi manuali, JSON facoltativo, opzioni non valide, dry-run senza modifiche, ripresa delle aggiunte interrotte e aggiornamento delle release nei gruppi precedenti. Queste verifiche usano risposte HTTP simulate e non scaricano dati biologici.

Fonti: [KEGG API e limite delle richieste](https://www.kegg.jp/kegg/rest/), [manuale KEGG](https://www.kegg.jp/kegg/rest/keggapi.html), [API UniProt, paginazione e stream](https://academic.oup.com/nar/article/53/W1/W547/8126256).

## Collegamenti diretti KO, pathway ed EC

`download-kegg` acquisisce anche `/link/pathway/ko` e `/link/enzyme/ko`, salvando `relations/ko_pathway.tsv` e `relations/ko_ec.tsv`. Sono relazioni globali, come i cataloghi KO e reference pathway, indipendenti dalla selezione degli organismi. La cache verificata, i checksum e i tentativi HTTP si applicano anche a questi file. `transform` richiede entrambi i raw, normalizza gli identificatori e produce `ortologia_pathway.tsv` e `ortologia_ec.tsv`; un raw mancante o incoerente blocca la pubblicazione. Per snapshot precedenti, seguire la [procedura di migrazione](orthology-migration.md).
