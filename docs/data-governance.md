# Data governance

## Selection and provenance

The protein scope is UniProtKB/Swiss-Prot, never UniProtKB/TrEMBL. Requests include `reviewed:true`, exported rows must report `Reviewed=reviewed`, and processed protein accessions must belong to the verified export. The existing biological identifiers are preserved. Organism membership is checked across gene-to-protein and gene-to-pathway bridges. Unresolved relationships are excluded by transformation and reported in local artifacts.

The ten configured KEGG organism codes are `hsa`, `mmu`, `rno`, `dre`, `dme`, `cel`, `ath`, `sce`, `eco` and `bsu`. Genome/strain identifiers come from upstream records rather than an assumption that every identifier represents an entire species. The snapshot includes reference vocabularies that may be broader than the observed protein set.

An accession match validates dataset selection, not sequence identity against every upstream release. The reviewed export, TSV hashes and acquisition metadata should be retained together for reproducibility. Do not merge exports from different releases without a deliberate reconciliation policy. Manifests are integrity metadata, not signed attestations.

## Relational semantics

`GENE_PROTEINA.mapping_source` distinguishes KEGG conversion mappings from UniProt cross-references. Two rows for the same gene/protein pair can represent two source assertions, not two distinct proteins. Count distinct pairs or accessions when that is the analytical intent.

KEGG annotations, GO evidence and EC assignments are integrated associations. A shared EC number or pathway assignment does not establish reaction direction, flux or experimental activity. Isoform metadata does not imply that all isoform sequences are stored: canonical sequences reside in `PROTEIN_UNIPROT`; isoform records describe identifiers and sequence status.

The preserved `PROTEINA_GO` grain is one accession/GO pair with one evidence-code/source representation. The current schema does not retain an arbitrary history of competing evidence assertions. Temporal versioning, source-release reconciliation and evidence multiplicity require explicit schema extensions.

## Distribution boundaries

Git ignores all real raw exports, TSVs, manifests, dumps and local reports. Container builds exclude `data/` and `artifacts/`. Do not bypass these controls with forced Git additions or bake real data into a public image. Synthetic CI fixtures are generated from invented records and explicitly labelled `synthetic`.

Consult the [KEGG legal notice](https://www.kegg.jp/kegg/legal.html), [KEGG licensing information](https://kegg.net/en/licensing.html) and [UniProt data policy](https://www.uniprot.org/api-documentation/support-data) before distribution. Attribution and usage permissions remain upstream obligations. This repository does not grant rights to redistribute KEGG content. The code and data have separate licensing considerations; no blanket third-party data license is asserted.
