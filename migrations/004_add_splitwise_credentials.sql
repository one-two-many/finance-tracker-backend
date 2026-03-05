-- Migration: 004_add_splitwise_credentials.sql
-- Description: Add user_settings table for storing encrypted Splitwise API credentials
-- Date: 2026-02-20

-- User settings table for API credentials and preferences
CREATE TABLE IF NOT EXISTS user_settings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,

    -- Splitwise credentials (encrypted using Fernet cipher)
    splitwise_api_key VARCHAR(500),
    splitwise_is_active BOOLEAN DEFAULT false,
    splitwise_last_verified_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for faster lookups
CREATE INDEX IF NOT EXISTS idx_user_settings_user_id ON user_settings(user_id);

-- Comments for documentation
COMMENT ON TABLE user_settings IS 'Stores user preferences and encrypted API credentials for external services';
COMMENT ON COLUMN user_settings.splitwise_api_key IS 'Encrypted Splitwise API key using Fernet cipher derived from SECRET_KEY';
COMMENT ON COLUMN user_settings.splitwise_is_active IS 'Whether Splitwise integration is currently active for this user';
COMMENT ON COLUMN user_settings.splitwise_last_verified_at IS 'Timestamp of last successful API key verification';
