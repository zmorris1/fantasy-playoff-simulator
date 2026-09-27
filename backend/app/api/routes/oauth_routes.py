"""
OAuth connection routes shared by Yahoo and CBS.

Flow:
1. GET  /oauth/{provider}/authorize  (logged in) -> provider URL with a signed state
2. The provider redirects the browser to its redirect URI with ?code&state:
   - the frontend dashboard, which POSTs them to /oauth/{provider}/callback, or
   - GET /oauth/{provider}/callback on the API, which redirects to the dashboard.
   Either way the signed state identifies the user; a browser redirect
   carries no Authorization header, so it can't be relied on.
"""

import os
from types import ModuleType
from typing import Optional, Type
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user_required
from ..oauth_state import InvalidOAuthState, create_oauth_state, verify_oauth_state
from ...db import get_db, User, UserRepository


class AuthorizationUrlResponse(BaseModel):
    """Response containing the provider authorization URL."""
    url: str
    state: str


class ConnectionStatusResponse(BaseModel):
    """Whether the user has connected the provider."""
    connected: bool
    account_id: Optional[str] = None


class OAuthCallbackRequest(BaseModel):
    """Code and state the provider appended to the redirect URL."""
    code: str
    state: str


def build_oauth_router(
    provider: str,
    display_name: str,
    oauth: ModuleType,
    oauth_error: Type[Exception],
    repo_class: type,
    account_field: str,
) -> APIRouter:
    """
    Routes for connecting one OAuth provider.

    Args:
        provider: URL segment and state tag, e.g. "yahoo"
        display_name: Name shown in error messages
        oauth: Module with build_authorization_url(state) and exchange_code_for_tokens(code)
        oauth_error: Exception the oauth module raises
        repo_class: Credential repository (get_by_user_id / upsert / delete_by_user_id)
        account_field: Provider account ID field on the credential and token data
    """
    router = APIRouter(prefix=f"/oauth/{provider}", tags=[f"{provider}-oauth"])

    async def store_tokens(db: AsyncSession, user_id: int, code: str) -> Optional[str]:
        token_data = await oauth.exchange_code_for_tokens(code)
        await repo_class(db).upsert(
            user_id=user_id,
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_at=token_data["expires_at"],
            **{account_field: token_data.get(account_field)},
        )
        await db.commit()
        return token_data.get(account_field)

    @router.get("/authorize", response_model=AuthorizationUrlResponse)
    async def get_authorization_url(
        current_user: User = Depends(get_current_user_required)
    ) -> AuthorizationUrlResponse:
        """
        Get the provider's OAuth authorization URL. Requires authentication.
        """
        try:
            url, state = oauth.build_authorization_url(create_oauth_state(current_user.id, provider))
            return AuthorizationUrlResponse(url=url, state=state)
        except oauth_error as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"{display_name} connections aren't available right now: {e}"
            )

    @router.get("/callback")
    async def handle_oauth_redirect(
        code: Optional[str] = None,
        state: Optional[str] = None,
        error: Optional[str] = None,
        error_description: Optional[str] = None,
        db: AsyncSession = Depends(get_db)
    ):
        """
        Browser redirect target when the redirect URI points at the API.
        Stores the tokens for the user named in the state, then redirects
        to the frontend dashboard with success or error status.
        """
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")

        def back_to_dashboard(**params: str) -> RedirectResponse:
            return RedirectResponse(url=f"{frontend_url}/dashboard?{urlencode(params)}")

        if error:
            return back_to_dashboard(**{f"{provider}_error": error_description or error})
        if not code:
            return back_to_dashboard(**{f"{provider}_error": "No authorization code received"})

        try:
            user_id = verify_oauth_state(state, provider)
            if await UserRepository(db).get_by_id(user_id) is None:
                raise InvalidOAuthState("That account no longer exists.")
            await store_tokens(db, user_id, code)
        except (InvalidOAuthState, oauth_error) as e:
            return back_to_dashboard(**{f"{provider}_error": str(e)})

        return back_to_dashboard(**{f"{provider}_connected": "true"})

    @router.post("/callback", response_model=ConnectionStatusResponse)
    async def complete_oauth(
        data: OAuthCallbackRequest,
        current_user: User = Depends(get_current_user_required),
        db: AsyncSession = Depends(get_db)
    ) -> ConnectionStatusResponse:
        """
        Finish connecting when the provider redirected to the frontend,
        which forwards the code and state here.
        """
        try:
            verify_oauth_state(data.state, provider, current_user.id)
            account_id = await store_tokens(db, current_user.id, data.code)
        except InvalidOAuthState as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        except oauth_error as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{display_name} rejected the connection: {e}"
            )

        return ConnectionStatusResponse(connected=True, account_id=account_id)

    @router.get("/status", response_model=ConnectionStatusResponse)
    async def get_connection_status(
        current_user: User = Depends(get_current_user_required),
        db: AsyncSession = Depends(get_db)
    ) -> ConnectionStatusResponse:
        """
        Check if the user has connected the provider. Requires authentication.
        """
        credential = await repo_class(db).get_by_user_id(current_user.id)
        if credential is None:
            return ConnectionStatusResponse(connected=False)
        return ConnectionStatusResponse(connected=True, account_id=getattr(credential, account_field))

    @router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
    async def disconnect(
        current_user: User = Depends(get_current_user_required),
        db: AsyncSession = Depends(get_db)
    ) -> None:
        """
        Remove the user's stored OAuth credentials. Requires authentication.
        """
        deleted = await repo_class(db).delete_by_user_id(current_user.id)
        await db.commit()

        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No {display_name} connection found"
            )

    return router
