# Database Migrations

This directory contains SQL migration scripts for the Finance Tracker database.

## Automated Migrations (Recommended)

**Migrations run automatically when using Docker Compose!**

When you start the services with `docker-compose up`, the backend container automatically:
1. Waits for the database to be ready
2. Creates a `schema_migrations` tracking table
3. Runs all pending migrations in order
4. Skips migrations that have already been applied
5. Starts the FastAPI application

No manual intervention needed! Just run:
```bash
docker-compose up -d
```

### Migration Tracking

The system uses a `schema_migrations` table to track which migrations have been applied. This ensures:
- Migrations are only run once
- Safe to restart containers (won't re-run completed migrations)
- Easy to see migration status:

```bash
docker exec -it finance-tracker-db psql -U financeuser -d financedb -c "SELECT * FROM schema_migrations;"
```

## Manual Migration Options

### Option 1: Manual SQL Execution

Connect to your PostgreSQL database and run the migration files in order:

```bash
psql -U financeuser -d financedb -f migrations/001_add_import_tracking.sql
psql -U financeuser -d financedb -f migrations/002_add_default_parser_to_accounts.sql
psql -U financeuser -d financedb -f migrations/003_add_balance_snapshots.sql
```

### Option 2: Docker (Manual)

If you need to run migrations manually:

```bash
docker exec -i finance-tracker-db psql -U financeuser -d financedb < finance-tracker-backend/migrations/001_add_import_tracking.sql
docker exec -i finance-tracker-db psql -U financeuser -d financedb < finance-tracker-backend/migrations/002_add_default_parser_to_accounts.sql
docker exec -i finance-tracker-db psql -U financeuser -d financedb < finance-tracker-backend/migrations/003_add_balance_snapshots.sql
```

### Option 3: Migration Script

Run the migration script directly:

```bash
cd finance-tracker-backend
DB_HOST=localhost DB_PORT=5432 DB_USER=financeuser DB_NAME=financedb POSTGRES_PASSWORD=financepass bash scripts/run_migrations.sh
```

## Migration Files

- `001_add_import_tracking.sql` - Adds tables for import sessions, category rules, parser templates, and updates transactions/accounts tables
- `002_add_default_parser_to_accounts.sql` - Adds default_parser field to accounts for linking accounts to CSV parsers
- `003_add_balance_snapshots.sql` - Adds account_balance_snapshots table for tracking balances over time

## Adding New Migrations

1. Create a new file with the next sequence number: `00X_description.sql`
2. Use `IF NOT EXISTS` clauses for safety (idempotent)
3. Test the migration locally
4. The automated system will pick it up on next container restart

## Rollback

To rollback migrations, you'll need to:
1. Manually drop the tables and columns added
2. Remove the entry from `schema_migrations` table
3. Use caution with production data

## Troubleshooting

**"Table already exists" errors:**
- This is normal if migrations were previously run manually
- The automated system will skip already-applied migrations

**"Connection refused" errors:**
- Ensure the database container is running: `docker ps | grep finance-tracker-db`
- Check database health: `docker exec finance-tracker-db pg_isready -U financeuser`

**View migration logs:**
```bash
docker logs finance-tracker-backend
```
