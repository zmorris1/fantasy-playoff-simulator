"""
Yahoo OAuth 2.0 utilities.

Handles authorization URL building, token exchange, and token refresh
for Yahoo Fantasy Sports API access.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple
from urllib.parse import urlencode

import httpx


class YahooOAuthError(Exception):
    """Raised when there's an error with Yahoo OAuth."""
    pass


class YahooTokenExpiredError(YahooOAuthError):
    """Raised when Yahoo tokens are expired and cannot be refreshed."""
    pass


# Yahoo OAuth configuration from environment
YAHOO_CLIENT_ID = os.getenv("YAHOO_CLIENT_ID", "")
YAHOO_CLIENT_SECRET = os.getenv("YAHOO_CLIENT_SECRET", "")
YAHOO_REDIRECT_URI = os.getenv("YAHOO_REDIRECT_URI", "http://localhost:5173/dashboard")

# Yahoo OAuth endpoints
YAHOO_AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


def build_authorization_url(state: str | None = None) -> Tuple[str, str]:
    """
    Build the Yahoo OAuth authorization URL.

    Args:
        state: Optional state parameter for CSRF protection.
               If not provided, a random state will be generated.

    Returns:
        Tuple of (authorization_url, state)

    Raises:
        YahooOAuthError: If Yahoo credentials are not configured
    """
    if not YAHOO_CLIENT_ID:
        raise YahooOAuthError("YAHOO_CLIENT_ID environment variable is not set")

    if state is None:
        state = secrets.token_urlsafe(32)

    params = {
        "client_id": YAHOO_CLIENT_ID,
        "redirect_uri": YAHOO_REDIRECT_URI,
        "response_type": "code",
        "scope": "fspt-r",  # Fantasy Sports read access
        "state": state,
    }

    url = f"{YAHOO_AUTH_URL}?{urlencode(params)}"
    return url, state


async def exchange_code_for_tokens(code: str) -> dict:
    """
    Exchange an authorization code for access and refresh tokens.

    Args:
        code: The authorization code from Yahoo OAuth callback

    Returns:
        Dict containing:
            - access_token: OAuth access token
            - refresh_token: OAuth refresh token
            - expires_at: datetime when the access token expires
            - yahoo_guid: User's Yahoo GUID (if available)

    Raises:
        YahooOAuthError: If token exchange fails
    """
    if not YAHOO_CLIENT_ID or not YAHOO_CLIENT_SECRET:
        raise YahooOAuthError("Yahoo OAuth credentials are not configured")

    data = {
        "client_id": YAHOO_CLIENT_ID,
        "client_secret": YAHOO_CLIENT_SECRET,
        "redirect_uri": YAHOO_REDIRECT_URI,
        "code": code,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                YAHOO_TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code != 200:
                error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                error_msg = error_data.get("error_description", response.text)
                raise YahooOAuthError(f"Token exchange failed: {error_msg}")

            token_data = response.json()

            # Calculate expiration time
            expires_in = token_data.get("expires_in", 3600)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            return {
                "access_token": token_data["access_token"],
                "refresh_token": token_data["refresh_token"],
                "expires_at": expires_at,
                "yahoo_guid": token_data.get("xoauth_yahoo_guid"),
            }

        except httpx.RequestError as e:
            raise YahooOAuthError(f"Network error during token exchange: {e}")


async def refresh_access_token(refresh_token: str) -> dict:
    """
    Refresh an expired access token using the refresh token.

    Args:
        refresh_token: The OAuth refresh token

    Returns:
        Dict containing:
            - access_token: New OAuth access token
            - refresh_token: New OAuth refresh token (may be same as input)
            - expires_at: datetime when the new access token expires

    Raises:
        YahooTokenExpiredError: If refresh token is invalid/expired
        YahooOAuthError: If token refresh fails for other reasons
    """
    if not YAHOO_CLIENT_ID or not YAHOO_CLIENT_SECRET:
        raise YahooOAuthError("Yahoo OAuth credentials are not configured")

    data = {
        "client_id": YAHOO_CLIENT_ID,
        "client_secret": YAHOO_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                YAHOO_TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code == 401:
                raise YahooTokenExpiredError(
                    "Refresh token is invalid or expired. Please reconnect your Yahoo account."
                )

            if response.status_code != 200:
                error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                error_msg = error_data.get("error_description", response.text)
                raise YahooOAuthError(f"Token refresh failed: {error_msg}")

            token_data = response.json()

            # Calculate expiration time
            expires_in = token_data.get("expires_in", 3600)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            return {
                "access_token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token", refresh_token),
                "expires_at": expires_at,
            }

        except httpx.RequestError as e:
            raise YahooOAuthError(f"Network error during token refresh: {e}")
