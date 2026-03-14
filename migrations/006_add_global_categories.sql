INSERT INTO schema_migrations (version) VALUES ('006')
ON CONFLICT (version) DO NOTHING;

ALTER TABLE categories
ADD COLUMN IF NOT EXISTS is_global BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_categories_is_global ON categories (is_global) WHERE is_global = TRUE;
