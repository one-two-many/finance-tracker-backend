-- Migration: Add import tracking tables and fields
-- Date: 2026-02-17
-- Description: Add support for CSV import sessions, category rules, and parser templates

-- Create import_sessions table
CREATE TABLE IF NOT EXISTS import_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    filename VARCHAR(255),
    parser_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'completed',
    total_rows INTEGER DEFAULT 0,
    created_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_import_sessions_user_id ON import_sessions(user_id);
CREATE INDEX idx_import_sessions_account_id ON import_sessions(account_id);

-- Create category_rules table
CREATE TABLE IF NOT EXISTS category_rules (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    pattern VARCHAR(255) NOT NULL,
    pattern_type VARCHAR(20) DEFAULT 'keyword',
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_category_rules_user_id ON category_rules(user_id);
CREATE INDEX idx_category_rules_category_id ON category_rules(category_id);
CREATE INDEX idx_category_rules_priority ON category_rules(priority);

-- Create bank_parser_templates table
CREATE TABLE IF NOT EXISTS bank_parser_templates (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    bank_name VARCHAR(100) NOT NULL,
    parser_type VARCHAR(50) NOT NULL,
    column_mapping JSONB NOT NULL,
    date_format VARCHAR(50),
    is_default BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_bank_parser_templates_user_id ON bank_parser_templates(user_id);

-- Add new fields to transactions table
ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS import_session_id INTEGER REFERENCES import_sessions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS raw_data JSONB;

CREATE INDEX IF NOT EXISTS idx_transactions_import_session ON transactions(import_session_id);

-- Add new fields to accounts table
ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS bank_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS account_number_last4 VARCHAR(4);
