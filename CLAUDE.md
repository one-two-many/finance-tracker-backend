# CLAUDE.md — finance-tracker-backend

## Quick Reference

```bash
# Run locally (requires Python 3.11+)
python3 -m uvicorn app.main:app --reload

# Syntax check a file
python3 -m py_compile app/path/to/file.py

# Run tests
pytest

# Docker (from project root)
docker-compose up -d
docker-compose logs -f backend
docker-compose restart backend
```

## Project Structure

```
app/
├── main.py                  # FastAPI app, CORS, router registration
├── core/
│   ├── config.py            # Settings (pydantic-settings, reads .env)
│   ├── database.py          # SQLAlchemy engine, SessionLocal, Base, get_db
│   └── security.py          # JWT (python-jose) and password hashing (passlib)
├── api/                     # Route handlers (all under /api/v1)
│   ├── dependencies.py      # get_current_user (OAuth2 + JWT)
│   ├── health.py            # GET /health
│   ├── auth.py              # /auth/* — register, login, user info
│   ├── accounts.py          # /accounts/* — CRUD
│   ├── transactions.py      # /transactions/* — CRUD, CSV import, merge
│   ├── parsers.py           # /parsers/* — list & detect parsers
│   ├── categories.py        # /categories/* — categories + rules
│   ├── analytics.py         # /analytics/* — Sankey diagram data
│   └── settings.py          # /settings/* — Splitwise integration
├── models/                  # SQLAlchemy ORM models
│   ├── user.py              # User (JWT auth)
│   ├── account.py           # Financial accounts (bank_name, last4)
│   ├── transaction.py       # Transactions (amount, type, splitwise_split)
│   ├── category.py          # Hierarchical categories with colors/icons
│   ├── import_session.py    # CSV import session tracking
│   ├── category_rule.py     # Auto-categorization rules
│   ├── bank_parser_template.py
│   ├── account_balance_snapshot.py
│   └── user_settings.py
├── schemas/                 # Pydantic request/response models
│   ├── csv_import.py
│   └── parser.py
└── services/
    ├── csv_import/          # Strategy-pattern CSV parser system
    │   ├── __init__.py      # initialize_parsers() — registers all parsers
    │   ├── base_parser.py   # CSVParser ABC, ParsedTransaction dataclass
    │   ├── parser_registry.py  # Singleton registry
    │   ├── import_service.py   # Orchestrates preview + confirm flow
    │   ├── category_suggester.py
    │   ├── transfer_detector.py
    │   ├── legacy.py
    │   └── parsers/         # Individual bank parsers
    │       ├── amex_parser.py
    │       ├── chase_bank_parser.py
    │       ├── chase_bank_pdf_parser.py
    │       ├── chase_credit_parser.py
    │       ├── discover_bank_parser.py
    │       ├── discover_savings_parser.py
    │       ├── capital_one_parser.py
    │       ├── citi_parser.py
    │       ├── boa_parser.py
    │       └── wells_fargo_parser.py
    ├── sankey_service.py
    └── splitwise_service.py
migrations/                  # SQL migration files (001–006)
scripts/
    ├── entrypoint.sh        # Docker entrypoint (runs migrations then uvicorn)
    ├── run_migrations.sh    # Automated migration runner
    └── verify_migrations.sh
```

## Tech Stack

- **Python 3.11+**, **FastAPI 0.115**, **Pydantic v2**, **SQLAlchemy 2.0**
- **PostgreSQL** (production via Docker) / SQLite (local dev fallback)
- **JWT auth** via python-jose + passlib (bcrypt)
- **Splitwise SDK** (`splitwise==3.0.0`)
- **PDF parsing**: pdfplumber + pdfminer.six

## Key Patterns

### Every endpoint uses `get_current_user`
All API routes depend on `get_current_user` for authentication and always filter by `current_user.id` for data isolation.

### Transaction model has two FK paths to Account
`account_id` and `transfer_to_account_id` both reference `accounts.id`. Always use explicit `onclause` in joins:
```python
.join(Account, Transaction.account_id == Account.id)
```
Omitting the onclause causes `AmbiguousForeignKeysError`.

### CSV parser registration (two files)
When adding a new parser:
1. Create `parsers/my_bank_parser.py` inheriting `CSVParser`
2. Export from `parsers/__init__.py`
3. Import and instantiate in `csv_import/__init__.py` → `initialize_parsers()`

### Pydantic schemas vs inline dicts
Some endpoints (transactions list, merge) return raw dicts; others use Pydantic response models from `schemas/`. Follow the existing pattern for the router you're modifying.

### TransactionType enum
Defined in `models/transaction.py`. When comparing in queries, handle both string and enum forms:
```python
if txn.transaction_type in ("income", TransactionType.INCOME):
```

## Database & Migrations

- Migrations live in `migrations/` as raw SQL files (`001_*.sql` through `006_*.sql`)
- Tracked in `schema_migrations` table — **only has a `version` column** (no `description`)
- Run automatically on Docker container startup via `scripts/run_migrations.sh`
- Always use `IF NOT EXISTS` and `ON CONFLICT (version) DO NOTHING`
- Insert format: `INSERT INTO schema_migrations (version) VALUES ('00X') ON CONFLICT (version) DO NOTHING;`

```bash
# Check migration status
docker exec -it finance-tracker-db psql -U financeuser -d financedb -c "SELECT * FROM schema_migrations;"

# Run a migration manually
docker exec -i finance-tracker-db psql -U financeuser -d financedb < migrations/006_add_global_categories.sql
```

## Environment Variables

| Variable | Default | Notes |
|---|---|---|
| `FT_DATABASE_URL` | `sqlite:///./finance.db` | PostgreSQL in prod |
| `SECRET_KEY` | (required) | JWT signing key |
| `ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | |
| `ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Comma-separated CORS origins |
| `DEBUG` | `false` | Enables SQLAlchemy echo |

## Common Gotchas

- **Sankey income/expense name collision**: Income and expense category nodes must never share the same name — causes infinite recursion in the frontend Sankey chart. See `sankey_service.py` for dedup logic.
- **Splitwise `createExpense()` returns a tuple** `(Expense, Errors)` in SDK v3 — always check `isinstance(result, tuple)`.
- **Splitwise participant errors**: Current user must be included; don't add them twice when iterating group members.
- **`schema_migrations` has no `description` column** — INSERT only the `version` value.
