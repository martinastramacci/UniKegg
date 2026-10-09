-- Read-only integration queries. Select the target database before execution.
SELECT DISTINCT
    g.kegg_gene_id, g.symbol, p.accession, p.protein_name,
    p.sequence_length, pr.name AS pathway
FROM ORGANISM o
JOIN GENE_KEGG g ON g.organism_id = o.organism_id
JOIN GENE_PATHWAY gp ON gp.kegg_gene_id = g.kegg_gene_id
JOIN PATHWAY_ORGANISM po ON po.pathway_id = gp.pathway_id AND po.organism_id = o.organism_id
JOIN PATHWAY_REFERENCE pr ON pr.map_id = po.map_id
JOIN GENE_PROTEIN m ON m.kegg_gene_id = g.kegg_gene_id
JOIN PROTEIN_UNIPROT p ON p.accession = m.accession AND p.organism_id = o.organism_id
WHERE o.kegg_code = 'hsa' AND pr.map_id = 'map00010'
ORDER BY g.kegg_gene_id, p.accession;



SELECT DISTINCT p.accession, p.protein_name, pe.ec_number, r.reaction_id, r.equation
FROM ORGANISM o
JOIN GENE_KEGG g ON g.organism_id = o.organism_id
JOIN GENE_PATHWAY gp ON gp.kegg_gene_id = g.kegg_gene_id
JOIN PATHWAY_ORGANISM po ON po.pathway_id = gp.pathway_id AND po.organism_id = o.organism_id
JOIN GENE_PROTEIN m ON m.kegg_gene_id = g.kegg_gene_id
JOIN PROTEIN_UNIPROT p ON p.accession = m.accession AND p.organism_id = o.organism_id
JOIN PROTEIN_EC pe ON pe.accession = p.accession
JOIN REACTION_EC re ON re.ec_number = pe.ec_number
JOIN REACTION_KEGG r ON r.reaction_id = re.reaction_id
JOIN PATHWAY_REACTION pr ON pr.reaction_id = r.reaction_id AND pr.map_id = po.map_id
WHERE
    o.kegg_code = 'hsa' AND po.map_id = 'map00010'
    AND REGEXP_LIKE(pe.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
ORDER BY p.accession, r.reaction_id, pe.ec_number;


WITH pairs AS (
    SELECT
        kegg_gene_id, accession,
        MAX(mapping_source = 'KEGG_CONV') AS from_kegg,
        MAX(mapping_source = 'UNIPROT_DR') AS from_uniprot
    FROM GENE_PROTEIN GROUP BY kegg_gene_id, accession
)
SELECT
    o.kegg_code, COUNT(*) AS total_pairs,
    SUM(c.from_kegg = 1 AND c.from_uniprot = 1) AS both_sources,
    SUM(c.from_kegg = 1 AND c.from_uniprot = 0) AS kegg_only,
    SUM(c.from_kegg = 0 AND c.from_uniprot = 1) AS uniprot_only
FROM pairs c
JOIN GENE_KEGG g ON g.kegg_gene_id = c.kegg_gene_id
JOIN ORGANISM o ON o.organism_id = g.organism_id
GROUP BY o.organism_id, o.kegg_code ORDER BY o.kegg_code;




SELECT r.reaction_id, r.name, r.equation
FROM REACTION_KEGG r
JOIN PATHWAY_REACTION pr ON pr.reaction_id = r.reaction_id
WHERE
    pr.map_id = 'map00010'
    AND EXISTS (
        SELECT 1 FROM REACTION_EC re
        WHERE re.reaction_id = r.reaction_id AND REGEXP_LIKE(re.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
    )
    AND NOT EXISTS (
        SELECT 1 FROM REACTION_EC re
        JOIN PROTEIN_EC pe ON pe.ec_number = re.ec_number
        JOIN PROTEIN_UNIPROT p ON p.accession = pe.accession
        JOIN ORGANISM o ON o.organism_id = p.organism_id
        WHERE
            re.reaction_id = r.reaction_id AND REGEXP_LIKE(re.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
            AND o.kegg_code = 'hsa'
    )
ORDER BY r.reaction_id;


SELECT DISTINCT g.kegg_gene_id, k.ko_id, p.accession, t.go_id, t.name, pg.evidence_code
FROM GENE_KEGG g
JOIN ORGANISM o ON o.organism_id = g.organism_id
JOIN GENE_ORTHOLOGY k ON k.kegg_gene_id = g.kegg_gene_id
JOIN GENE_PROTEIN m ON m.kegg_gene_id = g.kegg_gene_id
JOIN PROTEIN_UNIPROT p ON p.accession = m.accession AND p.organism_id = g.organism_id
JOIN PROTEIN_GO pg ON pg.accession = p.accession
JOIN GO_TERM t ON t.go_id = pg.go_id
WHERE o.kegg_code = 'hsa' AND t.namespace = 'MF'
ORDER BY g.kegg_gene_id, p.accession, t.go_id LIMIT 100;


SELECT p.accession, p.protein_name, COUNT(i.isoform_id) AS isoform_count
FROM PROTEIN_UNIPROT p
JOIN ORGANISM o ON o.organism_id = p.organism_id
LEFT JOIN PROTEIN_ISOFORM i ON i.accession = p.accession
WHERE
    o.kegg_code = 'hsa' AND EXISTS (
        SELECT 1 FROM GENE_PROTEIN m
        JOIN GENE_KEGG g ON g.kegg_gene_id = m.kegg_gene_id AND g.organism_id = p.organism_id
        JOIN GENE_PATHWAY gp ON gp.kegg_gene_id = g.kegg_gene_id
        JOIN PATHWAY_ORGANISM po ON po.pathway_id = gp.pathway_id AND po.organism_id = p.organism_id
        WHERE m.accession = p.accession AND po.map_id = 'map00010'
    )
GROUP BY p.accession, p.protein_name ORDER BY isoform_count DESC, p.accession;



WITH averages AS (
    SELECT organism_id, AVG(sequence_length) AS average_length
    FROM PROTEIN_UNIPROT GROUP BY organism_id
)
SELECT p.accession, o.kegg_code, p.sequence_length
FROM PROTEIN_UNIPROT p JOIN ORGANISM o ON o.organism_id = p.organism_id
JOIN averages a ON a.organism_id = p.organism_id
WHERE
    EXISTS (SELECT 1 FROM GENE_PROTEIN m WHERE m.accession = p.accession)
    AND p.sequence_length > a.average_length
ORDER BY p.sequence_length DESC, p.accession LIMIT 100;


WITH coverage AS (
    SELECT
        g.organism_id, g.kegg_gene_id,
        EXISTS(SELECT 1 FROM GENE_PROTEIN m WHERE m.kegg_gene_id = g.kegg_gene_id) AS covered
    FROM GENE_KEGG g WHERE g.gene_type = 'CDS'
)
SELECT
    o.kegg_code, COUNT(*) AS cds_genes, SUM(c.covered) AS covered_genes,
    ROUND(100.0 * SUM(c.covered) / COUNT(*), 2) AS percentage
FROM coverage c JOIN ORGANISM o ON o.organism_id = c.organism_id
GROUP BY o.organism_id, o.kegg_code ORDER BY percentage DESC;


SELECT po.pathway_id, pr.name, COUNT(DISTINCT p.accession) AS proteins
FROM PATHWAY_ORGANISM po
JOIN ORGANISM o ON o.organism_id = po.organism_id
JOIN PATHWAY_REFERENCE pr ON pr.map_id = po.map_id
JOIN GENE_PATHWAY gp ON gp.pathway_id = po.pathway_id
JOIN GENE_KEGG g ON g.kegg_gene_id = gp.kegg_gene_id AND g.organism_id = po.organism_id
JOIN GENE_PROTEIN m ON m.kegg_gene_id = g.kegg_gene_id
JOIN PROTEIN_UNIPROT p ON p.accession = m.accession AND p.organism_id = po.organism_id
WHERE o.kegg_code = 'hsa'
GROUP BY po.pathway_id, pr.name HAVING COUNT(DISTINCT p.accession) >= 10
ORDER BY proteins DESC, po.pathway_id;



WITH counts AS (
    SELECT po.organism_id, po.pathway_id, COUNT(DISTINCT m.accession) AS proteins
    FROM PATHWAY_ORGANISM po
    LEFT JOIN GENE_PATHWAY gp ON gp.pathway_id = po.pathway_id
    LEFT JOIN GENE_PROTEIN m ON m.kegg_gene_id = gp.kegg_gene_id
    GROUP BY po.organism_id, po.pathway_id
), ranking AS (
    SELECT *, DENSE_RANK() OVER (PARTITION BY organism_id ORDER BY proteins DESC) AS rank_position
    FROM counts
)
SELECT o.kegg_code, c.pathway_id, c.proteins
FROM ranking c JOIN ORGANISM o ON o.organism_id = c.organism_id
WHERE c.rank_position = 1 ORDER BY o.kegg_code, c.pathway_id;


SELECT p.accession, p.protein_name, o.kegg_code
FROM PROTEIN_UNIPROT p JOIN ORGANISM o ON o.organism_id = p.organism_id
WHERE
    EXISTS (SELECT 1 FROM GENE_PROTEIN m WHERE m.accession = p.accession)
    AND NOT EXISTS (SELECT 1 FROM PROTEIN_GO pg WHERE pg.accession = p.accession)
ORDER BY o.kegg_code, p.accession LIMIT 100;


SELECT o.kegg_code, COUNT(*) AS unmapped_proteins
FROM PROTEIN_UNIPROT p JOIN ORGANISM o ON o.organism_id = p.organism_id
WHERE NOT EXISTS (SELECT 1 FROM GENE_PROTEIN m WHERE m.accession = p.accession)
GROUP BY o.organism_id, o.kegg_code ORDER BY unmapped_proteins DESC;


SELECT o.kegg_code, COUNT(*) AS uncovered_cds_genes
FROM GENE_KEGG g JOIN ORGANISM o ON o.organism_id = g.organism_id
WHERE
    g.gene_type = 'CDS'
    AND NOT EXISTS (SELECT 1 FROM GENE_PROTEIN m WHERE m.kegg_gene_id = g.kegg_gene_id)
GROUP BY o.organism_id, o.kegg_code ORDER BY uncovered_cds_genes DESC;


SELECT m.kegg_gene_id, m.accession, p.protein_name
FROM GENE_PROTEIN m JOIN PROTEIN_UNIPROT p ON p.accession = m.accession
WHERE
    m.mapping_source = 'KEGG_CONV' AND NOT EXISTS (
        SELECT
            1 FROM GENE_PROTEIN x WHERE x.kegg_gene_id = m.kegg_gene_id
        AND x.accession = m.accession AND x.mapping_source = 'UNIPROT_DR'
    )
ORDER BY m.kegg_gene_id, m.accession LIMIT 100;


SELECT m.kegg_gene_id, m.accession, p.protein_name
FROM GENE_PROTEIN m JOIN PROTEIN_UNIPROT p ON p.accession = m.accession
WHERE
    m.mapping_source = 'UNIPROT_DR' AND NOT EXISTS (
        SELECT
            1 FROM GENE_PROTEIN x WHERE x.kegg_gene_id = m.kegg_gene_id
        AND x.accession = m.accession AND x.mapping_source = 'KEGG_CONV'
    )
ORDER BY m.kegg_gene_id, m.accession LIMIT 100;


SELECT g.kegg_gene_id, g.symbol, COUNT(DISTINCT m.accession) AS uniprot_entries
FROM GENE_KEGG g JOIN GENE_PROTEIN m ON m.kegg_gene_id = g.kegg_gene_id
GROUP BY g.kegg_gene_id, g.symbol HAVING COUNT(DISTINCT m.accession) > 1
ORDER BY uniprot_entries DESC, g.kegg_gene_id LIMIT 100;


SELECT p.accession, p.protein_name, COUNT(DISTINCT m.kegg_gene_id) AS kegg_genes
FROM PROTEIN_UNIPROT p JOIN GENE_PROTEIN m ON m.accession = p.accession
GROUP BY p.accession, p.protein_name HAVING COUNT(DISTINCT m.kegg_gene_id) > 1
ORDER BY kegg_genes DESC, p.accession LIMIT 100;



WITH ko_proteins AS (
    SELECT DISTINCT k.ko_id, p.accession, o.kegg_code
    FROM GENE_ORTHOLOGY k JOIN GENE_PROTEIN m ON m.kegg_gene_id = k.kegg_gene_id
    JOIN PROTEIN_UNIPROT p ON p.accession = m.accession
    JOIN ORGANISM o ON o.organism_id = p.organism_id
    WHERE o.kegg_code IN ('hsa', 'mmu')
)
SELECT h.ko_id, h.accession AS human_protein, t.accession AS mouse_protein
FROM ko_proteins h JOIN ko_proteins t ON t.ko_id = h.ko_id
WHERE h.kegg_code = 'hsa' AND t.kegg_code = 'mmu'
ORDER BY h.ko_id, h.accession, t.accession LIMIT 100;


SELECT k.ko_id, COUNT(DISTINCT p.organism_id) AS organisms
FROM GENE_ORTHOLOGY k JOIN GENE_PROTEIN m ON m.kegg_gene_id = k.kegg_gene_id
JOIN PROTEIN_UNIPROT p ON p.accession = m.accession
GROUP BY k.ko_id
HAVING COUNT(DISTINCT p.organism_id) = (SELECT COUNT(*) FROM ORGANISM)
ORDER BY k.ko_id;


WITH ko_proteins AS (
    SELECT DISTINCT k.ko_id, p.accession, p.sequence_length, o.kegg_code
    FROM GENE_ORTHOLOGY k JOIN GENE_PROTEIN m ON m.kegg_gene_id = k.kegg_gene_id
    JOIN PROTEIN_UNIPROT p ON p.accession = m.accession
    JOIN ORGANISM o ON o.organism_id = p.organism_id
    WHERE o.kegg_code IN ('hsa', 'mmu')
)
SELECT
    h.ko_id, h.accession AS human, t.accession AS mouse,
    h.sequence_length AS human_length, t.sequence_length AS mouse_length
FROM ko_proteins h JOIN ko_proteins t ON t.ko_id = h.ko_id
WHERE
    h.kegg_code = 'hsa' AND t.kegg_code = 'mmu'
    AND GREATEST(h.sequence_length, t.sequence_length) >= 2 * LEAST(h.sequence_length, t.sequence_length)
ORDER BY h.ko_id, h.accession, t.accession LIMIT 100;


WITH provenance AS (
    SELECT
        e.ec_number,
        EXISTS(SELECT 1 FROM PROTEIN_EC pe WHERE pe.ec_number = e.ec_number) AS u,
        EXISTS(SELECT 1 FROM REACTION_EC re WHERE re.ec_number = e.ec_number) AS k
    FROM EC_NUMBER e
)
SELECT
    CASE
        WHEN u AND k THEN 'BOTH_SOURCES' WHEN k THEN 'KEGG_ONLY'
        WHEN u THEN 'UNIPROT_ONLY' ELSE 'UNREFERENCED'
    END AS contribution,
    COUNT(*) AS ec_numbers
FROM provenance GROUP BY contribution ORDER BY contribution;


SELECT e.ec_number FROM EC_NUMBER e
WHERE
    EXISTS (SELECT 1 FROM REACTION_EC re WHERE re.ec_number = e.ec_number)
    AND NOT EXISTS (SELECT 1 FROM PROTEIN_EC pe WHERE pe.ec_number = e.ec_number)
ORDER BY e.ec_number LIMIT 100;


SELECT e.ec_number FROM EC_NUMBER e
WHERE
    EXISTS (SELECT 1 FROM PROTEIN_EC pe WHERE pe.ec_number = e.ec_number)
    AND NOT EXISTS (SELECT 1 FROM REACTION_EC re WHERE re.ec_number = e.ec_number)
ORDER BY e.ec_number LIMIT 100;


SELECT p.accession, p.protein_name, COUNT(DISTINCT pe.ec_number) AS ec_activities
FROM PROTEIN_UNIPROT p JOIN PROTEIN_EC pe ON pe.accession = p.accession
WHERE
    REGEXP_LIKE(pe.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
    AND EXISTS (SELECT 1 FROM REACTION_EC re WHERE re.ec_number = pe.ec_number)
GROUP BY p.accession, p.protein_name HAVING COUNT(DISTINCT pe.ec_number) >= 2
ORDER BY ec_activities DESC, p.accession LIMIT 100;



SELECT
    r.reaction_id, r.name, COUNT(DISTINCT p.organism_id) AS organisms,
    COUNT(DISTINCT p.accession) AS candidate_proteins
FROM REACTION_KEGG r
LEFT JOIN REACTION_EC re ON re.reaction_id = r.reaction_id AND REGEXP_LIKE(re.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
LEFT JOIN PROTEIN_EC pe ON pe.ec_number = re.ec_number
LEFT JOIN PROTEIN_UNIPROT p ON p.accession = pe.accession
GROUP BY r.reaction_id, r.name ORDER BY organisms DESC, r.reaction_id LIMIT 100;



SELECT DISTINCT p.accession, p.protein_name, pe.ec_number, r.reaction_id, r.equation
FROM PROTEIN_UNIPROT p JOIN ORGANISM o ON o.organism_id = p.organism_id
JOIN PROTEIN_EC pe ON pe.accession = p.accession
JOIN REACTION_EC re ON re.ec_number = pe.ec_number
JOIN REACTION_KEGG r ON r.reaction_id = re.reaction_id
JOIN REACTION_COMPOUND rc ON rc.reaction_id = r.reaction_id
WHERE o.kegg_code = 'hsa' AND rc.compound_id = 'C00002' AND REGEXP_LIKE(pe.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
ORDER BY p.accession, r.reaction_id, pe.ec_number LIMIT 100;


SELECT c.compound_id, c.name, COUNT(DISTINCT pe.accession) AS candidate_proteins
FROM COMPOUND_KEGG c JOIN REACTION_COMPOUND rc ON rc.compound_id = c.compound_id
JOIN REACTION_EC re ON re.reaction_id = rc.reaction_id
JOIN PROTEIN_EC pe ON pe.ec_number = re.ec_number
WHERE REGEXP_LIKE(re.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
GROUP BY c.compound_id, c.name ORDER BY candidate_proteins DESC, c.compound_id LIMIT 20;


WITH pathway_proteins AS (
    SELECT DISTINCT m.accession
    FROM PATHWAY_ORGANISM po JOIN ORGANISM o ON o.organism_id = po.organism_id
    JOIN GENE_PATHWAY gp ON gp.pathway_id = po.pathway_id
    JOIN GENE_PROTEIN m ON m.kegg_gene_id = gp.kegg_gene_id
    WHERE o.kegg_code = 'hsa' AND po.map_id = 'map00010'
)
SELECT t.go_id, t.name, COUNT(DISTINCT pg.accession) AS annotated_proteins
FROM pathway_proteins pp JOIN PROTEIN_GO pg ON pg.accession = pp.accession
JOIN GO_TERM t ON t.go_id = pg.go_id
WHERE t.namespace = 'BP'
GROUP BY t.go_id, t.name HAVING COUNT(DISTINCT pg.accession) >= 10
ORDER BY annotated_proteins DESC, t.go_id;



WITH memberships AS (
    SELECT DISTINCT m.accession, po.map_id
    FROM GENE_PROTEIN m JOIN GENE_PATHWAY gp ON gp.kegg_gene_id = m.kegg_gene_id
    JOIN PATHWAY_ORGANISM po ON po.pathway_id = gp.pathway_id
    JOIN ORGANISM o ON o.organism_id = po.organism_id
    WHERE o.kegg_code = 'hsa'
)
SELECT p.accession, p.protein_name
FROM PROTEIN_UNIPROT p
WHERE
    EXISTS (SELECT 1 FROM memberships a WHERE a.accession = p.accession AND a.map_id = 'map00010')
    AND EXISTS (SELECT 1 FROM memberships a WHERE a.accession = p.accession AND a.map_id = 'map00020')
    AND NOT EXISTS (SELECT 1 FROM memberships a WHERE a.accession = p.accession AND a.map_id = 'map00030')
ORDER BY p.accession;


SELECT DISTINCT p.accession, k.ko_id, r.reaction_id, pe.ec_number
FROM PROTEIN_UNIPROT p JOIN ORGANISM o ON o.organism_id = p.organism_id
JOIN GENE_PROTEIN m ON m.accession = p.accession
JOIN GENE_KEGG g ON g.kegg_gene_id = m.kegg_gene_id AND g.organism_id = p.organism_id
JOIN GENE_ORTHOLOGY k ON k.kegg_gene_id = g.kegg_gene_id
JOIN ORTHOLOGY_REACTION kr ON kr.ko_id = k.ko_id
JOIN REACTION_KEGG r ON r.reaction_id = kr.reaction_id
JOIN REACTION_EC re ON re.reaction_id = r.reaction_id
JOIN PROTEIN_EC pe ON pe.accession = p.accession AND pe.ec_number = re.ec_number
WHERE o.kegg_code = 'hsa' AND REGEXP_LIKE(pe.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
ORDER BY p.accession, r.reaction_id, k.ko_id, pe.ec_number LIMIT 100;
