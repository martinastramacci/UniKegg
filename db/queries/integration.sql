-- Read-only integration queries. Select the target database before execution.
SELECT DISTINCT
    g.kegg_gene_id, g.symbol, p.accession, p.protein_name,
    p.sequence_length, pr.name AS pathway
FROM ORGANISMO o
JOIN GENE_KEGG g ON g.organism_id = o.organism_id
JOIN GENE_PATHWAY gp ON gp.kegg_gene_id = g.kegg_gene_id
JOIN PATHWAY_ORGANISMO po ON po.pathway_id = gp.pathway_id AND po.organism_id = o.organism_id
JOIN PATHWAY_RIFERIMENTO pr ON pr.map_id = po.map_id
JOIN GENE_PROTEINA m ON m.kegg_gene_id = g.kegg_gene_id
JOIN PROTEIN_UNIPROT p ON p.accession = m.accession AND p.organism_id = o.organism_id
WHERE o.kegg_code = 'hsa' AND pr.map_id = 'map00010'
ORDER BY g.kegg_gene_id, p.accession;



SELECT DISTINCT p.accession, p.protein_name, pe.ec_number, r.reaction_id, r.equation
FROM ORGANISMO o
JOIN GENE_KEGG g ON g.organism_id = o.organism_id
JOIN GENE_PATHWAY gp ON gp.kegg_gene_id = g.kegg_gene_id
JOIN PATHWAY_ORGANISMO po ON po.pathway_id = gp.pathway_id AND po.organism_id = o.organism_id
JOIN GENE_PROTEINA m ON m.kegg_gene_id = g.kegg_gene_id
JOIN PROTEIN_UNIPROT p ON p.accession = m.accession AND p.organism_id = o.organism_id
JOIN PROTEINA_EC pe ON pe.accession = p.accession
JOIN REAZIONE_EC re ON re.ec_number = pe.ec_number
JOIN REAZIONE_KEGG r ON r.reaction_id = re.reaction_id
JOIN PATHWAY_REAZIONE pr ON pr.reaction_id = r.reaction_id AND pr.map_id = po.map_id
WHERE
    o.kegg_code = 'hsa' AND po.map_id = 'map00010'
    AND REGEXP_LIKE(pe.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
ORDER BY p.accession, r.reaction_id, pe.ec_number;


WITH coppie AS (
    SELECT
        kegg_gene_id, accession,
        MAX(mapping_source = 'KEGG_CONV') AS da_kegg,
        MAX(mapping_source = 'UNIPROT_DR') AS da_uniprot
    FROM GENE_PROTEINA GROUP BY kegg_gene_id, accession
)
SELECT
    o.kegg_code, COUNT(*) AS coppie_totali,
    SUM(c.da_kegg = 1 AND c.da_uniprot = 1) AS entrambe,
    SUM(c.da_kegg = 1 AND c.da_uniprot = 0) AS solo_kegg,
    SUM(c.da_kegg = 0 AND c.da_uniprot = 1) AS solo_uniprot
FROM coppie c
JOIN GENE_KEGG g ON g.kegg_gene_id = c.kegg_gene_id
JOIN ORGANISMO o ON o.organism_id = g.organism_id
GROUP BY o.organism_id, o.kegg_code ORDER BY o.kegg_code;




SELECT r.reaction_id, r.name, r.equation
FROM REAZIONE_KEGG r
JOIN PATHWAY_REAZIONE pr ON pr.reaction_id = r.reaction_id
WHERE
    pr.map_id = 'map00010'
    AND EXISTS (
        SELECT 1 FROM REAZIONE_EC re
        WHERE re.reaction_id = r.reaction_id AND REGEXP_LIKE(re.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
    )
    AND NOT EXISTS (
        SELECT 1 FROM REAZIONE_EC re
        JOIN PROTEINA_EC pe ON pe.ec_number = re.ec_number
        JOIN PROTEIN_UNIPROT p ON p.accession = pe.accession
        JOIN ORGANISMO o ON o.organism_id = p.organism_id
        WHERE
            re.reaction_id = r.reaction_id AND REGEXP_LIKE(re.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
            AND o.kegg_code = 'hsa'
    )
ORDER BY r.reaction_id;


SELECT DISTINCT g.kegg_gene_id, k.ko_id, p.accession, t.go_id, t.name, pg.evidence_code
FROM GENE_KEGG g
JOIN ORGANISMO o ON o.organism_id = g.organism_id
JOIN GENE_ORTOLOGIA k ON k.kegg_gene_id = g.kegg_gene_id
JOIN GENE_PROTEINA m ON m.kegg_gene_id = g.kegg_gene_id
JOIN PROTEIN_UNIPROT p ON p.accession = m.accession AND p.organism_id = g.organism_id
JOIN PROTEINA_GO pg ON pg.accession = p.accession
JOIN TERMINE_GO t ON t.go_id = pg.go_id
WHERE o.kegg_code = 'hsa' AND t.namespace = 'MF'
ORDER BY g.kegg_gene_id, p.accession, t.go_id LIMIT 100;


SELECT p.accession, p.protein_name, COUNT(i.isoform_id) AS numero_isoforme
FROM PROTEIN_UNIPROT p
JOIN ORGANISMO o ON o.organism_id = p.organism_id
LEFT JOIN PROTEIN_ISOFORM i ON i.accession = p.accession
WHERE
    o.kegg_code = 'hsa' AND EXISTS (
        SELECT 1 FROM GENE_PROTEINA m
        JOIN GENE_KEGG g ON g.kegg_gene_id = m.kegg_gene_id AND g.organism_id = p.organism_id
        JOIN GENE_PATHWAY gp ON gp.kegg_gene_id = g.kegg_gene_id
        JOIN PATHWAY_ORGANISMO po ON po.pathway_id = gp.pathway_id AND po.organism_id = p.organism_id
        WHERE m.accession = p.accession AND po.map_id = 'map00010'
    )
GROUP BY p.accession, p.protein_name ORDER BY numero_isoforme DESC, p.accession;



WITH medie AS (
    SELECT organism_id, AVG(sequence_length) AS lunghezza_media
    FROM PROTEIN_UNIPROT GROUP BY organism_id
)
SELECT p.accession, o.kegg_code, p.sequence_length
FROM PROTEIN_UNIPROT p JOIN ORGANISMO o ON o.organism_id = p.organism_id
JOIN medie a ON a.organism_id = p.organism_id
WHERE
    EXISTS (SELECT 1 FROM GENE_PROTEINA m WHERE m.accession = p.accession)
    AND p.sequence_length > a.lunghezza_media
ORDER BY p.sequence_length DESC, p.accession LIMIT 100;


WITH copertura AS (
    SELECT
        g.organism_id, g.kegg_gene_id,
        EXISTS(SELECT 1 FROM GENE_PROTEINA m WHERE m.kegg_gene_id = g.kegg_gene_id) AS coperto
    FROM GENE_KEGG g WHERE g.gene_type = 'CDS'
)
SELECT
    o.kegg_code, COUNT(*) AS geni_cds, SUM(c.coperto) AS geni_coperti,
    ROUND(100.0 * SUM(c.coperto) / COUNT(*), 2) AS percentuale
FROM copertura c JOIN ORGANISMO o ON o.organism_id = c.organism_id
GROUP BY o.organism_id, o.kegg_code ORDER BY percentuale DESC;


SELECT po.pathway_id, pr.name, COUNT(DISTINCT p.accession) AS proteine
FROM PATHWAY_ORGANISMO po
JOIN ORGANISMO o ON o.organism_id = po.organism_id
JOIN PATHWAY_RIFERIMENTO pr ON pr.map_id = po.map_id
JOIN GENE_PATHWAY gp ON gp.pathway_id = po.pathway_id
JOIN GENE_KEGG g ON g.kegg_gene_id = gp.kegg_gene_id AND g.organism_id = po.organism_id
JOIN GENE_PROTEINA m ON m.kegg_gene_id = g.kegg_gene_id
JOIN PROTEIN_UNIPROT p ON p.accession = m.accession AND p.organism_id = po.organism_id
WHERE o.kegg_code = 'hsa'
GROUP BY po.pathway_id, pr.name HAVING COUNT(DISTINCT p.accession) >= 10
ORDER BY proteine DESC, po.pathway_id;



WITH conteggi AS (
    SELECT po.organism_id, po.pathway_id, COUNT(DISTINCT m.accession) AS proteine
    FROM PATHWAY_ORGANISMO po
    LEFT JOIN GENE_PATHWAY gp ON gp.pathway_id = po.pathway_id
    LEFT JOIN GENE_PROTEINA m ON m.kegg_gene_id = gp.kegg_gene_id
    GROUP BY po.organism_id, po.pathway_id
), classifica AS (
    SELECT *, DENSE_RANK() OVER (PARTITION BY organism_id ORDER BY proteine DESC) AS posizione
    FROM conteggi
)
SELECT o.kegg_code, c.pathway_id, c.proteine
FROM classifica c JOIN ORGANISMO o ON o.organism_id = c.organism_id
WHERE c.posizione = 1 ORDER BY o.kegg_code, c.pathway_id;


SELECT p.accession, p.protein_name, o.kegg_code
FROM PROTEIN_UNIPROT p JOIN ORGANISMO o ON o.organism_id = p.organism_id
WHERE
    EXISTS (SELECT 1 FROM GENE_PROTEINA m WHERE m.accession = p.accession)
    AND NOT EXISTS (SELECT 1 FROM PROTEINA_GO pg WHERE pg.accession = p.accession)
ORDER BY o.kegg_code, p.accession LIMIT 100;


SELECT o.kegg_code, COUNT(*) AS proteine_senza_mapping
FROM PROTEIN_UNIPROT p JOIN ORGANISMO o ON o.organism_id = p.organism_id
WHERE NOT EXISTS (SELECT 1 FROM GENE_PROTEINA m WHERE m.accession = p.accession)
GROUP BY o.organism_id, o.kegg_code ORDER BY proteine_senza_mapping DESC;


SELECT o.kegg_code, COUNT(*) AS geni_cds_non_coperti
FROM GENE_KEGG g JOIN ORGANISMO o ON o.organism_id = g.organism_id
WHERE
    g.gene_type = 'CDS'
    AND NOT EXISTS (SELECT 1 FROM GENE_PROTEINA m WHERE m.kegg_gene_id = g.kegg_gene_id)
GROUP BY o.organism_id, o.kegg_code ORDER BY geni_cds_non_coperti DESC;


SELECT m.kegg_gene_id, m.accession, p.protein_name
FROM GENE_PROTEINA m JOIN PROTEIN_UNIPROT p ON p.accession = m.accession
WHERE
    m.mapping_source = 'KEGG_CONV' AND NOT EXISTS (
        SELECT
            1 FROM GENE_PROTEINA x WHERE x.kegg_gene_id = m.kegg_gene_id
        AND x.accession = m.accession AND x.mapping_source = 'UNIPROT_DR'
    )
ORDER BY m.kegg_gene_id, m.accession LIMIT 100;


SELECT m.kegg_gene_id, m.accession, p.protein_name
FROM GENE_PROTEINA m JOIN PROTEIN_UNIPROT p ON p.accession = m.accession
WHERE
    m.mapping_source = 'UNIPROT_DR' AND NOT EXISTS (
        SELECT
            1 FROM GENE_PROTEINA x WHERE x.kegg_gene_id = m.kegg_gene_id
        AND x.accession = m.accession AND x.mapping_source = 'KEGG_CONV'
    )
ORDER BY m.kegg_gene_id, m.accession LIMIT 100;


SELECT g.kegg_gene_id, g.symbol, COUNT(DISTINCT m.accession) AS entry_uniprot
FROM GENE_KEGG g JOIN GENE_PROTEINA m ON m.kegg_gene_id = g.kegg_gene_id
GROUP BY g.kegg_gene_id, g.symbol HAVING COUNT(DISTINCT m.accession) > 1
ORDER BY entry_uniprot DESC, g.kegg_gene_id LIMIT 100;


SELECT p.accession, p.protein_name, COUNT(DISTINCT m.kegg_gene_id) AS geni_kegg
FROM PROTEIN_UNIPROT p JOIN GENE_PROTEINA m ON m.accession = p.accession
GROUP BY p.accession, p.protein_name HAVING COUNT(DISTINCT m.kegg_gene_id) > 1
ORDER BY geni_kegg DESC, p.accession LIMIT 100;



WITH proteine_ko AS (
    SELECT DISTINCT k.ko_id, p.accession, o.kegg_code
    FROM GENE_ORTOLOGIA k JOIN GENE_PROTEINA m ON m.kegg_gene_id = k.kegg_gene_id
    JOIN PROTEIN_UNIPROT p ON p.accession = m.accession
    JOIN ORGANISMO o ON o.organism_id = p.organism_id
    WHERE o.kegg_code IN ('hsa', 'mmu')
)
SELECT h.ko_id, h.accession AS proteina_umana, t.accession AS proteina_murina
FROM proteine_ko h JOIN proteine_ko t ON t.ko_id = h.ko_id
WHERE h.kegg_code = 'hsa' AND t.kegg_code = 'mmu'
ORDER BY h.ko_id, h.accession, t.accession LIMIT 100;


SELECT k.ko_id, COUNT(DISTINCT p.organism_id) AS organismi
FROM GENE_ORTOLOGIA k JOIN GENE_PROTEINA m ON m.kegg_gene_id = k.kegg_gene_id
JOIN PROTEIN_UNIPROT p ON p.accession = m.accession
GROUP BY k.ko_id
HAVING COUNT(DISTINCT p.organism_id) = (SELECT COUNT(*) FROM ORGANISMO)
ORDER BY k.ko_id;


WITH proteine_ko AS (
    SELECT DISTINCT k.ko_id, p.accession, p.sequence_length, o.kegg_code
    FROM GENE_ORTOLOGIA k JOIN GENE_PROTEINA m ON m.kegg_gene_id = k.kegg_gene_id
    JOIN PROTEIN_UNIPROT p ON p.accession = m.accession
    JOIN ORGANISMO o ON o.organism_id = p.organism_id
    WHERE o.kegg_code IN ('hsa', 'mmu')
)
SELECT
    h.ko_id, h.accession AS umana, t.accession AS murina,
    h.sequence_length AS lunghezza_umana, t.sequence_length AS lunghezza_murina
FROM proteine_ko h JOIN proteine_ko t ON t.ko_id = h.ko_id
WHERE
    h.kegg_code = 'hsa' AND t.kegg_code = 'mmu'
    AND GREATEST(h.sequence_length, t.sequence_length) >= 2 * LEAST(h.sequence_length, t.sequence_length)
ORDER BY h.ko_id, h.accession, t.accession LIMIT 100;


WITH provenienza AS (
    SELECT
        e.ec_number,
        EXISTS(SELECT 1 FROM PROTEINA_EC pe WHERE pe.ec_number = e.ec_number) AS u,
        EXISTS(SELECT 1 FROM REAZIONE_EC re WHERE re.ec_number = e.ec_number) AS k
    FROM NUMERO_EC e
)
SELECT
    CASE
        WHEN u AND k THEN 'ENTRAMBE' WHEN k THEN 'SOLO_KEGG'
        WHEN u THEN 'SOLO_UNIPROT' ELSE 'NON_REFERENZIATO'
    END AS contributo,
    COUNT(*) AS numeri_ec
FROM provenienza GROUP BY contributo ORDER BY contributo;


SELECT e.ec_number FROM NUMERO_EC e
WHERE
    EXISTS (SELECT 1 FROM REAZIONE_EC re WHERE re.ec_number = e.ec_number)
    AND NOT EXISTS (SELECT 1 FROM PROTEINA_EC pe WHERE pe.ec_number = e.ec_number)
ORDER BY e.ec_number LIMIT 100;


SELECT e.ec_number FROM NUMERO_EC e
WHERE
    EXISTS (SELECT 1 FROM PROTEINA_EC pe WHERE pe.ec_number = e.ec_number)
    AND NOT EXISTS (SELECT 1 FROM REAZIONE_EC re WHERE re.ec_number = e.ec_number)
ORDER BY e.ec_number LIMIT 100;


SELECT p.accession, p.protein_name, COUNT(DISTINCT pe.ec_number) AS attivita_ec
FROM PROTEIN_UNIPROT p JOIN PROTEINA_EC pe ON pe.accession = p.accession
WHERE
    REGEXP_LIKE(pe.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
    AND EXISTS (SELECT 1 FROM REAZIONE_EC re WHERE re.ec_number = pe.ec_number)
GROUP BY p.accession, p.protein_name HAVING COUNT(DISTINCT pe.ec_number) >= 2
ORDER BY attivita_ec DESC, p.accession LIMIT 100;



SELECT
    r.reaction_id, r.name, COUNT(DISTINCT p.organism_id) AS organismi,
    COUNT(DISTINCT p.accession) AS proteine_candidate
FROM REAZIONE_KEGG r
LEFT JOIN REAZIONE_EC re ON re.reaction_id = r.reaction_id AND REGEXP_LIKE(re.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
LEFT JOIN PROTEINA_EC pe ON pe.ec_number = re.ec_number
LEFT JOIN PROTEIN_UNIPROT p ON p.accession = pe.accession
GROUP BY r.reaction_id, r.name ORDER BY organismi DESC, r.reaction_id LIMIT 100;



SELECT DISTINCT p.accession, p.protein_name, pe.ec_number, r.reaction_id, r.equation
FROM PROTEIN_UNIPROT p JOIN ORGANISMO o ON o.organism_id = p.organism_id
JOIN PROTEINA_EC pe ON pe.accession = p.accession
JOIN REAZIONE_EC re ON re.ec_number = pe.ec_number
JOIN REAZIONE_KEGG r ON r.reaction_id = re.reaction_id
JOIN REAZIONE_COMPOSTO rc ON rc.reaction_id = r.reaction_id
WHERE o.kegg_code = 'hsa' AND rc.compound_id = 'C00002' AND REGEXP_LIKE(pe.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
ORDER BY p.accession, r.reaction_id, pe.ec_number LIMIT 100;


SELECT c.compound_id, c.name, COUNT(DISTINCT pe.accession) AS proteine_candidate
FROM COMPOSTO_KEGG c JOIN REAZIONE_COMPOSTO rc ON rc.compound_id = c.compound_id
JOIN REAZIONE_EC re ON re.reaction_id = rc.reaction_id
JOIN PROTEINA_EC pe ON pe.ec_number = re.ec_number
WHERE REGEXP_LIKE(re.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
GROUP BY c.compound_id, c.name ORDER BY proteine_candidate DESC, c.compound_id LIMIT 20;


WITH proteine_pathway AS (
    SELECT DISTINCT m.accession
    FROM PATHWAY_ORGANISMO po JOIN ORGANISMO o ON o.organism_id = po.organism_id
    JOIN GENE_PATHWAY gp ON gp.pathway_id = po.pathway_id
    JOIN GENE_PROTEINA m ON m.kegg_gene_id = gp.kegg_gene_id
    WHERE o.kegg_code = 'hsa' AND po.map_id = 'map00010'
)
SELECT t.go_id, t.name, COUNT(DISTINCT pg.accession) AS proteine_annotate
FROM proteine_pathway pp JOIN PROTEINA_GO pg ON pg.accession = pp.accession
JOIN TERMINE_GO t ON t.go_id = pg.go_id
WHERE t.namespace = 'BP'
GROUP BY t.go_id, t.name HAVING COUNT(DISTINCT pg.accession) >= 10
ORDER BY proteine_annotate DESC, t.go_id;



WITH appartenenze AS (
    SELECT DISTINCT m.accession, po.map_id
    FROM GENE_PROTEINA m JOIN GENE_PATHWAY gp ON gp.kegg_gene_id = m.kegg_gene_id
    JOIN PATHWAY_ORGANISMO po ON po.pathway_id = gp.pathway_id
    JOIN ORGANISMO o ON o.organism_id = po.organism_id
    WHERE o.kegg_code = 'hsa'
)
SELECT p.accession, p.protein_name
FROM PROTEIN_UNIPROT p
WHERE
    EXISTS (SELECT 1 FROM appartenenze a WHERE a.accession = p.accession AND a.map_id = 'map00010')
    AND EXISTS (SELECT 1 FROM appartenenze a WHERE a.accession = p.accession AND a.map_id = 'map00020')
    AND NOT EXISTS (SELECT 1 FROM appartenenze a WHERE a.accession = p.accession AND a.map_id = 'map00030')
ORDER BY p.accession;


SELECT DISTINCT p.accession, k.ko_id, r.reaction_id, pe.ec_number
FROM PROTEIN_UNIPROT p JOIN ORGANISMO o ON o.organism_id = p.organism_id
JOIN GENE_PROTEINA m ON m.accession = p.accession
JOIN GENE_KEGG g ON g.kegg_gene_id = m.kegg_gene_id AND g.organism_id = p.organism_id
JOIN GENE_ORTOLOGIA k ON k.kegg_gene_id = g.kegg_gene_id
JOIN ORTOLOGIA_REAZIONE kr ON kr.ko_id = k.ko_id
JOIN REAZIONE_KEGG r ON r.reaction_id = kr.reaction_id
JOIN REAZIONE_EC re ON re.reaction_id = r.reaction_id
JOIN PROTEINA_EC pe ON pe.accession = p.accession AND pe.ec_number = re.ec_number
WHERE o.kegg_code = 'hsa' AND REGEXP_LIKE(pe.ec_number, '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
ORDER BY p.accession, r.reaction_id, k.ko_id, pe.ec_number LIMIT 100;
