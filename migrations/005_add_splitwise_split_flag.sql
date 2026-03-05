-- Migration 005: Add splitwise_split flag to transactions
-- Marks transactions that have been pushed to Splitwise

INSERT INTO schema_migrations (version) VALUES ('005')
ON CONFLICT (version) DO NOTHING;

ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS splitwise_split BOOLEAN NOT NULL DEFAULT FALSE;
