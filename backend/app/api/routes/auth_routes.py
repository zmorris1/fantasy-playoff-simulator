"""
Authentication API routes.
"""

from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import UserRegister, UserLogin, TokenResponse, UserResponse
from ..auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user_required,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from ...db import get_db, UserRepository, User


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: UserRegister,
    db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    """
    Register a new user account.

    Returns a JWT token on successful registration.
    """
    user_repo = UserRepository(db)

    # Check if email already exists
    if await user_repo.email_exists(data.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Create user
    password_hash = hash_password(data.password)
    user = await user_repo.create(email=data.email, password_hash=password_hash)
    await db.commit()

    # Generate token
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
async def login(
    data: UserLogin,
    db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    """
    Login with email and password.

    Returns a JWT token on successful login.
    """
    user_repo = UserRepository(db)

    # Find user by email
    user = await user_repo.get_by_email(data.email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Verify password
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Generate token
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user_required)
) -> UserResponse:
    """
    Get the current authenticated user's information.
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        created_at=current_user.created_at
    )


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user_required)
) -> dict:
    """
    Logout (client should discard token).

    Note: JWT tokens are stateless, so the server cannot invalidate them.
    The client should discard the token on logout.
    """
    return {"message": "Successfully logged out"}
