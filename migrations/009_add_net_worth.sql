-- Migration: Add net worth feature — CD + HYSA account types, CD-specific columns, savings goals
-- Author: System
-- Date: 2026-04-20

-- Add CD + HYSA to accounttype enum (pattern matches 007)
ALTER TYPE accounttype ADD VALUE IF NOT EXISTS 'CD';
ALTER TYPE accounttype ADD VALUE IF NOT EXISTS 'HIGH_YIELD_SAVINGS';

-- Add CD-specific + HYSA-supporting columns on accounts.
-- interest_rate is shared between CD (for accrual formula) and HYSA (reference/display).
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS interest_rate NUMERIC(6,4);
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS maturity_date DATE;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS term_months INTEGER;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS inception_date DATE;

-- Savings goals
CREATE TABLE IF NOT EXISTS savings_goals (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(120) NOT NULL,
    target_amount NUMERIC(12,2) NOT NULL,
    target_date DATE,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_savings_goals_user_id ON savings_goals(user_id);

INSERT INTO schema_migrations (version) VALUES ('009_add_net_worth') ON CONFLICT (version) DO NOTHING;
