"""
CBS Sports OAuth API routes.

Handles CBS OAuth 2.0 authentication flow for accessing
CBS Sports Fantasy leagues.
"""

import os
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from ..auth import get_current_user_required
from ...db import get_db, CBSCredentialRepository, User
from ...core.cbs_oauth import (
    build_authorization_url,
    exchange_code_for_tokens,
    CBSOAuthError,
)


router = APIRouter(prefix="/oauth/cbs", tags=["cbs-oauth"])


class AuthorizationUrlResponse(BaseModel):
    """Response containing CBS authorization URL."""
    url: str
    state: str


class ConnectionStatusResponse(BaseModel):
    """Response containing CBS connection status."""
    connected: bool
    cbs_user_id: str | None = None


@router.get("/authorize", response_model=AuthorizationUrlResponse)
async def get_authorization_url(
    current_user: User = Depends(get_current_user_required)
) -> AuthorizationUrlResponse:
    """
    Get the CBS OAuth authorization URL.

    The user should be redirected to this URL to authorize access to
    their CBS Sports Fantasy account.

    Requires authentication.
    """
    try:
        url, state = build_authorization_url()
        return AuthorizationUrlResponse(url=url, state=state)
    except CBSOAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/callback")
async def handle_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """
    Handle the CBS OAuth callback.

    This endpoint receives the authorization code from CBS after the user
    grants access. It exchanges the code for tokens and stores them.

    Redirects to the frontend dashboard with success or error status.
    """
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")

    # Handle OAuth errors
    if error:
        error_msg = error_description or error
        return RedirectResponse(
            url=f"{frontend_url}/dashboard?cbs_error={error_msg}"
        )

    if not code:
        return RedirectResponse(
            url=f"{frontend_url}/dashboard?cbs_error=No authorization code received"
        )

    try:
        # Exchange code for tokens
        token_data = await exchange_code_for_tokens(code)

        # Store tokens
        cred_repo = CBSCredentialRepository(db)
        await cred_repo.upsert(
            user_id=current_user.id,
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_at=token_data["expires_at"],
            cbs_user_id=token_data.get("cbs_user_id")
        )
        await db.commit()

        return RedirectResponse(
            url=f"{frontend_url}/dashboard?cbs_connected=true"
        )

    except CBSOAuthError as e:
        return RedirectResponse(
            url=f"{frontend_url}/dashboard?cbs_error={str(e)}"
        )


@router.get("/status", response_model=ConnectionStatusResponse)
async def get_connection_status(
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
) -> ConnectionStatusResponse:
    """
    Check if the user has connected their CBS account.

    Requires authentication.
    """
    cred_repo = CBSCredentialRepository(db)
    credential = await cred_repo.get_by_user_id(current_user.id)

    if credential is None:
        return ConnectionStatusResponse(connected=False)

    return ConnectionStatusResponse(
        connected=True,
        cbs_user_id=credential.cbs_user_id
    )


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_cbs(
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
) -> None:
    """
    Disconnect the user's CBS account.

    Removes stored CBS OAuth credentials.

    Requires authentication.
    """
    cred_repo = CBSCredentialRepository(db)
    deleted = await cred_repo.delete_by_user_id(current_user.id)
    await db.commit()

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No CBS connection found"
        )
