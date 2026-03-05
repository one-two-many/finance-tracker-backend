from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import engine, Base
from app.api import health, auth, accounts, transactions, parsers, categories, analytics, settings as settings_api

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    debug=settings.DEBUG
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, tags=["health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(accounts.router, prefix="/api/v1/accounts", tags=["accounts"])
app.include_router(transactions.router, prefix="/api/v1/transactions", tags=["transactions"])
app.include_router(parsers.router, prefix="/api/v1/parsers", tags=["parsers"])
app.include_router(categories.router, prefix="/api/v1/categories", tags=["categories"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])
app.include_router(settings_api.router, prefix="/api/v1/settings", tags=["settings"])


@app.get("/")
async def root():
    return {
        "message": "Finance Tracker API",
        "version": settings.VERSION,
        "docs": "/docs"
    }
