# Local verification record

## Dataset synchronization and version history — 2026-09-30

| Check | Result |
|---|---|
| Python 3.14.6 complete unit/regression suite | 184 passed |
| Real isolated MySQL 8.4.11 update tests | Additions, modifications, deletions, unique-value swaps and full field comparisons passed |
| Selection and dependencies | Changed organism annotations and removal of an entire organism preserved referential integrity |
| Preview and repeat update | Dry-run preserved persistent data/schema/history; repeated current snapshot did not create a version |
| Concurrent updates | Two concurrent calls produced exactly one new version |
| Rollback | Injected failures after domain synchronization and after history/state writes restored the previous committed state |
| Legacy migration | Baseline fingerprint/date preserved; dry-run did not migrate; failed update left no committed version; retry succeeded |
| History and validation | UTC dates, labels, old-fingerprint rejection, manual field-drift detection and invalid-bundle rejection passed |
| Ruff, SQLFluff, ingestion projections and diff whitespace | Passed |

Tests used synthetic records on a temporary native MySQL server. No existing biological database was synchronized. The configured Docker MySQL 8.0.44 workflow includes these regressions but was not executed locally; native 8.4.11 verification does not establish an executed Docker result. See the [update guide](updates.md) for commands and version semantics.

## Curated acquisition update — 2026-09-30

Verified after adding a 16-organism curated catalog (ten defaults plus six additions):

| Check | Result |
|---|---|
| Python 3.14.6 unit/regression suite | 166 passed, including 1/2/16-organism transformations and legacy manifests |
| HTTP failure simulations | Retry-After seconds/date, persistent cooldown, permanent errors, interrupted/damaged pages, release/count mismatch and duplicate accession rejection passed |
| Source/cache checks | Query/hash verification, managed-source locks, selected-file manifests and active KEGG detail index passed |
| Live UniProt client | Two real one-record pages for reviewed human P04637/P38398 merged and validated; reuse made no HTTP calls |
| Live KEGG client | R00010/C00001 batch validated; reuse made no HTTP calls |
| Six added organisms | Five reviewed protein/gene matches per organism agreed between UniProt cross-references and KEGG conversion |
| Real isolated MySQL 8.4.11 | Original round-trip, rollback, concurrent load, fingerprint rejection and thirty-query regressions passed |
| Ruff, SQLFluff and ingestion projections | Passed |

No complete biological dataset for all sixteen organisms was downloaded. New catalog checks are samples and do not assert complete reviewed coverage. MySQL testing used a temporary server without a network port and left existing databases untouched. This native 8.4.11 result does not substitute for Docker's configured 8.0.44 integration job. The new disk-backed temporary volume is covered by static configuration tests; container runtime execution is not claimed here. Python 3.11/3.12 remain the CI targets.

See the [acquisition guide](acquisition.md) for scope, commands and recovery behavior.

## Historical prepared snapshot

Verified on 2026-09-19 against the prepared local snapshot:

| Check | Result |
|---|---|
| Regenerate all 20 TSVs from the selected original raw snapshot | Passed; SHA-256 matches for every prepared TSV |
| Reviewed-only manifest, primary keys, references, species consistency, sequence lengths | Passed |
| Schema initialization on isolated MySQL 8.0.44 | Passed |
| Full transactional ingestion with warnings treated as failures | Passed; 2,006,370 rows |
| Compare every protein sequence and name with the TSV | Passed; 89,601 proteins |
| Long canonical sequences | Q8WZ42: 34,350 residues; A2ASS6: 35,213 residues |
| Synthetic CSV-style quote preservation | Passed |
| Repeated load | Passed; verification without duplicate insertion |
| Deliberate uniqueness warning | Rejected; previously loaded tables rolled back |
| Thirty cross-resource queries on the loaded snapshot | Passed |
| Ruff and SQLFluff MySQL checks, including ingestion projections | Passed |
| Unit and static infrastructure tests | 17 passed |
| Editable package installation and both acquisition dry runs | Passed |

Native tests used a temporary database server and did not modify an existing working database. Docker execution was not performed locally because Docker was unavailable. Static Compose/workflow checks and native MySQL tests do not substitute for an executed Linux-container test. The provided CI workflow defines that test; no remote GitHub Actions run is claimed by this record.

Live upstream acquisition was not repeated during these checks. Acquisition dry runs inspect the planned requests; they do not validate current upstream API availability or authorization. This record is specific to the snapshot and code under verification, not a production certification.
