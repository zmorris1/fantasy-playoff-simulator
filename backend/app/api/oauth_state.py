"""
Signed OAuth `state` values.

The state sent to Yahoo/CBS is a short-lived JWT naming the user and the
provider. When the provider redirects back, verifying it both prevents CSRF
and tells us which user to attach the tokens to, even on a plain browser
redirect that carries no Authorization header.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from .auth import SECRET_KEY, ALGORITHM


STATE_TYPE = "oauth_state"
STATE_TTL = timedelta(minutes=15)


class InvalidOAuthState(Exception):
    """The state is missing, forged, expired, or for another provider/user."""


def create_oauth_state(user_id: int, provider: str) -> str:
    """Signed state for `user_id` connecting `provider`."""
    payload = {
        # Deliberately not "sub": this must never work as a login token
        "uid": user_id,
        "prov": provider,
        "typ": STATE_TYPE,
        "nonce": secrets.token_urlsafe(8),
        "exp": datetime.now(timezone.utc) + STATE_TTL,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_oauth_state(state: Optional[str], provider: str, user_id: Optional[int] = None) -> int:
    """
    Return the user ID a state was issued to.

    Raises InvalidOAuthState if it's invalid, expired, for a different
    provider, or (when user_id is given) issued to a different user.
    """
    if not state:
        raise InvalidOAuthState("Missing OAuth state. Please try connecting again.")
    try:
        payload = jwt.decode(state, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise InvalidOAuthState("This connection link is invalid or expired. Please try connecting again.")

    if payload.get("typ") != STATE_TYPE or payload.get("prov") != provider:
        raise InvalidOAuthState("OAuth state doesn't match this provider. Please try connecting again.")

    state_user = payload.get("uid")
    if not isinstance(state_user, int):
        raise InvalidOAuthState("Invalid OAuth state. Please try connecting again.")
    if user_id is not None and state_user != user_id:
        raise InvalidOAuthState("This connection was started by a different account.")
    return state_user
