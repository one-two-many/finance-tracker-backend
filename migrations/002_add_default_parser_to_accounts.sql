-- Migration: Add default_parser field to accounts table
-- Description: Links accounts to their preferred CSV parser for easier imports
-- Date: 2026-02-18

-- Add default_parser column to accounts table
ALTER TABLE accounts
ADD COLUMN IF NOT EXISTS default_parser VARCHAR(50);

-- Add comment explaining the column
COMMENT ON COLUMN accounts.default_parser IS 'Default CSV parser for this account (e.g., amex, discover_bank, chase_credit)';

-- No data migration needed - all existing accounts will have NULL default_parser
