"""
Fantasy Basketball Playoff Simulator - FastAPI Application

Main entry point for the web API.
"""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import auth_router, leagues_router, simulations_router, yahoo_oauth_router, cbs_oauth_router
from .db import create_tables

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Starting application...")
    logger.info(f"DATABASE_URL configured: {'DATABASE_URL' in os.environ}")
    logger.info(f"PORT: {os.environ.get('PORT', 'not set')}")
    try:
        await create_tables()
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create tables on startup: {e}")
        # App still starts — DB may become available later
    logger.info("Application startup complete")
    yield
    # Shutdown


# Create FastAPI app
app = FastAPI(
    title="Fantasy Basketball Playoff Simulator",
    description="Monte Carlo simulation to calculate playoff probabilities for fantasy basketball leagues.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# CORS configuration
# In production, replace with specific frontend URL
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router, prefix="/api")
app.include_router(leagues_router, prefix="/api")
app.include_router(simulations_router, prefix="/api")
app.include_router(yahoo_oauth_router, prefix="/api")
app.include_router(cbs_oauth_router, prefix="/api")


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "Fantasy Basketball Playoff Simulator API",
        "version": "1.0.0",
        "docs": "/api/docs",
        "health": "/api/health"
    }
