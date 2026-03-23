#!/bin/bash
set -e

echo "Starting Finance Tracker Backend..."

# Run migrations
echo "Running database migrations..."
bash /app/scripts/run_migrations.sh

# Start the application with OpenTelemetry auto-instrumentation
echo "Starting FastAPI application..."
if [ -n "$OTEL_EXPORTER_OTLP_ENDPOINT" ]; then
    echo "OpenTelemetry enabled — endpoint: $OTEL_EXPORTER_OTLP_ENDPOINT"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
