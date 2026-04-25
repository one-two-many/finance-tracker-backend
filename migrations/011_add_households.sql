-- 011_add_households.sql
-- Adds households, members, invitations, and joint-account FK on accounts.

DO $$ BEGIN
    CREATE TYPE household_role AS ENUM ('admin', 'member');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE invitation_status AS ENUM ('pending', 'accepted', 'declined', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS households (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    created_by_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS household_members (
    id SERIAL PRIMARY KEY,
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role household_role NOT NULL DEFAULT 'member',
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (household_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_household_members_user_id ON household_members(user_id);

CREATE TABLE IF NOT EXISTS household_invitations (
    id SERIAL PRIMARY KEY,
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    inviter_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    invitee_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status invitation_status NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    responded_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pending_invite
    ON household_invitations(household_id, invitee_user_id)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS ix_invitations_invitee
    ON household_invitations(invitee_user_id);

ALTER TABLE accounts
    ADD COLUMN IF NOT EXISTS household_id INTEGER
    REFERENCES households(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS ix_accounts_household_id ON accounts(household_id);

INSERT INTO schema_migrations (version) VALUES ('011') ON CONFLICT (version) DO NOTHING;
