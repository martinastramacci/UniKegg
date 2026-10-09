# KEGG orthology relationships in the ER model

For installations with previous Italian table or TSV names, first follow the [English naming migration](english-names-migration.md).

[Original Italian notes](orthology-design-notes.it.md).

## Why orthology belongs in the pathway model

KEGG Orthology groups represent shared functional roles identified by KO codes such as `K00010`. Reference pathways describe biological networks independently of one selected organism. Linking KO groups directly to reference pathways makes it possible to project annotated organism genes onto those networks:

`GENE_KEGG → GENE_ORTHOLOGY → ORTHOLOGY_KEGG → ORTHOLOGY_PATHWAY → PATHWAY_REFERENCE`.

The relationship is many-to-many. A KO can participate in multiple pathways, and a pathway can contain multiple KO groups. The implementation uses the association table `ORTHOLOGY_PATHWAY(ko_id, map_id)`, with foreign keys to both catalogs and a composite primary key.

Without that association, gene-to-KO annotation alone cannot answer which reference pathways are explicitly associated with a KO. Traversing reaction or protein annotations can answer related questions, but those paths express different source assertions and cannot replace direct KEGG KO links.

Reference maps can represent KO, EC, reactions, compounds and other biological components. KO annotations are a central projection mechanism, but not every element of every map is a KO. The current implementation imports direct KEGG assertions rather than assuming every pathway component has the same type.

## Orthology and EC numbers

An EC number classifies catalytic activity. A multifunctional KO can have multiple EC numbers; the same EC classification can apply to different KO groups. This relationship is therefore also many-to-many and is stored in `ORTHOLOGY_EC(ko_id, ec_number)`, joining `ORTHOLOGY_KEGG` and `EC_NUMBER`.

These associations allow `EC → KO → Pathway` queries. Shared annotation does not by itself prove that every catalytic activity of a multifunctional KO is used in every associated pathway. An EC number need not uniquely identify a KEGG reaction. Direct KO–EC annotations remain distinct from protein–EC and reaction–EC annotations.

## Optional disease modeling

A possible future extension is KEGG disease data. Disease-to-pathway and disease-to-KO associations can both be many-to-many, depending on the explicit source relationships selected for import. This would require a disease catalog, association tables, validated raw acquisition, provenance and corresponding schema and dataset changes. Disease tables are not part of the current 22-table contract.

## Implemented behavior

The project imports `/link/pathway/ko` and `/link/enzyme/ko`. KO is the first raw column. It removes prefixes, normalizes reference pathway representations (`koNNNNN` and `mapNNNNN`) to `mapNNNNN`, preserves valid incomplete/preliminary EC classifications, and sorts and deduplicates associations.

Missing parents and malformed identifiers are errors. The only quarantine exceptions require independent matching KEGG HTTP 404 evidence and produce warnings while preserving raw files. No relationships are inferred to fill missing source assertions.

See [the ER diagram](schema.md), [source semantics and KO migration](orthology-migration.md), [English naming migration](english-names-migration.md), and [acquisition](acquisition.md) for the operational contract.
