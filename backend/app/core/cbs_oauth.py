"""
CBS Sports OAuth 2.0 utilities.

Handles authorization URL building, token exchange, and token refresh
for CBS Sports Fantasy API access.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple
from urllib.parse import urlencode

import httpx


class CBSOAuthError(Exception):
    """Raised when there's an error with CBS OAuth."""
    pass


class CBSTokenExpiredError(CBSOAuthError):
    """Raised when CBS tokens are expired and cannot be refreshed."""
    pass


# CBS OAuth configuration from environment
CBS_CLIENT_ID = os.getenv("CBS_CLIENT_ID", "")
CBS_CLIENT_SECRET = os.getenv("CBS_CLIENT_SECRET", "")
CBS_REDIRECT_URI = os.getenv("CBS_REDIRECT_URI", "http://localhost:5173/dashboard")

# CBS OAuth endpoints
CBS_AUTH_URL = "https://www.cbssports.com/oauth/authorize"
CBS_TOKEN_URL = "https://api.cbssports.com/oauth/token"


def build_authorization_url(state: str | None = None) -> Tuple[str, str]:
    """
    Build the CBS OAuth authorization URL.

    Args:
        state: Optional state parameter for CSRF protection.
               If not provided, a random state will be generated.

    Returns:
        Tuple of (authorization_url, state)

    Raises:
        CBSOAuthError: If CBS credentials are not configured
    """
    if not CBS_CLIENT_ID:
        raise CBSOAuthError("CBS_CLIENT_ID environment variable is not set")

    if state is None:
        state = secrets.token_urlsafe(32)

    params = {
        "client_id": CBS_CLIENT_ID,
        "redirect_uri": CBS_REDIRECT_URI,
        "response_type": "code",
        "scope": "fantasy",
        "state": state,
    }

    url = f"{CBS_AUTH_URL}?{urlencode(params)}"
    return url, state


async def exchange_code_for_tokens(code: str) -> dict:
    """
    Exchange an authorization code for access and refresh tokens.

    Args:
        code: The authorization code from CBS OAuth callback

    Returns:
        Dict containing:
            - access_token: OAuth access token
            - refresh_token: OAuth refresh token
            - expires_at: datetime when the access token expires
            - cbs_user_id: User's CBS ID (if available)

    Raises:
        CBSOAuthError: If token exchange fails
    """
    if not CBS_CLIENT_ID or not CBS_CLIENT_SECRET:
        raise CBSOAuthError("CBS OAuth credentials are not configured")

    data = {
        "client_id": CBS_CLIENT_ID,
        "client_secret": CBS_CLIENT_SECRET,
        "redirect_uri": CBS_REDIRECT_URI,
        "code": code,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                CBS_TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code != 200:
                error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                error_msg = error_data.get("error_description", response.text)
                raise CBSOAuthError(f"Token exchange failed: {error_msg}")

            token_data = response.json()

            # CBS tokens typically expire in 3 days (259200 seconds)
            expires_in = token_data.get("expires_in", 259200)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            return {
                "access_token": token_data["access_token"],
                "refresh_token": token_data["refresh_token"],
                "expires_at": expires_at,
                "cbs_user_id": token_data.get("user_id"),
            }

        except httpx.RequestError as e:
            raise CBSOAuthError(f"Network error during token exchange: {e}")


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
        CBSTokenExpiredError: If refresh token is invalid/expired
        CBSOAuthError: If token refresh fails for other reasons
    """
    if not CBS_CLIENT_ID or not CBS_CLIENT_SECRET:
        raise CBSOAuthError("CBS OAuth credentials are not configured")

    data = {
        "client_id": CBS_CLIENT_ID,
        "client_secret": CBS_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                CBS_TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code == 401:
                raise CBSTokenExpiredError(
                    "Refresh token is invalid or expired. Please reconnect your CBS account."
                )

            if response.status_code != 200:
                error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                error_msg = error_data.get("error_description", response.text)
                raise CBSOAuthError(f"Token refresh failed: {error_msg}")

            token_data = response.json()

            # CBS tokens typically expire in 3 days
            expires_in = token_data.get("expires_in", 259200)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            return {
                "access_token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token", refresh_token),
                "expires_at": expires_at,
            }

        except httpx.RequestError as e:
            raise CBSOAuthError(f"Network error during token refresh: {e}")
