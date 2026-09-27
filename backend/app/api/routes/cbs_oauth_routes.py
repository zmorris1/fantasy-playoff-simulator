"""
CBS Sports OAuth API routes.

Handles CBS Sports OAuth 2.0 authentication flow for accessing
CBS Sports Fantasy leagues.
"""

from .oauth_routes import build_oauth_router
from ...core import cbs_oauth
from ...db import CBSCredentialRepository


router = build_oauth_router(
    provider="cbs",
    display_name="CBS Sports",
    oauth=cbs_oauth,
    oauth_error=cbs_oauth.CBSOAuthError,
    repo_class=CBSCredentialRepository,
    account_field="cbs_user_id",
)
