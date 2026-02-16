"""
Fantrax Fantasy platform adapter.

Fetches league data from Fantrax's unofficial API for public leagues.
Fantrax supports football, basketball, baseball, hockey, soccer, golf, and racing.
"""

import httpx
from collections import defaultdict
from typing import Dict, List, Tuple, Any

from .base import (
    PlatformAdapter,
    LeagueNotFoundError,
    LeaguePrivateError,
    PlatformError
)
from ..simulator.models import Team, Matchup, H2HDict
from ..core.sports import Sport, FANTRAX_SPORT_CODES


class FantraxAdapter(PlatformAdapter):
    """Fantrax Fantasy platform adapter supporting football, basketball, and baseball."""

    BASE_URL = "https://www.fantrax.com/fxpa/req"

    def __init__(self, sport: Sport = Sport.FOOTBALL, timeout: float = 30.0):
        """
        Initialize the Fantrax adapter.

        Args:
            sport: The sport type (football, basketball, or baseball)
            timeout: HTTP request timeout in seconds
        """
        self.sport = sport
        self.timeout = timeout
        self._league_info_cache: Dict[str, Dict] = {}

    def _get_sport_code(self) -> str:
        """Get the Fantrax API sport code for the current sport."""
        return FANTRAX_SPORT_CODES[self.sport]

    @property
    def platform_name(self) -> str:
        return "fantrax"

    def _hash_team_id(self, team_id: str) -> int:
        """
        Convert Fantrax's string team ID to an integer.

        Uses a simple hash to create a consistent integer ID.
        """
        return abs(hash(team_id)) % (10 ** 9)

    async def _call_api(self, method: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make a POST request to the Fantrax API.

        Args:
            method: The API method name (e.g., "getFantasyLeagueInfo")
            data: The request data including leagueId

        Returns:
            The response data from the API

        Raises:
            LeagueNotFoundError: If the league doesn't exist
            LeaguePrivateError: If the league is private
            PlatformError: If there's an API error
        """
        payload = {"msgs": [{"method": method, "data": data}]}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    self.BASE_URL,
                    params={"leagueId": data.get("leagueId", "")},
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )

                if response.status_code == 404:
                    raise LeagueNotFoundError(f"League not found")

                response.raise_for_status()
                result = response.json()

                # Check for API-level errors in response
                if not result or "responses" not in result:
                    raise PlatformError("Invalid response from Fantrax API")

                responses = result.get("responses", [])
                if not responses:
                    raise LeagueNotFoundError("League not found or empty response")

                first_response = responses[0]

                # Check for error in response
                if "error" in first_response:
                    error_msg = first_response.get("error", {}).get("message", "Unknown error")
                    if "private" in error_msg.lower() or "access" in error_msg.lower():
                        raise LeaguePrivateError(
                            "This league is private. Please make the league public in Fantrax settings."
                        )
                    raise PlatformError(f"Fantrax API error: {error_msg}")

                # Check for pageError (e.g., WARNING_NOT_LOGGED_IN for private leagues)
                if "pageError" in first_response:
                    error_code = first_response.get("pageError", {}).get("code", "")
                    if error_code == "WARNING_NOT_LOGGED_IN":
                        raise LeaguePrivateError(
                            "This league requires authentication. "
                            "Fantrax private leagues are not currently supported."
                        )
                    raise PlatformError(f"Fantrax API error: {error_code}")

                return first_response.get("data", {})

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    raise LeaguePrivateError(
                        "This league is private. Please make the league public in Fantrax settings."
                    )
                raise PlatformError(f"Fantrax API error: {e}")
            except httpx.RequestError as e:
                raise PlatformError(f"Network error: {e}")

    async def _get_league_info(self, league_id: str) -> Dict[str, Any]:
        """
        Get league info, using cache if available.

        Args:
            league_id: The Fantrax league ID

        Returns:
            League info dict
        """
        if league_id in self._league_info_cache:
            return self._league_info_cache[league_id]

        data = await self._call_api("getFantasyLeagueInfo", {"leagueId": league_id})
        self._league_info_cache[league_id] = data
        return data

    async def validate_league(self, league_id: str, season: int) -> bool:
        """Validate that a league exists and is accessible."""
        try:
            league_info = await self._get_league_info(league_id)

            if not league_info:
                raise LeagueNotFoundError(f"League {league_id} not found")

            return True
        except (LeagueNotFoundError, LeaguePrivateError):
            raise
        except Exception as e:
            raise PlatformError(f"Error validating league: {e}")

    async def fetch_standings(
        self, league_id: str, season: int
    ) -> Tuple[Dict[int, Team], Dict[int, str]]:
        """
        Fetch current standings from Fantrax API.

        Returns:
            Tuple of (teams dict by id, division names dict)
        """
        # Fetch standings data
        standings_data = await self._call_api("getStandings", {"leagueId": league_id})
        league_info = await self._get_league_info(league_id)

        # Build team info mapping from league info
        team_info_map: Dict[str, Dict] = {}
        if "teamInfo" in league_info:
            for team_id, info in league_info.get("teamInfo", {}).items():
                team_info_map[team_id] = info

        # Get division info from league settings
        division_names: Dict[int, str] = {}
        divisions_list = league_info.get("divisions", [])
        for i, div in enumerate(divisions_list):
            div_id = i + 1  # Use 1-indexed division IDs
            div_name = div.get("name", f"Division {div_id}")
            division_names[div_id] = div_name

        # Build division ID mapping from team info
        team_division_map: Dict[str, int] = {}
        for team_id, info in team_info_map.items():
            div_id = info.get("divisionId")
            if div_id is not None:
                # Map string division ID to integer index
                for i, div in enumerate(divisions_list):
                    if div.get("id") == div_id:
                        team_division_map[team_id] = i + 1
                        break
                else:
                    team_division_map[team_id] = 0
            else:
                team_division_map[team_id] = 0

        # Parse standings from tableList
        teams: Dict[int, Team] = {}
        table_list = standings_data.get("tableList", [])

        if table_list:
            rows = table_list[0].get("rows", [])
            for row in rows:
                team_id_str = row.get("teamId", "")
                team_name = row.get("teamName", f"Team {team_id_str}")

                # Convert string ID to integer
                team_id_int = self._hash_team_id(team_id_str)

                # Get record
                wins = row.get("wins", 0) or 0
                losses = row.get("losses", 0) or 0
                ties = row.get("ties", 0) or 0

                # Get division ID
                division_id = team_division_map.get(team_id_str, 0)

                team = Team(
                    id=team_id_int,
                    name=team_name,
                    division_id=division_id,
                    wins=wins,
                    losses=losses,
                    ties=ties,
                    division_wins=0,
                    division_losses=0,
                    division_ties=0
                )
                teams[team_id_int] = team

                # Store mapping for later use
                if not hasattr(self, '_team_id_map'):
                    self._team_id_map: Dict[str, int] = {}
                self._team_id_map[team_id_str] = team_id_int

        # Calculate division records if there are divisions
        if division_names:
            await self._calculate_division_records(league_id, teams)

        return teams, division_names

    async def _calculate_division_records(
        self, league_id: str, teams: Dict[int, Team]
    ) -> None:
        """Calculate division records from completed matchups."""
        league_info = await self._get_league_info(league_id)

        # Get matchup periods from league info
        matchup_periods = league_info.get("matchupPeriods", [])

        for period in matchup_periods:
            # Skip incomplete periods
            if not period.get("completed", False):
                continue

            matchups = period.get("matchups", [])
            for matchup in matchups:
                team1_id_str = matchup.get("team1Id")
                team2_id_str = matchup.get("team2Id")

                if not team1_id_str or not team2_id_str:
                    continue

                team1_id = self._team_id_map.get(team1_id_str)
                team2_id = self._team_id_map.get(team2_id_str)

                if team1_id is None or team2_id is None:
                    continue

                team1 = teams.get(team1_id)
                team2 = teams.get(team2_id)

                if not team1 or not team2:
                    continue

                # Check if division game
                if team1.division_id != team2.division_id or team1.division_id == 0:
                    continue

                # Determine winner
                team1_score = matchup.get("team1Score", 0) or 0
                team2_score = matchup.get("team2Score", 0) or 0

                if team1_score > team2_score:
                    team1.division_wins += 1
                    team2.division_losses += 1
                elif team2_score > team1_score:
                    team2.division_wins += 1
                    team1.division_losses += 1
                else:
                    team1.division_ties += 1
                    team2.division_ties += 1

    async def fetch_schedule(
        self, league_id: str, season: int, teams: Dict[int, Team]
    ) -> Tuple[List[Matchup], int, int]:
        """
        Fetch schedule from Fantrax API and identify remaining matchups.

        Returns:
            Tuple of (remaining matchups, current week, total weeks)
        """
        league_info = await self._get_league_info(league_id)

        matchup_periods = league_info.get("matchupPeriods", [])
        total_weeks = len(matchup_periods)

        # Find current week (first non-completed period)
        current_week = 1
        for i, period in enumerate(matchup_periods):
            if period.get("current", False):
                current_week = i + 1
                break
            elif not period.get("completed", False):
                current_week = i + 1
                break
        else:
            current_week = total_weeks

        # Build remaining matchups
        remaining: List[Matchup] = []

        for i, period in enumerate(matchup_periods):
            week = i + 1

            # Skip completed periods
            if period.get("completed", False):
                continue

            matchups = period.get("matchups", [])
            for matchup in matchups:
                team1_id_str = matchup.get("team1Id")
                team2_id_str = matchup.get("team2Id")

                if not team1_id_str or not team2_id_str:
                    continue

                team1_id = self._team_id_map.get(team1_id_str)
                team2_id = self._team_id_map.get(team2_id_str)

                if team1_id is None or team2_id is None:
                    # Try to hash if not in map
                    team1_id = self._hash_team_id(team1_id_str)
                    team2_id = self._hash_team_id(team2_id_str)

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

        return remaining, current_week, total_weeks

    async def fetch_head_to_head(
        self, league_id: str, season: int, teams: Dict[int, Team]
    ) -> H2HDict:
        """
        Fetch head-to-head records between all teams.

        Returns:
            Dict mapping (team1_id, team2_id) -> (team1_wins, team2_wins, ties)
        """
        league_info = await self._get_league_info(league_id)

        h2h: Dict[Tuple[int, int], List[int]] = defaultdict(lambda: [0, 0, 0])

        matchup_periods = league_info.get("matchupPeriods", [])

        for period in matchup_periods:
            # Only count completed periods
            if not period.get("completed", False):
                continue

            matchups = period.get("matchups", [])
            for matchup in matchups:
                team1_id_str = matchup.get("team1Id")
                team2_id_str = matchup.get("team2Id")

                if not team1_id_str or not team2_id_str:
                    continue

                team1_id = self._team_id_map.get(team1_id_str)
                team2_id = self._team_id_map.get(team2_id_str)

                if team1_id is None or team2_id is None:
                    team1_id = self._hash_team_id(team1_id_str)
                    team2_id = self._hash_team_id(team2_id_str)

                team1_score = matchup.get("team1Score", 0) or 0
                team2_score = matchup.get("team2Score", 0) or 0

                # Use consistent key ordering (min_id, max_id)
                key = (min(team1_id, team2_id), max(team1_id, team2_id))

                if team1_score > team2_score:
                    if team1_id < team2_id:
                        h2h[key][0] += 1
                    else:
                        h2h[key][1] += 1
                elif team2_score > team1_score:
                    if team2_id < team1_id:
                        h2h[key][0] += 1
                    else:
                        h2h[key][1] += 1
                else:
                    h2h[key][2] += 1

        return {k: tuple(v) for k, v in h2h.items()}

    async def fetch_league_settings(
        self, league_id: str, season: int
    ) -> Dict[str, Any]:
        """
        Fetch league settings including playoff configuration.

        Returns:
            Dict with league settings
        """
        league_info = await self._get_league_info(league_id)

        if not league_info:
            raise LeagueNotFoundError(f"League {league_id} not found")

        # Get league name
        league_name = league_info.get("name", f"League {league_id}")

        # Get division info
        divisions_list = league_info.get("divisions", [])
        num_divisions = len(divisions_list)

        # Build division list
        division_list = []
        for i, div in enumerate(divisions_list):
            division_list.append({
                "id": i + 1,
                "name": div.get("name", f"Division {i + 1}")
            })

        # Get playoff spots from settings
        settings = league_info.get("settings", {})
        playoff_spots = settings.get("playoffTeams", 6)

        # Get total weeks from matchup periods
        matchup_periods = league_info.get("matchupPeriods", [])
        total_weeks = len(matchup_periods)

        return {
            "league_name": league_name,
            "playoff_spots": playoff_spots,
            "num_divisions": num_divisions,
            "total_weeks": total_weeks,
            "divisions": division_list
        }
