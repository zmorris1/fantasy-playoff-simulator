"""
League management API routes.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import (
    LeagueValidateRequest,
    LeagueValidateResponse,
    SavedLeagueCreate,
    SavedLeagueResponse
)
from ..auth import get_current_user, get_current_user_required
from ...db import get_db, SavedLeagueRepository, YahooCredentialRepository, CBSCredentialRepository, User
from ...platforms import get_adapter, LeagueNotFoundError, LeaguePrivateError, PlatformError
from ...core.sports import Sport, get_current_season
from ...core.yahoo_oauth import YahooTokenExpiredError
from ...core.cbs_oauth import CBSTokenExpiredError


router = APIRouter(prefix="/leagues", tags=["leagues"])


@router.get("/validate", response_model=LeagueValidateResponse)
async def validate_league(
    platform: str,
    league_id: str,
    season: int = None,
    sport: str = "basketball",
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> LeagueValidateResponse:
    """
    Validate that a league exists and is accessible.

    This endpoint can be used without authentication for ESPN leagues.
    Yahoo leagues require authentication and a connected Yahoo account.
    """
    # Convert sport string to Sport enum
    try:
        sport_enum = Sport(sport.lower())
    except ValueError:
        return LeagueValidateResponse(
            valid=False,
            error=f"Invalid sport: {sport}. Supported: basketball, football, baseball, hockey"
        )

    if season is None:
        season = get_current_season(sport_enum)

    # Handle Yahoo platform - requires authentication and Yahoo credential
    yahoo_credential = None
    if platform.lower() == "yahoo":
        if current_user is None:
            return LeagueValidateResponse(
                valid=False,
                error="Authentication required to access Yahoo Fantasy leagues"
            )

        cred_repo = YahooCredentialRepository(db)
        yahoo_credential = await cred_repo.get_by_user_id(current_user.id)
        if yahoo_credential is None:
            return LeagueValidateResponse(
                valid=False,
                error="Please connect your Yahoo account first"
            )

    # Handle CBS platform - requires authentication and CBS credential
    cbs_credential = None
    if platform.lower() == "cbs":
        if current_user is None:
            return LeagueValidateResponse(
                valid=False,
                error="Authentication required to access CBS Sports Fantasy leagues"
            )

        cbs_cred_repo = CBSCredentialRepository(db)
        cbs_credential = await cbs_cred_repo.get_by_user_id(current_user.id)
        if cbs_credential is None:
            return LeagueValidateResponse(
                valid=False,
                error="Please connect your CBS account first"
            )

    try:
        adapter = get_adapter(platform, sport_enum, yahoo_credential=yahoo_credential, cbs_credential=cbs_credential)
    except ValueError as e:
        return LeagueValidateResponse(
            valid=False,
            error=str(e)
        )

    try:
        await adapter.validate_league(league_id, season)
        settings = await adapter.fetch_league_settings(league_id, season)

        # If token was refreshed, persist the new tokens
        if hasattr(adapter, '_token_refreshed') and adapter._token_refreshed:
            await db.commit()

        return LeagueValidateResponse(
            valid=True,
            league_name=settings.get("league_name"),
            playoff_spots=settings.get("playoff_spots"),
            num_divisions=settings.get("num_divisions"),
            sport=sport.lower()
        )

    except LeagueNotFoundError:
        return LeagueValidateResponse(
            valid=False,
            error=f"League {league_id} not found for season {season}"
        )
    except LeaguePrivateError:
        return LeagueValidateResponse(
            valid=False,
            error="This league is private. Only public leagues can be simulated."
        )
    except YahooTokenExpiredError:
        return LeagueValidateResponse(
            valid=False,
            error="Yahoo authentication expired. Please reconnect your Yahoo account."
        )
    except CBSTokenExpiredError:
        return LeagueValidateResponse(
            valid=False,
            error="CBS authentication expired. Please reconnect your CBS account."
        )
    except PlatformError as e:
        return LeagueValidateResponse(
            valid=False,
            error=f"Error communicating with {platform}: {str(e)}"
        )
    except Exception as e:
        return LeagueValidateResponse(
            valid=False,
            error=f"Unexpected error validating league: {str(e)}"
        )


@router.get("/me", response_model=List[SavedLeagueResponse])
async def get_my_leagues(
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
) -> List[SavedLeagueResponse]:
    """
    Get all saved leagues for the current user.
    """
    league_repo = SavedLeagueRepository(db)
    leagues = await league_repo.get_user_leagues(current_user.id)

    return [
        SavedLeagueResponse(
            id=league.id,
            platform=league.platform,
            league_id=league.league_id,
            season=league.season,
            sport=league.sport,
            nickname=league.nickname,
            created_at=league.created_at
        )
        for league in leagues
    ]


@router.post("/me", response_model=SavedLeagueResponse, status_code=status.HTTP_201_CREATED)
async def save_league(
    data: SavedLeagueCreate,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
) -> SavedLeagueResponse:
    """
    Save a league to the user's account.
    """
    # Convert sport string to Sport enum
    try:
        sport_enum = Sport(data.sport.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sport: {data.sport}. Supported: basketball, football, baseball, hockey"
        )

    league_repo = SavedLeagueRepository(db)

    # Check if already saved
    existing = await league_repo.get_user_league(
        current_user.id,
        data.platform,
        data.league_id,
        data.season,
        data.sport
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This league is already saved to your account"
        )

    # Handle Yahoo platform - requires Yahoo credential
    yahoo_credential = None
    if data.platform.lower() == "yahoo":
        cred_repo = YahooCredentialRepository(db)
        yahoo_credential = await cred_repo.get_by_user_id(current_user.id)
        if yahoo_credential is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please connect your Yahoo account first"
            )

    # Handle CBS platform - requires CBS credential
    cbs_credential = None
    if data.platform.lower() == "cbs":
        cbs_cred_repo = CBSCredentialRepository(db)
        cbs_credential = await cbs_cred_repo.get_by_user_id(current_user.id)
        if cbs_credential is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please connect your CBS account first"
            )

    # Validate the league exists
    try:
        adapter = get_adapter(data.platform, sport_enum, yahoo_credential=yahoo_credential, cbs_credential=cbs_credential)
        await adapter.validate_league(data.league_id, data.season)

        # If token was refreshed, persist the new tokens
        if hasattr(adapter, '_token_refreshed') and adapter._token_refreshed:
            await db.flush()
    except (LeagueNotFoundError, LeaguePrivateError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except YahooTokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Yahoo authentication expired. Please reconnect your Yahoo account."
        )
    except CBSTokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CBS authentication expired. Please reconnect your CBS account."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not validate league: {str(e)}"
        )

    # Save the league
    league = await league_repo.create(
        user_id=current_user.id,
        platform=data.platform,
        league_id=data.league_id,
        season=data.season,
        sport=data.sport,
        nickname=data.nickname
    )
    await db.commit()

    return SavedLeagueResponse(
        id=league.id,
        platform=league.platform,
        league_id=league.league_id,
        season=league.season,
        sport=league.sport,
        nickname=league.nickname,
        created_at=league.created_at
    )


@router.delete("/me/{league_pk}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_league(
    league_pk: int,
    current_user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
) -> None:
    """
    Delete a saved league from the user's account.
    """
    league_repo = SavedLeagueRepository(db)

    league = await league_repo.get_by_id(league_pk)
    if league is None or league.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="League not found"
        )

    await league_repo.delete(league)
    await db.commit()
