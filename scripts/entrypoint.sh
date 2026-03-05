#!/bin/bash
set -e

echo "Starting Finance Tracker Backend..."

# Run migrations
echo "Running database migrations..."
bash /app/scripts/run_migrations.sh

# Start the application
echo "Starting FastAPI application..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
