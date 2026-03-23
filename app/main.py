import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import engine, Base
from app.core.telemetry import init_telemetry
from app.core.logging import get_logger
from app.api import health, auth, accounts, transactions, parsers, categories, analytics, settings as settings_api

logger = get_logger(__name__)

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    debug=settings.DEBUG
)

# Initialize OpenTelemetry (traces, metrics, logs)
init_telemetry(app)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log every request with method, path, status, and duration."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000

    # Skip noisy health checks
    if request.url.path not in ("/health", "/"):
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration_ms, 2),
            client=request.client.host if request.client else None,
        )

    return response


# Include routers
app.include_router(health.router, tags=["health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(accounts.router, prefix="/api/v1/accounts", tags=["accounts"])
app.include_router(transactions.router, prefix="/api/v1/transactions", tags=["transactions"])
app.include_router(parsers.router, prefix="/api/v1/parsers", tags=["parsers"])
app.include_router(categories.router, prefix="/api/v1/categories", tags=["categories"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(settings_api.router, prefix="/api/v1/settings", tags=["settings"])

logger.info("app_started", version=settings.VERSION)


@app.get("/")
async def root():
    return {
        "message": "Finance Tracker API",
        "version": settings.VERSION,
        "docs": "/docs"
    }
