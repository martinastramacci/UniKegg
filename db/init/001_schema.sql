-- MySQL 8.0 schema; the database is selected by the container initializer.
CREATE TABLE ORGANISMO (
    organism_id INT UNSIGNED PRIMARY KEY,
    kegg_code VARCHAR(5) NOT NULL UNIQUE,
    taxonomy_id INT UNSIGNED NOT NULL UNIQUE,
    scientific_name VARCHAR(200) NOT NULL,
    CHECK (taxonomy_id > 0),
    CHECK (REGEXP_LIKE(kegg_code, '^[a-z][a-z0-9]{2,4}$'))
);

CREATE TABLE GENE_KEGG (
    kegg_gene_id VARCHAR(40) PRIMARY KEY,
    organism_id INT UNSIGNED NOT NULL,
    gene_type VARCHAR(16) NOT NULL,
    symbol VARCHAR(255),
    definition TEXT,

    FOREIGN KEY (organism_id) REFERENCES ORGANISMO (organism_id)
);

CREATE TABLE PROTEIN_UNIPROT (
    accession VARCHAR(10) PRIMARY KEY,
    organism_id INT UNSIGNED NOT NULL,
    entry_name VARCHAR(30) NOT NULL UNIQUE,
    protein_name TEXT,
    sequence_length INT UNSIGNED NOT NULL,
    molecular_mass INT UNSIGNED NOT NULL,
    protein_existence VARCHAR(50) NOT NULL,
    sequence_version INT UNSIGNED NOT NULL,

    amino_acid_sequence MEDIUMTEXT NOT NULL,
    KEY (organism_id),
    FOREIGN KEY (organism_id) REFERENCES ORGANISMO (organism_id),
    CHECK (sequence_length > 0 AND molecular_mass > 0)

);

CREATE TABLE ORTOLOGIA_KEGG (
    ko_id CHAR(6) PRIMARY KEY,
    name VARCHAR(300),
    definition TEXT
);

CREATE TABLE PATHWAY_RIFERIMENTO (
    map_id CHAR(8) PRIMARY KEY,
    name VARCHAR(500) NOT NULL
);

CREATE TABLE PATHWAY_ORGANISMO (
    pathway_id VARCHAR(12) PRIMARY KEY,
    organism_id INT UNSIGNED NOT NULL,
    map_id CHAR(8) NOT NULL,
    UNIQUE (organism_id, map_id),
    FOREIGN KEY (organism_id) REFERENCES ORGANISMO (organism_id),
    FOREIGN KEY (map_id) REFERENCES PATHWAY_RIFERIMENTO (map_id)
);

CREATE TABLE REAZIONE_KEGG (
    reaction_id CHAR(6) PRIMARY KEY,
    name TEXT,
    definition TEXT,
    equation TEXT
);

CREATE TABLE COMPOSTO_KEGG (
    compound_id CHAR(6) PRIMARY KEY,
    name TEXT NOT NULL,
    formula VARCHAR(500),
    exact_mass DECIMAL(24, 10),
    molecular_weight DECIMAL(24, 10)
);

CREATE TABLE TERMINE_GO (
    go_id CHAR(10) PRIMARY KEY,
    name VARCHAR(500) NOT NULL,
    namespace ENUM('BP', 'MF', 'CC') NOT NULL
);

CREATE TABLE NUMERO_EC (
    ec_number VARCHAR(20) PRIMARY KEY
);

CREATE TABLE PROTEIN_ISOFORM (
    isoform_id VARCHAR(25) PRIMARY KEY,
    accession VARCHAR(10) NOT NULL,
    ordinal INT UNSIGNED NOT NULL,
    name VARCHAR(500) NOT NULL,
    sequence_status ENUM('DISPLAYED', 'EXTERNAL', 'NOT_DESCRIBED', 'DESCRIBED') NOT NULL,
    note TEXT,
    UNIQUE (accession, ordinal),
    FOREIGN KEY (accession) REFERENCES PROTEIN_UNIPROT (accession) ON DELETE CASCADE
);

