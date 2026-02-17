"""
Fantasy Basketball Playoff Simulator - FastAPI Application

Main entry point for the web API.
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import auth_router, leagues_router, simulations_router, yahoo_oauth_router, cbs_oauth_router
from .db import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    try:
        await create_tables()
    except Exception as e:
        import logging
        logging.getLogger("app").error(f"Failed to create tables on startup: {e}")
        # App still starts — DB may become available later
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
