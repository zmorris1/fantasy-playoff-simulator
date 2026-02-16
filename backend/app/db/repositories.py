"""
Repository classes for database operations.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from uuid import uuid4

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User, SavedLeague, SimulationCache, SimulationTask, YahooCredential, CBSCredential


class UserRepository:
    """Repository for user operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, email: str, password_hash: str) -> User:
        """Create a new user."""
        user = User(email=email.lower(), password_hash=password_hash)
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def get_by_id(self, user_id: int) -> Optional[User]:
        """Get a user by ID."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get a user by email."""
        result = await self.session.execute(
            select(User).where(User.email == email.lower())
        )
        return result.scalar_one_or_none()

    async def email_exists(self, email: str) -> bool:
        """Check if an email is already registered."""
        result = await self.session.execute(
            select(User.id).where(User.email == email.lower())
        )
        return result.scalar_one_or_none() is not None

    async def delete(self, user: User) -> None:
        """Delete a user."""
        await self.session.delete(user)


class SavedLeagueRepository:
    """Repository for saved league operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        user_id: int,
        platform: str,
        league_id: str,
        season: int,
        sport: str = "basketball",
        nickname: Optional[str] = None
    ) -> SavedLeague:
        """Save a league for a user."""
        league = SavedLeague(
            user_id=user_id,
            platform=platform.lower(),
            league_id=league_id,
            season=season,
            sport=sport.lower(),
            nickname=nickname
        )
        self.session.add(league)
        await self.session.flush()
        await self.session.refresh(league)
        return league

    async def get_by_id(self, league_pk: int) -> Optional[SavedLeague]:
        """Get a saved league by primary key."""
        result = await self.session.execute(
            select(SavedLeague).where(SavedLeague.id == league_pk)
        )
        return result.scalar_one_or_none()

    async def get_user_leagues(self, user_id: int) -> List[SavedLeague]:
        """Get all saved leagues for a user."""
        result = await self.session.execute(
            select(SavedLeague)
            .where(SavedLeague.user_id == user_id)
            .order_by(SavedLeague.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_user_league(
        self,
        user_id: int,
        platform: str,
        league_id: str,
        season: int,
        sport: str = "basketball"
    ) -> Optional[SavedLeague]:
        """Get a specific saved league for a user."""
        result = await self.session.execute(
            select(SavedLeague)
            .where(
                SavedLeague.user_id == user_id,
                SavedLeague.platform == platform.lower(),
                SavedLeague.league_id == league_id,
                SavedLeague.season == season,
                SavedLeague.sport == sport.lower()
            )
        )
        return result.scalar_one_or_none()

    async def update_nickname(self, league: SavedLeague, nickname: str) -> SavedLeague:
        """Update a saved league's nickname."""
        league.nickname = nickname
        await self.session.flush()
        return league

    async def delete(self, league: SavedLeague) -> None:
        """Delete a saved league."""
        await self.session.delete(league)


class SimulationCacheRepository:
    """Repository for simulation cache operations."""

    DEFAULT_TTL_MINUTES = 15

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(
        self,
        platform: str,
        league_id: str,
        season: int,
        week: int,
        sport: str = "basketball"
    ) -> Optional[dict]:
        """
        Get cached simulation results if not expired.

        Returns:
            Parsed results dict or None if not cached/expired
        """
        result = await self.session.execute(
            select(SimulationCache)
            .where(
                SimulationCache.platform == platform.lower(),
                SimulationCache.league_id == league_id,
                SimulationCache.season == season,
                SimulationCache.sport == sport.lower(),
                SimulationCache.week == week
            )
        )
        cache_entry = result.scalar_one_or_none()

        if cache_entry is None:
            return None

        if cache_entry.is_expired:
            await self.session.delete(cache_entry)
            return None

        return json.loads(cache_entry.results_json)

    async def set(
        self,
        platform: str,
        league_id: str,
        season: int,
        week: int,
        results: dict,
        sport: str = "basketball",
        ttl_minutes: int = DEFAULT_TTL_MINUTES
    ) -> SimulationCache:
        """
        Cache simulation results.

        Args:
            platform: Platform name
            league_id: League identifier
            season: Season year
            week: Week number
            results: Results to cache
            sport: Sport type
            ttl_minutes: Time-to-live in minutes

        Returns:
            Created cache entry
        """
        # Delete existing entry if present
        await self.session.execute(
            delete(SimulationCache)
            .where(
                SimulationCache.platform == platform.lower(),
                SimulationCache.league_id == league_id,
                SimulationCache.season == season,
                SimulationCache.sport == sport.lower(),
                SimulationCache.week == week
            )
        )

        # Create new entry
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        cache_entry = SimulationCache(
            platform=platform.lower(),
            league_id=league_id,
            season=season,
            sport=sport.lower(),
            week=week,
            results_json=json.dumps(results),
            expires_at=expires_at
        )
        self.session.add(cache_entry)
        await self.session.flush()
        return cache_entry

    async def invalidate(
        self,
        platform: str,
        league_id: str,
        season: int,
        week: Optional[int] = None
    ) -> int:
        """
        Invalidate cached results.

        Args:
            platform: Platform name
            league_id: League identifier
            season: Season year
            week: Week number (optional, invalidates all weeks if not provided)

        Returns:
            Number of entries deleted
        """
        conditions = [
            SimulationCache.platform == platform.lower(),
            SimulationCache.league_id == league_id,
            SimulationCache.season == season
        ]
        if week is not None:
            conditions.append(SimulationCache.week == week)

        result = await self.session.execute(
            delete(SimulationCache).where(*conditions)
        )
        return result.rowcount

    async def cleanup_expired(self) -> int:
        """
        Remove all expired cache entries.

        Returns:
            Number of entries deleted
        """
        result = await self.session.execute(
            delete(SimulationCache)
            .where(SimulationCache.expires_at < datetime.now(timezone.utc))
        )
        return result.rowcount


