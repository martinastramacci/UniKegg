# Local verification record

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