CREATE TABLE GENE_PROTEINA (
    kegg_gene_id VARCHAR(40),
    accession VARCHAR(10),
    mapping_source ENUM('KEGG_CONV', 'UNIPROT_DR') NOT NULL,
    PRIMARY KEY (kegg_gene_id, accession, mapping_source),
    KEY (accession),
    FOREIGN KEY (kegg_gene_id) REFERENCES GENE_KEGG (kegg_gene_id) ON DELETE CASCADE,
    FOREIGN KEY (accession) REFERENCES PROTEIN_UNIPROT (accession) ON DELETE CASCADE
);

CREATE TABLE GENE_ORTOLOGIA (
    kegg_gene_id VARCHAR(40),
    ko_id CHAR(6),
    PRIMARY KEY (kegg_gene_id, ko_id),
    KEY (ko_id),
    FOREIGN KEY (kegg_gene_id) REFERENCES GENE_KEGG (kegg_gene_id) ON DELETE CASCADE,
    FOREIGN KEY (ko_id) REFERENCES ORTOLOGIA_KEGG (ko_id)
);

CREATE TABLE GENE_PATHWAY (
    kegg_gene_id VARCHAR(40),
    pathway_id VARCHAR(12),
    PRIMARY KEY (kegg_gene_id, pathway_id),
    FOREIGN KEY (kegg_gene_id) REFERENCES GENE_KEGG (kegg_gene_id) ON DELETE CASCADE,
    FOREIGN KEY (pathway_id) REFERENCES PATHWAY_ORGANISMO (pathway_id)
);

CREATE TABLE ORTOLOGIA_REAZIONE (
    ko_id CHAR(6),
    reaction_id CHAR(6),
    PRIMARY KEY (ko_id, reaction_id),
    FOREIGN KEY (ko_id) REFERENCES ORTOLOGIA_KEGG (ko_id),
    FOREIGN KEY (reaction_id) REFERENCES REAZIONE_KEGG (reaction_id)
);

CREATE TABLE PATHWAY_REAZIONE (
    map_id CHAR(8),
    reaction_id CHAR(6),
    PRIMARY KEY (map_id, reaction_id),
    KEY (reaction_id),
    FOREIGN KEY (map_id) REFERENCES PATHWAY_RIFERIMENTO (map_id),
    FOREIGN KEY (reaction_id) REFERENCES REAZIONE_KEGG (reaction_id)
);

CREATE TABLE REAZIONE_COMPOSTO (
    reaction_id CHAR(6),
    compound_id CHAR(6),
    PRIMARY KEY (reaction_id, compound_id),
    FOREIGN KEY (reaction_id) REFERENCES REAZIONE_KEGG (reaction_id),
    FOREIGN KEY (compound_id) REFERENCES COMPOSTO_KEGG (compound_id)
);

CREATE TABLE PROTEINA_GO (
    accession VARCHAR(10),
    go_id CHAR(10),
    evidence_code VARCHAR(12),
    evidence_source VARCHAR(100),
    PRIMARY KEY (accession, go_id),
    FOREIGN KEY (accession) REFERENCES PROTEIN_UNIPROT (accession) ON DELETE CASCADE,
    FOREIGN KEY (go_id) REFERENCES TERMINE_GO (go_id)
);

CREATE TABLE PROTEINA_EC (
    accession VARCHAR(10),
    ec_number VARCHAR(20),
    PRIMARY KEY (accession, ec_number),
    FOREIGN KEY (accession) REFERENCES PROTEIN_UNIPROT (accession) ON DELETE CASCADE,
    FOREIGN KEY (ec_number) REFERENCES NUMERO_EC (ec_number)
);

CREATE TABLE REAZIONE_EC (
    reaction_id CHAR(6),
    ec_number VARCHAR(20),
    PRIMARY KEY (reaction_id, ec_number),
    FOREIGN KEY (reaction_id) REFERENCES REAZIONE_KEGG (reaction_id),
    FOREIGN KEY (ec_number) REFERENCES NUMERO_EC (ec_number)
);
