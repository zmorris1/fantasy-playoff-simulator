"""
Abstract base class for fantasy sports platform adapters.

This provides a common interface for fetching league data from different
fantasy sports platforms (ESPN, Yahoo, Sleeper, etc.).
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Tuple, Any

from ..simulator.models import Team, Matchup, H2HDict


class PlatformAdapter(ABC):
    """Abstract base class for fantasy sports platform adapters."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform name (e.g., 'espn', 'yahoo', 'sleeper')."""
        pass

    @abstractmethod
    async def validate_league(self, league_id: str, season: int) -> bool:
        """
        Validate that a league exists and is accessible.

        Args:
            league_id: The league identifier
            season: The season year

        Returns:
            True if the league is valid and accessible

        Raises:
            LeagueNotFoundError: If the league doesn't exist
            LeaguePrivateError: If the league is private/inaccessible
        """
        pass

    @abstractmethod
    async def fetch_standings(
        self, league_id: str, season: int
    ) -> Tuple[Dict[int, Team], Dict[int, str]]:
        """
        Fetch current standings from the platform.

        Args:
            league_id: The league identifier
            season: The season year

        Returns:
            Tuple of (teams dict by id, division names dict)
        """
        pass

    @abstractmethod
    async def fetch_schedule(
        self, league_id: str, season: int, teams: Dict[int, Team]
    ) -> Tuple[List[Matchup], int, int]:
        """
        Fetch schedule and identify remaining matchups.

        Args:
            league_id: The league identifier
            season: The season year
            teams: Teams dict (needed to determine division games)

        Returns:
            Tuple of (remaining matchups, current week, total weeks)
        """
        pass

    @abstractmethod
    async def fetch_head_to_head(
        self, league_id: str, season: int, teams: Dict[int, Team]
    ) -> H2HDict:
        """
        Fetch head-to-head records between all teams.

        Args:
            league_id: The league identifier
            season: The season year
            teams: Teams dict

        Returns:
            Dict mapping (team1_id, team2_id) -> (team1_wins, team2_wins, ties)
        """
        pass

    @abstractmethod
    async def fetch_league_settings(
        self, league_id: str, season: int
    ) -> Dict[str, Any]:
        """
        Fetch league settings including playoff configuration.

        Args:
            league_id: The league identifier
            season: The season year

        Returns:
            Dict with league settings (playoff_spots, num_divisions, etc.)
        """
        pass


class LeagueNotFoundError(Exception):
    """Raised when a league cannot be found."""
    pass


class LeaguePrivateError(Exception):
    """Raised when a league is private and cannot be accessed."""
    pass


class PlatformError(Exception):
    """Raised when there's an error communicating with the platform."""
    pass
