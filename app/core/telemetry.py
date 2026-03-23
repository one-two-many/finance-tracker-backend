"""
OpenTelemetry initialization — traces, metrics, and logs export via OTLP gRPC.

Call `init_telemetry(app)` once from main.py at startup.
"""

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

try:
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
except ImportError:
    from opentelemetry.exporter.otlp.proto.http.log_exporter import OTLPLogExporter

from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry._logs import set_logger_provider
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor

import logging
import os

from app.core.config import settings
from app.core.logging import setup_logging, get_logger


logger = get_logger(__name__)


def _build_resource() -> Resource:
    """Build the OTel resource with service name and optional attributes."""
    attrs = {SERVICE_NAME: settings.OTEL_SERVICE_NAME}

    if settings.OTEL_RESOURCE_ATTRIBUTES:
        for pair in settings.OTEL_RESOURCE_ATTRIBUTES.split(","):
            if "=" in pair:
                key, value = pair.split("=", 1)
                attrs[key.strip()] = value.strip()

    return Resource.create(attrs)


def init_telemetry(app=None):
    """
    Initialize OpenTelemetry with traces, metrics, and log export.

    Args:
        app: FastAPI application instance (for auto-instrumentation)
    """
    # Always set up structured logging
    setup_logging(settings.LOG_LEVEL)

    if not settings.OTEL_ENABLED or not settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        logger.info(
            "otel_disabled",
            reason="OTEL_ENABLED=false or OTEL_EXPORTER_OTLP_ENDPOINT not set",
        )
        return

    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT.rstrip("/")
    resource = _build_resource()

    # Prevent the OTel SDK from reading OTEL_EXPORTER_OTLP_ENDPOINT directly
    # from the OS environment — we configure endpoints explicitly via code.
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    os.environ.pop("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", None)
    os.environ.pop("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", None)
    os.environ.pop("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", None)

    logger.info(
        "otel_init_start",
        endpoint=endpoint,
        service_name=settings.OTEL_SERVICE_NAME,
    )

    # --- Traces ---
    trace_exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
    trace.set_tracer_provider(tracer_provider)

    # --- Metrics ---
    metric_exporter = OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics")
    metric_reader = PeriodicExportingMetricReader(
        metric_exporter, export_interval_millis=30000
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # --- Logs ---
    log_exporter = OTLPLogExporter(endpoint=f"{endpoint}/v1/logs")
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(logger_provider)

    # Attach OTel log handler to Python root logger so structlog output
    # is also exported via OTLP to Loki
    otel_handler = LoggingHandler(
        level=logging.NOTSET, logger_provider=logger_provider
    )
    logging.getLogger().addHandler(otel_handler)

    # --- Auto-instrumentation ---
    if app:
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="health",
        )

    SQLAlchemyInstrumentor().instrument()
    RequestsInstrumentor().instrument()
    LoggingInstrumentor().instrument(set_logging_format=False)

    logger.info("otel_init_complete")


# --- Custom metrics ---
def get_meter():
    return metrics.get_meter(settings.OTEL_SERVICE_NAME)


# Pre-defined business metrics (initialized lazily)
_csv_import_counter = None
_csv_import_rows_histogram = None
_splitwise_expense_counter = None


def get_csv_import_counter():
    global _csv_import_counter
    if _csv_import_counter is None:
        _csv_import_counter = get_meter().create_counter(
            "csv_import_total",
            description="Number of CSV import operations",
            unit="1",
        )
    return _csv_import_counter


def get_csv_import_rows_histogram():
    global _csv_import_rows_histogram
    if _csv_import_rows_histogram is None:
        _csv_import_rows_histogram = get_meter().create_histogram(
            "csv_import_transactions_count",
            description="Number of transactions per CSV import",
            unit="1",
        )
    return _csv_import_rows_histogram


def get_splitwise_expense_counter():
    global _splitwise_expense_counter
    if _splitwise_expense_counter is None:
        _splitwise_expense_counter = get_meter().create_counter(
            "splitwise_expense_created_total",
            description="Number of Splitwise expenses created",
            unit="1",
        )
    return _splitwise_expense_counter
