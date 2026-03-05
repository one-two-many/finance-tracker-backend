#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting database migrations...${NC}"

# Database connection details
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-financeuser}"
DB_NAME="${DB_NAME:-financedb}"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-/app/migrations}"

# Wait for database to be ready
echo -e "${YELLOW}Waiting for database to be ready...${NC}"
max_attempts=30
attempt=0

until PGPASSWORD=$POSTGRES_PASSWORD psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c '\q' 2>/dev/null; do
  attempt=$((attempt + 1))
  if [ $attempt -ge $max_attempts ]; then
    echo -e "${RED}Database connection failed after $max_attempts attempts${NC}"
    exit 1
  fi
  echo "Waiting for database... (attempt $attempt/$max_attempts)"
  sleep 2
done

echo -e "${GREEN}Database is ready!${NC}"

# Create migrations tracking table if it doesn't exist
echo -e "${YELLOW}Creating migrations tracking table...${NC}"
PGPASSWORD=$POSTGRES_PASSWORD psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" <<-EOSQL
  CREATE TABLE IF NOT EXISTS schema_migrations (
    id SERIAL PRIMARY KEY,
    version VARCHAR(255) UNIQUE NOT NULL,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
  );
EOSQL

# Function to check if migration has been applied
migration_applied() {
  local version=$1
  PGPASSWORD=$POSTGRES_PASSWORD psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM schema_migrations WHERE version = '$version';" | tr -d '[:space:]'
}

# Function to mark migration as applied
mark_migration_applied() {
  local version=$1
  PGPASSWORD=$POSTGRES_PASSWORD psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c \
    "INSERT INTO schema_migrations (version) VALUES ('$version');"
}

# Run migrations in order
migration_count=0
for migration_file in $(ls -1 "$MIGRATIONS_DIR"/*.sql 2>/dev/null | sort); do
  migration_name=$(basename "$migration_file")
  version="${migration_name%.sql}"

  # Check if migration has already been applied
  if [ "$(migration_applied "$version")" -gt 0 ]; then
    echo -e "${YELLOW}⏭  Skipping $migration_name (already applied)${NC}"
    continue
  fi

  echo -e "${YELLOW}▶  Running migration: $migration_name${NC}"

  # Run the migration
  if PGPASSWORD=$POSTGRES_PASSWORD psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f "$migration_file"; then
    # Mark as applied
    mark_migration_applied "$version"
    echo -e "${GREEN}✓  Successfully applied $migration_name${NC}"
    migration_count=$((migration_count + 1))
  else
    echo -e "${RED}✗  Failed to apply $migration_name${NC}"
    exit 1
  fi
done

if [ $migration_count -eq 0 ]; then
  echo -e "${GREEN}✓  All migrations are up to date (no new migrations to run)${NC}"
else
  echo -e "${GREEN}✓  Successfully applied $migration_count migration(s)${NC}"
fi

echo -e "${GREEN}Database migrations completed!${NC}"
