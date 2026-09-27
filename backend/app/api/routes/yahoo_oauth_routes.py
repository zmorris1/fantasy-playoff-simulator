"""
Yahoo OAuth API routes.

Handles Yahoo OAuth 2.0 authentication flow for accessing
private Yahoo Fantasy leagues.
"""

from .oauth_routes import build_oauth_router
from ...core import yahoo_oauth
from ...db import YahooCredentialRepository


router = build_oauth_router(
    provider="yahoo",
    display_name="Yahoo",
    oauth=yahoo_oauth,
    oauth_error=yahoo_oauth.YahooOAuthError,
    repo_class=YahooCredentialRepository,
    account_field="yahoo_guid",
)
