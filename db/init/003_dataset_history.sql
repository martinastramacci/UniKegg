-- Application versions describe committed datasets, not upstream release numbers.
CREATE TABLE ETL_DATASET_HISTORY (
    version INT UNSIGNED PRIMARY KEY,
    dataset_sha256 CHAR(64) NOT NULL,
    dataset_kind VARCHAR(20) NOT NULL,
    applied_at DATETIME(6) NOT NULL,
    action VARCHAR(20) NOT NULL,
    version_label VARCHAR(128),
    manifest_json JSON,
    changes_json JSON,
    KEY (dataset_sha256)
) ENGINE = InnoDB;
