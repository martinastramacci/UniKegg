# Download the model organisms

For installation, server startup and credentials, choose [Python and SQL without Docker](command-guide.md#a-python-and-sql-without-docker) or [Docker and SQL](command-guide.md#b-docker-and-sql). This page describes the individual operation in more detail.

For installations with previous Italian table or TSV names, first follow the [English naming migration](english-names-migration.md).

[Italian copy](acquisition.it.md). For installation through database loading and the full CLI reference, see the [step-by-step command guide](command-guide.md).

UniKegg supports a curated catalog of **16 organisms**, restricted to UniProtKB/Swiss-Prot proteins (`reviewed:true`). All sixteen are selected by default. `--all-organisms` selects the curated catalog, not all KEGG genomes. Local IDs of the original ten organisms remain unchanged.

## Available organisms

| KEGG code | Organism / strain | UniProt query taxid | KEGG taxid | Selection |
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
| spo | Schizosaccharomyces pombe 972h− | 284812 | 284812 | Added |
| ddi | Dictyostelium discoideum | 44689 | 352472 | Added |
| gga | Gallus gallus | 9031 | 9031 | Added |
| xtr | Xenopus tropicalis | 8364 | 8364 | Added |
| mtu | Mycobacterium tuberculosis H37Rv | 83332 | 83332 | Added |
| pae | Pseudomonas aeruginosa PAO1 | 208964 | 208964 | Added |

On 30 September 2026, samples of five reviewed proteins for each of the six added organisms were compared with `/conv/uniprot/{code}`. All five links per organism matched between sources. The original ten KEGG codes and UniProt queries were checked in the preceding audit. These checks establish scope compatibility; they do not guarantee that every gene has a reviewed protein or that annotations remain unchanged.

The taxid differences for `eco` and `ddi` are intentional. The catalog records both identifiers and does not automatically replace the UniProt query taxid with the KEGG genome taxid. `spo` uses strain 972h−: a query with generic taxid 4896 did not return reviewed proteins with KEGG links during verification. The sixteen selected UniProt taxids are distinct, so expanding the catalog did not require SQL schema migration. Supporting strains with shared taxids would require different modeling.

## Commands

From the project directory after installing the package:

```bash
unikegg list-organisms
unikegg list-organisms --search pombe

# All 16 curated organisms (default):
unikegg download-kegg
unikegg download-uniprot
unikegg transform
unikegg validate

# A specific selection:
unikegg download-kegg --organisms hsa,eco,spo
unikegg download-uniprot --organisms hsa,eco,spo
unikegg transform

# First 12 in catalog order:
unikegg download-kegg --limit 12 --dry-run
unikegg download-uniprot --limit 12 --dry-run
```

`--organisms`, `--limit` and `--all-organisms` are mutually exclusive. `--limit` accepts 1–16 without silently clamping larger values. Unknown, empty or duplicate codes are rejected before downloading. Dry-run uses no network and creates no files. KEGG shows the exact base request count (88 for sixteen organisms); additional batches depend on downloaded relationships. UniProt shows page queries; the total page count is known after the first response for each query.

`transform` reads KEGG's completed selection and requires UniProt to cover it. To transform a subset of already downloaded sources:

```bash
unikegg transform --organisms hsa,eco
```

Processed manifests record the actual codes. `validate`, `load`, `update` and `verify` use this scope and reject options that change it. Older manifests without that field retain the original ten-organism contract. Use `unikegg update` to synchronize an existing database with a new dataset; `load` rejects a different fingerprint. Synchronization also removes organisms excluded by the new selection. See [dataset updates](updates.md) for versions and history.

## UniProt: individual organisms, groups and automatic batches

Every UniProt command requests `reviewed:true` and verifies reviewed status in responses. Each organism retains its own gzip TSV of sequences and annotations, even when downloaded within a batch. Proteins do not need a KEGG link to be included.

```bash
# One organism:
unikegg download-uniprot --organisms hsa

# A manually selected group:
unikegg download-uniprot --organisms hsa,mmu,eco

# All sixteen, in four sequential batches of four:
unikegg download-uniprot --all-organisms --batch-size 4

# Only batch 2 (dme,cel,ath,sce):
unikegg download-uniprot --all-organisms --batch-size 4 --batch 2

# Preview without network or writes:
unikegg download-uniprot --all-organisms --batch-size 4 --dry-run
```

`--batch-size` accepts 1–16; `--batch` requires it and is numbered from 1. Batches follow catalog order within the selected scope. Without explicit selection, all sixteen default organisms are used. The final batch may be smaller. Omitting `--batch` executes every batch in sequence. Organism grouping does not change HTTP pagination, which remains at most 500 proteins per page.

Use **`--append`** to build a cumulative selection over several sessions:

```bash
# Final selection: hsa,mmu,eco,spo.
unikegg download-uniprot --organisms hsa,mmu
unikegg download-uniprot --organisms eco,spo --append

# Four sessions for all sixteen, in a dedicated directory:
export UNIKEGG_DATA_DIR="$PWD/data-uniprot-16"
unikegg download-uniprot --all-organisms --batch-size 4 --batch 1 --append
unikegg download-uniprot --all-organisms --batch-size 4 --batch 2 --append
unikegg download-uniprot --all-organisms --batch-size 4 --batch 3 --append
unikegg download-uniprot --all-organisms --batch-size 4 --batch 4 --append
```

`--append` merges the requested group with the recorded selection in the same directory, rechecks previous files and reuses verified caches. It also works for the first group. Overlapping organisms appear once. Without `--append`, the manifest represents only the latest command's selection; other files remain on disk and can be reused by a broader selection later.

After interruption, repeat the same command (selection, batch, `--append`, format) **without `--refresh`** before adding another group. The cumulative selection stays incomplete until resumption finishes. Groups with different releases are rejected. Repeating with `--append --refresh` refreshes **the entire cumulative selection**, including earlier organisms. `--include-json` likewise applies to the entire cumulative selection. To change selection after interruption, run without `--append`; to refresh all sixteen use `--all-organisms --refresh`.

`--batch-size`, `--batch` and `--append` apply only to `download-uniprot`. Integrated transformation also needs matching KEGG acquisition, for example `unikegg download-kegg --all-organisms` in the same data directory, followed by `unikegg transform`.

## Interruptions, caches and refresh

Both clients default to one second between requests, up to four attempts and a configurable minimum interval of 0.34 seconds. Same-user processes sharing the temporary directory coordinate calls to each host. Processes on other machines or users sharing an IP cannot be coordinated by this program. HTTP 429, 408, 500, 502, 503 and 504 are retried with increasing delays and respect numeric or HTTP-date `Retry-After`. Server cooldown persists after the last attempt fails. Permanent errors such as HTTP 400/404 fail immediately, except independently recorded 404 checks used for the explicit quarantine rules below.

```bash
unikegg download-kegg --all-organisms --interval 1.5 --attempts 8
unikegg download-uniprot --all-organisms --interval 1.5 --attempts 8
```

Resume interrupted work with the same command **without `--refresh`**. Completed files are reused only after request, checksum and content validation. UniProt retains interrupted refresh identity: it resumes saved new pages even if an older export still exists and refreshes exports not yet reached. Optional JSON restarts from the beginning of its file. Incomplete selections cannot be transformed. Operating-system locks are released when a process exits; lock files may remain. Managed sources cannot be transformed while a downloader modifies them.

UniProt TSV uses `/search`, stable accession ordering, pages of at most 500 proteins and checkpoints in `raw/uniprot/.pages/`. Each page records its checksum and URL; a damaged page invalidates itself and subsequent checkpoints. Columns, organisms, reviewed status, duplicate accessions, total count and release are verified before publishing the final gzip. A release change during acquisition requires a full refresh to avoid mixing releases across pages or organisms.

Optional UniProt JSON:

```bash
unikegg download-uniprot --organisms hsa,spo --include-json
```

JSON uses the original stream and restarts a failed file from its beginning. Transformation reads only TSV; the default avoids downloading unused JSON.

A separate directory is preferable for new data:

```bash
export UNIKEGG_DATA_DIR="$PWD/data-snapshot-2026-09"
unikegg download-kegg --all-organisms
unikegg download-uniprot --all-organisms
unikegg transform
```

Alternatively, `--refresh` updates files in the current directory and restarts UniProt checkpoints. Acquisition remains incomplete until finished. Previous final files are preserved if their replacement transfer fails. A valid gzip without verifiable provenance is downloaded again. Verified cache reuse is not a server freshness check.

KEGG retains downloaded batches under `raw/kegg/batches/`, then writes identifier-specific records with `details/{category}/active.json`. Transformation reads only active records, preventing duplicate older overlapping batches and preventing smaller selections from reintroducing old details. Legacy manual exports without an index retain their original duplicate checks.

## Memory, disk and validation

Genes and proteins are written incrementally. Major relationships are deduplicated and sorted in a temporary SQLite database with bounded cache, avoiding multiple in-memory copies. Validation and membership indexes remain in RAM, so memory use is not constant with record count. The target is the curated catalog, not every KEGG genome.

`TMPDIR` controls temporary storage. In Docker it is `/app/tmp`, mounted through the on-disk `etl_tmp` volume; large snapshots do not consume `/tmp` tmpfs. Raw checkpoints and batches remain available for resumption and consume space after completion; they are not deleted automatically. Use separate directories to retain or archive snapshots.

Offline tests cover selections of 1/2/16 organisms, repeated pipelines, empty reviewed responses, retries and cooldowns, concurrent locks, interrupted/damaged pages, release changes, incorrect counts, caches and KEGG details. Recorded live client checks covered two actual UniProt pages, one KEGG batch and subsequent offline cache reuse; these checks did not download the entire sixteen-organism dataset.

UniProt batch tests also cover all sixteen organisms in one run or cumulative sessions, smaller final batches, manual groups, optional JSON, invalid options, dry-run without changes, resumption of interrupted additions and release refreshes of earlier groups. These use simulated HTTP responses without downloading biological data.

Sources: [KEGG API and rate limits](https://www.kegg.jp/kegg/rest/), [KEGG API manual](https://www.kegg.jp/kegg/rest/keggapi.html), [UniProt API, pagination and streaming](https://academic.oup.com/nar/article/53/W1/W547/8126256).

## Direct KO, pathway and EC links

`download-kegg` also acquires `/link/pathway/ko` and `/link/enzyme/ko`, saving `relations/ko_pathway.tsv` and `relations/ko_ec.tsv`. These global relationships, like KO and reference pathway catalogs, are independent of organism selection. Verified caching, checksums and HTTP retries also apply to them. `transform` requires both files, normalizes identifiers and produces `orthology_pathway.tsv` and `orthology_ec.tsv`. Missing or inconsistent raw sources prevent publication. See the [migration procedure](orthology-migration.md) for older snapshots.

Before detail batches, acquisition reconciles missing gene/pathway catalog entries and refreshes relationship files that still disagree. It also refreshes KO catalogs referenced by missing IDs. Remaining KO–EC or gene–pathway assertions may be quarantined only when the absent KO or gene is independently confirmed HTTP 404. Evidence is stored in `missing_ko_checks.json` or `missing_gene_checks.json`; transformation warns and preserves the raw assertions. Other failures remain errors. See [operations](operations.md).
