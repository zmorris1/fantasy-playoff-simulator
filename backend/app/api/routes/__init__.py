"""
API route modules.
"""

from .auth_routes import router as auth_router
from .leagues_routes import router as leagues_router
from .simulations_routes import router as simulations_router
from .yahoo_oauth_routes import router as yahoo_oauth_router
from .cbs_oauth_routes import router as cbs_oauth_router

__all__ = ["auth_router", "leagues_router", "simulations_router", "yahoo_oauth_router", "cbs_oauth_router"]
