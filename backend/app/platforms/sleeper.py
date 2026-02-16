"""
Sleeper Fantasy platform adapter.

Fetches league data from Sleeper's public API for fantasy football and basketball.
Sleeper has a free, public, read-only API requiring no authentication.
"""

import httpx
from collections import defaultdict
from typing import Dict, List, Tuple, Any, Optional

from .base import (
    PlatformAdapter,
    LeagueNotFoundError,
    PlatformError
)
from ..simulator.models import Team, Matchup, H2HDict
from ..core.sports import Sport, SLEEPER_SPORT_CODES


class SleeperAdapter(PlatformAdapter):
    """Sleeper Fantasy platform adapter supporting football and basketball."""

    BASE_URL = "https://api.sleeper.app/v1"

    def __init__(self, sport: Sport = Sport.FOOTBALL, timeout: float = 30.0):
        """
        Initialize the Sleeper adapter.

        Args:
            sport: The sport type (football or basketball)
            timeout: HTTP request timeout in seconds
        """
        if sport == Sport.BASEBALL:
            raise ValueError("Sleeper does not support baseball leagues")
        self.sport = sport
        self.timeout = timeout

    def _get_sport_code(self) -> str:
        """Get the Sleeper API sport code for the current sport."""
        return SLEEPER_SPORT_CODES[self.sport]

    @property
    def platform_name(self) -> str:
        return "sleeper"

    async def _fetch_json(self, endpoint: str) -> Any:
        """
        Fetch JSON data from Sleeper API.

        Args:
            endpoint: The API endpoint (e.g., "/league/123456")

        Returns:
            JSON response data

        Raises:
            LeagueNotFoundError: If the resource doesn't exist
            PlatformError: If there's an API error
        """
        url = f"{self.BASE_URL}{endpoint}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(url)

                if response.status_code == 404:
                    raise LeagueNotFoundError(f"Resource not found: {endpoint}")

                # Sleeper returns null for non-existent leagues
                if response.status_code == 200 and response.text == "null":
                    raise LeagueNotFoundError(f"League not found: {endpoint}")

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                raise PlatformError(f"Sleeper API error: {e}")
            except httpx.RequestError as e:
                raise PlatformError(f"Network error: {e}")

    async def _get_nfl_state(self) -> Dict[str, Any]:
        """Get the current NFL state including current week."""
        return await self._fetch_json(f"/state/{self._get_sport_code()}")

    async def validate_league(self, league_id: str, season: int) -> bool:
        """Validate that a league exists and is accessible."""
        try:
            league = await self._fetch_json(f"/league/{league_id}")
            if league is None:
                raise LeagueNotFoundError(f"League {league_id} not found")

            # Check if the league is for the correct season
            league_season = league.get("season")
            if league_season and str(league_season) != str(season):
                raise LeagueNotFoundError(
                    f"League {league_id} is for season {league_season}, not {season}"
                )

            return True
        except LeagueNotFoundError:
            raise
        except Exception as e:
            raise PlatformError(f"Error validating league: {e}")

    async def fetch_standings(
        self, league_id: str, season: int
    ) -> Tuple[Dict[int, Team], Dict[int, str]]:
        """
        Fetch current standings from Sleeper API.

        Returns:
            Tuple of (teams dict by id, division names dict)
        """
        # Fetch rosters and users in parallel
        rosters = await self._fetch_json(f"/league/{league_id}/rosters")
        users = await self._fetch_json(f"/league/{league_id}/users")
        league = await self._fetch_json(f"/league/{league_id}")

        if not rosters:
            raise LeagueNotFoundError(f"No rosters found for league {league_id}")

        # Build user_id -> display_name mapping
        user_names: Dict[str, str] = {}
        if users:
            for user in users:
                user_id = user.get("user_id")
                # Try metadata.team_name first, then display_name
                metadata = user.get("metadata") or {}
                team_name = metadata.get("team_name")
                display_name = user.get("display_name")
                user_names[user_id] = team_name or display_name or f"Team {user_id}"

        # Get division names from league settings
        division_names: Dict[int, str] = {}
        settings = league.get("settings", {}) if league else {}
        divisions = settings.get("divisions", 0)
        # Sleeper uses 1-indexed division IDs
        for i in range(1, divisions + 1):
            division_names[i] = f"Division {i}"

        # Build teams dict
        teams: Dict[int, Team] = {}
        for roster in rosters:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            # Get team name from user mapping
            name = user_names.get(owner_id, f"Team {roster_id}")

            # Get record from roster settings
            roster_settings = roster.get("settings", {}) or {}
            wins = roster_settings.get("wins", 0)
            losses = roster_settings.get("losses", 0)
            ties = roster_settings.get("ties", 0)

            # Division info
            division_id = roster_settings.get("division", 0)

            # Note: Sleeper doesn't provide division-specific records directly
            # We'll need to calculate them from matchup history if needed
            team = Team(
                id=roster_id,
                name=name,
                division_id=division_id,
                wins=wins,
                losses=losses,
                ties=ties,
                division_wins=0,
                division_losses=0,
                division_ties=0
            )
            teams[roster_id] = team

        # If there are divisions, calculate division records from matchups
        if divisions > 0:
            await self._calculate_division_records(league_id, teams)

        return teams, division_names

    async def _calculate_division_records(
        self, league_id: str, teams: Dict[int, Team]
    ) -> None:
        """Calculate division records by iterating through completed matchups."""
        league = await self._fetch_json(f"/league/{league_id}")
        settings = league.get("settings", {}) if league else {}

        # Get playoff start week to know when regular season ends
        playoff_week_start = settings.get("playoff_week_start", 15)

        # Get current week
        state = await self._get_nfl_state()
        current_week = state.get("week", 1)

        # Iterate through completed weeks
        for week in range(1, min(current_week, playoff_week_start)):
            try:
                matchups = await self._fetch_json(f"/league/{league_id}/matchups/{week}")
                if not matchups:
                    continue

                # Group matchups by matchup_id
                matchup_groups: Dict[int, List[Dict]] = defaultdict(list)
                for m in matchups:
                    matchup_id = m.get("matchup_id")
                    if matchup_id is not None:
                        matchup_groups[matchup_id].append(m)

                # Process each matchup
                for matchup_id, group in matchup_groups.items():
                    if len(group) != 2:
                        continue

                    team1_data, team2_data = group[0], group[1]
                    team1_id = team1_data.get("roster_id")
                    team2_id = team2_data.get("roster_id")

                    team1 = teams.get(team1_id)
                    team2 = teams.get(team2_id)

                    if not team1 or not team2:
                        continue

                    # Check if it's a division game
                    if team1.division_id != team2.division_id or team1.division_id == 0:
                        continue

                    # Determine winner by points
                    team1_points = team1_data.get("points", 0) or 0
                    team2_points = team2_data.get("points", 0) or 0

                    if team1_points > team2_points:
                        team1.division_wins += 1
                        team2.division_losses += 1
                    elif team2_points > team1_points:
                        team2.division_wins += 1
                        team1.division_losses += 1
                    else:
                        team1.division_ties += 1
                        team2.division_ties += 1

            except (LeagueNotFoundError, PlatformError):
                # Skip weeks that don't have data
                continue

    async def fetch_schedule(
        self, league_id: str, season: int, teams: Dict[int, Team]
    ) -> Tuple[List[Matchup], int, int]:
        """
        Fetch schedule from Sleeper API and identify remaining matchups.

        Returns:
            Tuple of (remaining matchups, current week, total weeks)
        """
        league = await self._fetch_json(f"/league/{league_id}")
        settings = league.get("settings", {}) if league else {}

        # Get playoff week start (regular season ends before this)
        playoff_week_start = settings.get("playoff_week_start", 15)
        total_weeks = playoff_week_start - 1

        # Get current week from NFL state
        state = await self._get_nfl_state()
        current_week = state.get("week", 1)

        # Build list of remaining matchups
        remaining: List[Matchup] = []

        for week in range(current_week, total_weeks + 1):
            try:
                matchups = await self._fetch_json(f"/league/{league_id}/matchups/{week}")
                if not matchups:
                    continue

                # Group matchups by matchup_id
                matchup_groups: Dict[int, List[Dict]] = defaultdict(list)
                for m in matchups:
                    matchup_id = m.get("matchup_id")
                    if matchup_id is not None:
                        matchup_groups[matchup_id].append(m)

                # Process each matchup
                for matchup_id, group in matchup_groups.items():
                    if len(group) != 2:
                        continue

                    team1_data, team2_data = group[0], group[1]
                    team1_id = team1_data.get("roster_id")
                    team2_id = team2_data.get("roster_id")

                    if team1_id is None or team2_id is None:
                        continue

                    # Check if matchup is completed (both have points > 0)
                    team1_points = team1_data.get("points", 0) or 0
                    team2_points = team2_data.get("points", 0) or 0

                    # If both teams have 0 points, matchup hasn't been played
                    # or if either team has non-zero points, check week completion
                    # For simplicity, treat current week matchups with 0-0 as remaining
                    if team1_points == 0 and team2_points == 0:
                        # Matchup not played yet
                        team1 = teams.get(team1_id)
                        team2 = teams.get(team2_id)
                        is_division_game = (
                            team1 and team2 and
                            team1.division_id == team2.division_id and
                            team1.division_id != 0
                        )

                        remaining.append(Matchup(
                            home_team_id=team1_id,
                            away_team_id=team2_id,
                            week=week,
                            is_division_game=is_division_game
                        ))

            except (LeagueNotFoundError, PlatformError):
                # Skip weeks that don't have data
                continue

        return remaining, current_week, total_weeks

    async def fetch_head_to_head(
        self, league_id: str, season: int, teams: Dict[int, Team]
    ) -> H2HDict:
        """
        Fetch head-to-head records between all teams.

        Returns:
            Dict mapping (team1_id, team2_id) -> (team1_wins, team2_wins, ties)
        """
        league = await self._fetch_json(f"/league/{league_id}")
        settings = league.get("settings", {}) if league else {}

        # Get playoff week start (regular season ends before this)
        playoff_week_start = settings.get("playoff_week_start", 15)

        # Get current week from NFL state
        state = await self._get_nfl_state()
        current_week = state.get("week", 1)

        # Track H2H records
        h2h: Dict[Tuple[int, int], List[int]] = defaultdict(lambda: [0, 0, 0])

        # Iterate through completed weeks only
        for week in range(1, min(current_week, playoff_week_start)):
            try:
                matchups = await self._fetch_json(f"/league/{league_id}/matchups/{week}")
                if not matchups:
                    continue

                # Group matchups by matchup_id
                matchup_groups: Dict[int, List[Dict]] = defaultdict(list)
                for m in matchups:
                    matchup_id = m.get("matchup_id")
                    if matchup_id is not None:
                        matchup_groups[matchup_id].append(m)

                # Process each matchup
                for matchup_id, group in matchup_groups.items():
                    if len(group) != 2:
                        continue

                    team1_data, team2_data = group[0], group[1]
                    team1_id = team1_data.get("roster_id")
                    team2_id = team2_data.get("roster_id")

                    if team1_id is None or team2_id is None:
                        continue

                    team1_points = team1_data.get("points", 0) or 0
                    team2_points = team2_data.get("points", 0) or 0

                    # Skip unplayed matchups
                    if team1_points == 0 and team2_points == 0:
                        continue

                    # Use consistent key ordering (min_id, max_id)
                    key = (min(team1_id, team2_id), max(team1_id, team2_id))

                    if team1_points > team2_points:
                        # team1 won
                        if team1_id < team2_id:
                            h2h[key][0] += 1
                        else:
                            h2h[key][1] += 1
                    elif team2_points > team1_points:
                        # team2 won
                        if team2_id < team1_id:
                            h2h[key][0] += 1
                        else:
                            h2h[key][1] += 1
                    else:
                        # Tie
                        h2h[key][2] += 1

            except (LeagueNotFoundError, PlatformError):
                # Skip weeks that don't have data
                continue

        # Convert lists to tuples
        return {k: tuple(v) for k, v in h2h.items()}

    async def fetch_league_settings(
        self, league_id: str, season: int
    ) -> Dict[str, Any]:
        """
        Fetch league settings including playoff configuration.

        Returns:
            Dict with league settings
        """
        league = await self._fetch_json(f"/league/{league_id}")

        if not league:
            raise LeagueNotFoundError(f"League {league_id} not found")

        settings = league.get("settings", {}) or {}

        # Get playoff settings
        playoff_teams = settings.get("playoff_teams", 6)
        divisions = settings.get("divisions", 0)
        playoff_week_start = settings.get("playoff_week_start", 15)
        total_weeks = playoff_week_start - 1

        # Get league name
        league_name = league.get("name", f"League {league_id}")

        # Build division list
        division_list = []
        for i in range(1, divisions + 1):
            division_list.append({"id": i, "name": f"Division {i}"})

        return {
            "league_name": league_name,
            "playoff_spots": playoff_teams,
            "num_divisions": divisions,
            "total_weeks": total_weeks,
            "divisions": division_list
        }
