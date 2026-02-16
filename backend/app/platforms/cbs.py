"""
CBS Sports Fantasy platform adapter.

Fetches league data from CBS Sports Fantasy API for basketball, football,
baseball, and hockey leagues. Requires OAuth 2.0 authentication.
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Any, Optional

import httpx

from .base import (
    PlatformAdapter,
    LeagueNotFoundError,
    LeaguePrivateError,
    PlatformError
)
from ..simulator.models import Team, Matchup, H2HDict
from ..core.sports import Sport, CBS_SPORT_CODES
from ..core.cbs_oauth import refresh_access_token, CBSOAuthError, CBSTokenExpiredError
from ..db.models import CBSCredential


class CBSAdapter(PlatformAdapter):
    """CBS Sports Fantasy platform adapter supporting basketball, football, baseball, and hockey."""

    BASE_URL = "https://api.cbssports.com/fantasy"

    def __init__(
        self,
        sport: Sport = Sport.BASKETBALL,
        credential: Optional[CBSCredential] = None,
        timeout: float = 30.0
    ):
        """
        Initialize the CBS adapter.

        Args:
            sport: The sport type (basketball, football, baseball, hockey)
            credential: CBSCredential object with OAuth tokens
            timeout: HTTP request timeout in seconds
        """
        self.sport = sport
        self.credential = credential
        self.timeout = timeout
        self._access_token: Optional[str] = None
        self._token_refreshed = False

    def _get_sport_code(self) -> str:
        """Get the CBS sport code for the current sport."""
        return CBS_SPORT_CODES[self.sport]

    @property
    def platform_name(self) -> str:
        return "cbs"

    async def _ensure_valid_token(self) -> str:
        """
        Ensure we have a valid access token, refreshing if necessary.

        Returns:
            Valid access token

        Raises:
            PlatformError: If no credential is available
            CBSTokenExpiredError: If token refresh fails
        """
        if self.credential is None:
            raise PlatformError("CBS credential is required for this operation")

        # Check if token is expired or will expire soon (within 5 minutes)
        now = datetime.now(timezone.utc)
        if self.credential.is_expired or (self.credential.expires_at - now).total_seconds() < 300:
            if self._token_refreshed:
                # Already tried to refresh, something is wrong
                raise CBSTokenExpiredError("Token refresh failed. Please reconnect your CBS account.")

            try:
                new_tokens = await refresh_access_token(self.credential.refresh_token)
                # Update the credential object (caller should persist this)
                self.credential.access_token = new_tokens["access_token"]
                self.credential.refresh_token = new_tokens["refresh_token"]
                self.credential.expires_at = new_tokens["expires_at"]
                self._token_refreshed = True
            except CBSOAuthError:
                raise

        return self.credential.access_token

    async def _fetch_api(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> dict:
        """
        Make an authenticated API call to CBS Sports Fantasy API.

        Args:
            endpoint: API endpoint path (after /fantasy/)
            params: Optional query parameters

        Returns:
            Parsed JSON response

        Raises:
            LeagueNotFoundError: If the league doesn't exist
            LeaguePrivateError: If the league is private/inaccessible
            PlatformError: If there's an API error
        """
        access_token = await self._ensure_valid_token()
        url = f"{self.BASE_URL}/{endpoint}"

        # Add response_format=json to all requests
        if params is None:
            params = {}
        params["response_format"] = "json"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(
                    url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    }
                )

                if response.status_code == 404:
                    raise LeagueNotFoundError("League not found")

                if response.status_code == 401:
                    raise LeaguePrivateError(
                        "CBS authentication failed. Please reconnect your CBS account."
                    )

                if response.status_code == 403:
                    raise LeaguePrivateError(
                        "You don't have access to this league."
                    )

                response.raise_for_status()

                data = response.json()

                # CBS API wraps responses in a "body" key
                if "body" in data:
                    return data["body"]
                return data

            except httpx.HTTPStatusError as e:
                raise PlatformError(f"CBS API error: {e}")
            except httpx.RequestError as e:
                raise PlatformError(f"Network error: {e}")

    async def validate_league(self, league_id: str, season: int) -> bool:
        """Validate that a league exists and is accessible."""
        sport_code = self._get_sport_code()
        try:
            await self._fetch_api(f"league/{sport_code}/{league_id}")
            return True
        except (LeagueNotFoundError, LeaguePrivateError):
            raise
        except Exception as e:
            raise PlatformError(f"Error validating league: {e}")

    async def fetch_standings(
        self, league_id: str, season: int
    ) -> Tuple[Dict[int, Team], Dict[int, str]]:
        """
        Fetch current standings from CBS API.

        Returns:
            Tuple of (teams dict by id, division names dict)
        """
        sport_code = self._get_sport_code()
        data = await self._fetch_api(f"league/{sport_code}/{league_id}/standings")

        teams: Dict[int, Team] = {}
        division_names: Dict[int, str] = {}

        # Parse standings data
        standings = data.get("standings", {})
        team_list = standings.get("teams", [])

        for team_data in team_list:
            team_id = int(team_data.get("id", 0))
            name = team_data.get("name", f"Team {team_id}")

            # Get division info
            division_id = int(team_data.get("division_id", 0))
            division_name = team_data.get("division_name", "")
            if division_id and division_name:
                division_names[division_id] = division_name

            # Get record
            wins = int(team_data.get("wins", 0))
            losses = int(team_data.get("losses", 0))
            ties = int(team_data.get("ties", 0))

            # Get division record if available
            division_wins = int(team_data.get("division_wins", 0))
            division_losses = int(team_data.get("division_losses", 0))
            division_ties = int(team_data.get("division_ties", 0))

            team = Team(
                id=team_id,
                name=name,
                division_id=division_id,
                wins=wins,
                losses=losses,
                ties=ties,
                division_wins=division_wins,
                division_losses=division_losses,
                division_ties=division_ties
            )
            teams[team_id] = team

        return teams, division_names

    async def fetch_schedule(
        self, league_id: str, season: int, teams: Dict[int, Team]
    ) -> Tuple[List[Matchup], int, int]:
        """
        Fetch schedule from CBS API and identify remaining matchups.

        Returns:
            Tuple of (remaining matchups, current week, total weeks)
        """
        sport_code = self._get_sport_code()
        data = await self._fetch_api(f"league/{sport_code}/{league_id}/scoreboard")

        # Get current week and total weeks
        scoreboard = data.get("scoreboard", {})
        current_week = int(scoreboard.get("current_week", 1))

        # Fetch settings to get total weeks
        settings = await self._fetch_league_settings_internal(league_id, season)
        total_weeks = settings.get("total_weeks", 18)

        remaining: List[Matchup] = []

        # Fetch matchups for remaining weeks
        for week in range(current_week, total_weeks + 1):
            try:
                week_data = await self._fetch_api(
                    f"league/{sport_code}/{league_id}/scoreboard",
                    params={"week": week}
                )
            except PlatformError:
                continue

            week_scoreboard = week_data.get("scoreboard", {})
            matchups = week_scoreboard.get("matchups", [])

            for matchup_data in matchups:
                # Skip completed matchups
                status = matchup_data.get("status", "")
                if status.lower() in ("final", "completed"):
                    continue

                home_team_id = int(matchup_data.get("home_team_id", 0))
                away_team_id = int(matchup_data.get("away_team_id", 0))

                if not home_team_id or not away_team_id:
                    continue

                # Check if division game
                home_team = teams.get(home_team_id)
                away_team = teams.get(away_team_id)
                is_division_game = (
                    home_team and away_team and
                    home_team.division_id == away_team.division_id and
                    home_team.division_id != 0
                )

                remaining.append(Matchup(
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
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
        sport_code = self._get_sport_code()

        # Get total weeks
        settings = await self._fetch_league_settings_internal(league_id, season)
        total_weeks = settings.get("total_weeks", 18)

        # Track H2H records
        h2h: Dict[Tuple[int, int], List[int]] = defaultdict(lambda: [0, 0, 0])

        # Fetch completed matchups for all weeks
        for week in range(1, total_weeks + 1):
            try:
                week_data = await self._fetch_api(
                    f"league/{sport_code}/{league_id}/scoreboard",
                    params={"week": week}
                )
            except PlatformError:
                continue

            week_scoreboard = week_data.get("scoreboard", {})
            matchups = week_scoreboard.get("matchups", [])

            for matchup_data in matchups:
                # Only include completed matchups
                status = matchup_data.get("status", "")
                if status.lower() not in ("final", "completed"):
                    continue

                home_team_id = int(matchup_data.get("home_team_id", 0))
                away_team_id = int(matchup_data.get("away_team_id", 0))

                if not home_team_id or not away_team_id:
                    continue

                home_score = float(matchup_data.get("home_score", 0))
                away_score = float(matchup_data.get("away_score", 0))

                key = (min(home_team_id, away_team_id), max(home_team_id, away_team_id))

                if home_score > away_score:
                    # Home team won
                    if home_team_id < away_team_id:
                        h2h[key][0] += 1
                    else:
                        h2h[key][1] += 1
                elif away_score > home_score:
                    # Away team won
                    if away_team_id < home_team_id:
                        h2h[key][0] += 1
                    else:
                        h2h[key][1] += 1
                else:
                    # Tie
                    h2h[key][2] += 1

        # Convert lists to tuples
        return {k: tuple(v) for k, v in h2h.items()}

    async def _fetch_league_settings_internal(
        self, league_id: str, season: int
    ) -> Dict[str, Any]:
        """Internal method to fetch league settings."""
        sport_code = self._get_sport_code()
        data = await self._fetch_api(f"league/{sport_code}/{league_id}/rules")

        rules = data.get("rules", {})

        # Get league name
        league_name = rules.get("league_name", f"League {league_id}")

        # Get playoff settings
        playoff_team_count = int(rules.get("playoff_teams", 6))

        # Get division info
        divisions = rules.get("divisions", [])
        num_divisions = len(divisions)

        # Get regular season weeks
        total_weeks = int(rules.get("regular_season_weeks", 18))

        return {
            "league_name": league_name,
            "playoff_spots": playoff_team_count,
            "num_divisions": num_divisions,
            "total_weeks": total_weeks,
        }

    async def fetch_league_settings(
        self, league_id: str, season: int
    ) -> Dict[str, Any]:
        """
        Fetch league settings including playoff configuration.

        Returns:
            Dict with league settings
        """
        settings = await self._fetch_league_settings_internal(league_id, season)

        # Get division details
        sport_code = self._get_sport_code()
        data = await self._fetch_api(f"league/{sport_code}/{league_id}/rules")

        rules = data.get("rules", {})
        divisions_list = []

        divisions = rules.get("divisions", [])
        for div in divisions:
            div_id = int(div.get("id", 0))
            div_name = div.get("name", f"Division {div_id}")
            divisions_list.append({"id": div_id, "name": div_name})

        settings["divisions"] = divisions_list
        return settings
