-- Migration: Self-managed accounts (HYSA/CD/etc. with no CSV feed)
-- Adds an is_self_managed flag on accounts + an account_rate_history table
-- so the accrual engine can compute correct monthly interest across
-- rate changes.
-- Date: 2026-04-21

-- Flag: true when the user enters balance changes manually and the system
-- auto-accrues monthly interest. Orthogonal to account_type.
ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS is_self_managed BOOLEAN NOT NULL DEFAULT FALSE;

-- Rate history: one row per rate effective period. Lookup for month M uses
-- the row with the largest effective_date <= first_of_M.
CREATE TABLE IF NOT EXISTS account_rate_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    rate NUMERIC(6, 4) NOT NULL,
    effective_date DATE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rate_hist_account_date
    ON account_rate_history(account_id, effective_date);
CREATE INDEX IF NOT EXISTS idx_rate_hist_user_id
    ON account_rate_history(user_id);

INSERT INTO schema_migrations (version) VALUES ('010_add_self_managed_accounts') ON CONFLICT (version) DO NOTHING;
