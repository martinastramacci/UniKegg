-- Operational state is separate from the twenty domain tables.
CREATE TABLE ETL_LOAD_STATE (
    singleton_id TINYINT PRIMARY KEY,
    dataset_sha256 CHAR(64) NOT NULL,
    dataset_kind VARCHAR(20) NOT NULL,
    loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (singleton_id = 1)
);
