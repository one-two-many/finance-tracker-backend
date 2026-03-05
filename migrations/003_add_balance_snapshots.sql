-- Migration: Add account balance snapshots table
-- Purpose: Track account balances at specific points in time for net worth calculations
-- Author: System
-- Date: 2026-02-19

-- Create account_balance_snapshots table
CREATE TABLE IF NOT EXISTS account_balance_snapshots (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    import_session_id INTEGER REFERENCES import_sessions(id) ON DELETE SET NULL,

    -- Balance information
    balance NUMERIC(12, 2) NOT NULL,
    snapshot_date DATE NOT NULL,
    snapshot_type VARCHAR(20) NOT NULL CHECK (snapshot_type IN ('start', 'end', 'manual')),

    -- Period information (for monthly snapshots)
    period_year INTEGER,
    period_month INTEGER,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE,

    -- Indexes for efficient queries
    CONSTRAINT account_balance_snapshots_user_id_idx FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT account_balance_snapshots_account_id_idx FOREIGN KEY (account_id) REFERENCES accounts(id)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_balance_snapshots_user_id ON account_balance_snapshots(user_id);
CREATE INDEX IF NOT EXISTS idx_balance_snapshots_account_id ON account_balance_snapshots(account_id);
CREATE INDEX IF NOT EXISTS idx_balance_snapshots_snapshot_date ON account_balance_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_balance_snapshots_period ON account_balance_snapshots(period_year, period_month);
CREATE INDEX IF NOT EXISTS idx_balance_snapshots_import_session ON account_balance_snapshots(import_session_id);

-- Create unique constraint to prevent duplicate snapshots for same account/date/type
CREATE UNIQUE INDEX IF NOT EXISTS idx_balance_snapshots_unique
    ON account_balance_snapshots(account_id, snapshot_date, snapshot_type);

-- Add comment to table
COMMENT ON TABLE account_balance_snapshots IS 'Stores account balance snapshots at specific points in time for net worth tracking and historical analysis';
