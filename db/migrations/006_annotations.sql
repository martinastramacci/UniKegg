-- Apply to the English schema before loading/updating a migrated TSV bundle.
ALTER TABLE PROTEIN_GO
DROP COLUMN evidence_code,
DROP COLUMN evidence_source;

ALTER TABLE EC_NUMBER
ADD COLUMN name TEXT,
ADD COLUMN catalytic_activity TEXT,
ADD COLUMN comment TEXT;
