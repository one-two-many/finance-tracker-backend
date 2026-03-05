#!/bin/bash
# Script to verify database migrations have been applied correctly

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Finance Tracker Migration Verification ===${NC}\n"

# Check if running in Docker or local
if [ -f /.dockerenv ]; then
    # Running inside Docker container
    DB_HOST="${DB_HOST:-db}"
    DB_USER="${DB_USER:-financeuser}"
    DB_NAME="${DB_NAME:-financedb}"
    PSQL_CMD="psql -h $DB_HOST -U $DB_USER -d $DB_NAME"
else
    # Running locally - use docker exec
    CONTAINER_NAME="${CONTAINER_NAME:-finance-tracker-db}"
    PSQL_CMD="docker exec -i $CONTAINER_NAME psql -U financeuser -d financedb"
fi

# Function to run SQL query
run_query() {
    if [ -f /.dockerenv ]; then
        PGPASSWORD=$POSTGRES_PASSWORD psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -t -c "$1" 2>/dev/null || echo "0"
    else
        docker exec -i "$CONTAINER_NAME" psql -U financeuser -d financedb -t -c "$1" 2>/dev/null || echo "0"
    fi
}

# Check if database is accessible
echo -e "${YELLOW}1. Checking database connection...${NC}"
if run_query "SELECT 1;" | grep -q "1"; then
    echo -e "${GREEN}✓ Database is accessible${NC}\n"
else
    echo -e "${RED}✗ Cannot connect to database${NC}"
    exit 1
fi

# Check if schema_migrations table exists
echo -e "${YELLOW}2. Checking migration tracking table...${NC}"
if run_query "SELECT to_regclass('public.schema_migrations');" | grep -q "schema_migrations"; then
    echo -e "${GREEN}✓ schema_migrations table exists${NC}\n"
else
    echo -e "${RED}✗ schema_migrations table not found${NC}"
    echo -e "${YELLOW}  Run migrations first: docker-compose restart backend${NC}\n"
    exit 1
fi

# Check applied migrations
echo -e "${YELLOW}3. Checking applied migrations...${NC}"
APPLIED_MIGRATIONS=$(run_query "SELECT version FROM schema_migrations ORDER BY version;" | tr -d '[:space:]')

EXPECTED_MIGRATIONS=(
    "001_add_import_tracking"
    "002_add_default_parser_to_accounts"
    "003_add_balance_snapshots"
)

all_applied=true
for migration in "${EXPECTED_MIGRATIONS[@]}"; do
    if echo "$APPLIED_MIGRATIONS" | grep -q "$migration"; then
        echo -e "${GREEN}✓ $migration${NC}"
    else
        echo -e "${RED}✗ $migration (NOT APPLIED)${NC}"
        all_applied=false
    fi
done
echo ""

# Check base tables
echo -e "${YELLOW}4. Checking base tables...${NC}"
BASE_TABLES=("users" "accounts" "transactions" "categories")

for table in "${BASE_TABLES[@]}"; do
    if run_query "SELECT to_regclass('public.$table');" | grep -q "$table"; then
        echo -e "${GREEN}✓ $table table exists${NC}"
    else
        echo -e "${RED}✗ $table table not found${NC}"
        all_applied=false
    fi
done
echo ""

# Check migration 001 tables
echo -e "${YELLOW}5. Checking migration 001 tables...${NC}"
MIGRATION_001_TABLES=("import_sessions" "category_rules" "bank_parser_templates")

for table in "${MIGRATION_001_TABLES[@]}"; do
    if run_query "SELECT to_regclass('public.$table');" | grep -q "$table"; then
        echo -e "${GREEN}✓ $table table exists${NC}"
    else
        echo -e "${RED}✗ $table table not found${NC}"
        all_applied=false
    fi
done
echo ""

# Check migration 001 columns
echo -e "${YELLOW}6. Checking migration 001 columns...${NC}"
COLUMNS_TO_CHECK=(
    "transactions:import_session_id"
    "transactions:raw_data"
    "accounts:bank_name"
    "accounts:account_number_last4"
)

for column_check in "${COLUMNS_TO_CHECK[@]}"; do
    IFS=':' read -r table column <<< "$column_check"
    if run_query "SELECT column_name FROM information_schema.columns WHERE table_name='$table' AND column_name='$column';" | grep -q "$column"; then
        echo -e "${GREEN}✓ $table.$column exists${NC}"
    else
        echo -e "${RED}✗ $table.$column not found${NC}"
        all_applied=false
    fi
done
echo ""

# Check migration 002 columns
echo -e "${YELLOW}7. Checking migration 002 columns...${NC}"
if run_query "SELECT column_name FROM information_schema.columns WHERE table_name='accounts' AND column_name='default_parser';" | grep -q "default_parser"; then
    echo -e "${GREEN}✓ accounts.default_parser exists${NC}\n"
else
    echo -e "${RED}✗ accounts.default_parser not found${NC}\n"
    all_applied=false
fi

# Check migration 003 table
echo -e "${YELLOW}8. Checking migration 003 table...${NC}"
if run_query "SELECT to_regclass('public.account_balance_snapshots');" | grep -q "account_balance_snapshots"; then
    echo -e "${GREEN}✓ account_balance_snapshots table exists${NC}\n"
else
    echo -e "${RED}✗ account_balance_snapshots table not found${NC}\n"
    all_applied=false
fi

# Summary
echo -e "${YELLOW}=== Summary ===${NC}"
if [ "$all_applied" = true ]; then
    echo -e "${GREEN}✓ All migrations applied successfully!${NC}"
    echo -e "${GREEN}  Your database is ready to use.${NC}"
    exit 0
else
    echo -e "${RED}✗ Some migrations are missing${NC}"
    echo -e "${YELLOW}  Run: docker-compose restart backend${NC}"
    echo -e "${YELLOW}  Or check logs: docker logs finance-tracker-backend${NC}"
    exit 1
fi
