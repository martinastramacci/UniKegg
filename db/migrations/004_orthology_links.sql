-- Apply once to the existing selected UniKegg database before loading a 22-table bundle.
-- Additive DDL: existing biological rows and version metadata are preserved.
-- IF NOT EXISTS permits resuming an interrupted migration; it does not repair schema drift.
CREATE TABLE IF NOT EXISTS ORTOLOGIA_PATHWAY (
    ko_id CHAR(6) NOT NULL,
    map_id CHAR(8) NOT NULL,
    PRIMARY KEY (ko_id, map_id),
    KEY (map_id),
    FOREIGN KEY (ko_id) REFERENCES ORTOLOGIA_KEGG (ko_id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
    FOREIGN KEY (map_id) REFERENCES PATHWAY_RIFERIMENTO (map_id)
    ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS ORTOLOGIA_EC (
    ko_id CHAR(6) NOT NULL,
    ec_number VARCHAR(20) NOT NULL,
    PRIMARY KEY (ko_id, ec_number),
    KEY (ec_number),
    FOREIGN KEY (ko_id) REFERENCES ORTOLOGIA_KEGG (ko_id)
    ON DELETE RESTRICT ON UPDATE RESTRICT,
    FOREIGN KEY (ec_number) REFERENCES NUMERO_EC (ec_number)
    ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB;