class SimulationTaskRepository:
    """Repository for simulation task operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        platform: str,
        league_id: str,
        season: int,
        sport: str = "basketball"
    ) -> SimulationTask:
        """Create a new simulation task."""
        task = SimulationTask(
            id=str(uuid4()),
            platform=platform.lower(),
            league_id=league_id,
            season=season,
            sport=sport.lower(),
            status="pending",
            progress=0
        )
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(task)
        return task

    async def get_by_id(self, task_id: str) -> Optional[SimulationTask]:
        """Get a task by ID."""
        result = await self.session.execute(
            select(SimulationTask).where(SimulationTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def update_progress(self, task: SimulationTask, progress: int) -> None:
        """Update task progress."""
        task.progress = progress
        task.status = "running"
        await self.session.flush()

    async def complete(self, task: SimulationTask, results: dict) -> None:
        """Mark task as completed with results."""
        task.status = "completed"
        task.progress = 100
        task.results_json = json.dumps(results)
        task.completed_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def fail(self, task: SimulationTask, error_message: str) -> None:
        """Mark task as failed with error message."""
        task.status = "failed"
        task.error_message = error_message
        task.completed_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def cleanup_old_tasks(self, hours: int = 24) -> int:
        """
        Remove tasks older than specified hours.

        Returns:
            Number of tasks deleted
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.session.execute(
            delete(SimulationTask)
            .where(SimulationTask.created_at < cutoff)
        )
        return result.rowcount


class YahooCredentialRepository:
    """Repository for Yahoo OAuth credential operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(self, user_id: int) -> Optional[YahooCredential]:
        """Get Yahoo credential for a user."""
        result = await self.session.execute(
            select(YahooCredential).where(YahooCredential.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        user_id: int,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
        yahoo_guid: Optional[str] = None
    ) -> YahooCredential:
        """
        Create or update Yahoo credential for a user.

        Args:
            user_id: User ID
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            expires_at: Token expiration datetime
            yahoo_guid: Yahoo user GUID (optional)

        Returns:
            Created or updated credential
        """
        existing = await self.get_by_user_id(user_id)

        if existing:
            existing.access_token = access_token
            existing.refresh_token = refresh_token
            existing.expires_at = expires_at
            existing.updated_at = datetime.now(timezone.utc)
            if yahoo_guid:
                existing.yahoo_guid = yahoo_guid
            await self.session.flush()
            return existing

        credential = YahooCredential(
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            yahoo_guid=yahoo_guid
        )
        self.session.add(credential)
        await self.session.flush()
        await self.session.refresh(credential)
        return credential

    async def delete_by_user_id(self, user_id: int) -> bool:
        """
        Delete Yahoo credential for a user.

        Returns:
            True if credential was deleted, False if not found
        """
        result = await self.session.execute(
            delete(YahooCredential).where(YahooCredential.user_id == user_id)
        )
        return result.rowcount > 0


class CBSCredentialRepository:
    """Repository for CBS Sports OAuth credential operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(self, user_id: int) -> Optional[CBSCredential]:
        """Get CBS credential for a user."""
        result = await self.session.execute(
            select(CBSCredential).where(CBSCredential.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        user_id: int,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
        cbs_user_id: Optional[str] = None
    ) -> CBSCredential:
        """
        Create or update CBS credential for a user.

        Args:
            user_id: User ID
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            expires_at: Token expiration datetime
            cbs_user_id: CBS user ID (optional)

        Returns:
            Created or updated credential
        """
        existing = await self.get_by_user_id(user_id)

        if existing:
            existing.access_token = access_token
            existing.refresh_token = refresh_token
            existing.expires_at = expires_at
            existing.updated_at = datetime.now(timezone.utc)
            if cbs_user_id:
                existing.cbs_user_id = cbs_user_id
            await self.session.flush()
            return existing

        credential = CBSCredential(
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            cbs_user_id=cbs_user_id
        )
        self.session.add(credential)
        await self.session.flush()
        await self.session.refresh(credential)
        return credential

    async def delete_by_user_id(self, user_id: int) -> bool:
        """
        Delete CBS credential for a user.

        Returns:
            True if credential was deleted, False if not found
        """
        result = await self.session.execute(
            delete(CBSCredential).where(CBSCredential.user_id == user_id)
        )
        return result.rowcount > 0
