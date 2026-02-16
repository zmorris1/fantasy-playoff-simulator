"""
Yahoo Fantasy platform adapter.

Fetches league data from Yahoo Fantasy API for basketball, football,
and baseball leagues. Requires OAuth 2.0 authentication.
"""

import re
import xml.etree.ElementTree as ET
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
from ..core.sports import Sport, YAHOO_GAME_KEYS
from ..core.yahoo_oauth import refresh_access_token, YahooOAuthError, YahooTokenExpiredError
from ..db.models import YahooCredential


class YahooAdapter(PlatformAdapter):
    """Yahoo Fantasy platform adapter supporting basketball, football, and baseball."""

    BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"
    XML_NS = {"yh": "http://fantasysports.yahooapis.com/fantasy/v2/base.rng"}

    def __init__(
        self,
        sport: Sport = Sport.BASKETBALL,
        credential: Optional[YahooCredential] = None,
        timeout: float = 30.0
    ):
        """
        Initialize the Yahoo adapter.

        Args:
            sport: The sport type (basketball, football, baseball)
            credential: YahooCredential object with OAuth tokens
            timeout: HTTP request timeout in seconds
        """
        self.sport = sport
        self.credential = credential
        self.timeout = timeout
        self._access_token: Optional[str] = None
        self._token_refreshed = False

    def _get_game_key(self) -> str:
        """Get the Yahoo game key for the current sport."""
        return YAHOO_GAME_KEYS[self.sport]

    @property
    def platform_name(self) -> str:
        return "yahoo"

    def _build_league_key(self, league_id: str, season: int) -> str:
        """
        Build the Yahoo league key.

        Yahoo league keys have the format: {game_key}.l.{league_id}
        where game_key is sport-specific (e.g., nba, nfl, mlb)

        For specific seasons, we need to look up the game_id first,
        but for simplicity we'll use the current game key format.
        """
        game_key = self._get_game_key()
        return f"{game_key}.l.{league_id}"

    async def _ensure_valid_token(self) -> str:
        """
        Ensure we have a valid access token, refreshing if necessary.

        Returns:
            Valid access token

        Raises:
            PlatformError: If no credential is available
            YahooTokenExpiredError: If token refresh fails
        """
        if self.credential is None:
            raise PlatformError("Yahoo credential is required for this operation")

        # Check if token is expired or will expire soon (within 5 minutes)
        now = datetime.now(timezone.utc)
        if self.credential.is_expired or (self.credential.expires_at - now).total_seconds() < 300:
            if self._token_refreshed:
                # Already tried to refresh, something is wrong
                raise YahooTokenExpiredError("Token refresh failed. Please reconnect your Yahoo account.")

            try:
                new_tokens = await refresh_access_token(self.credential.refresh_token)
                # Update the credential object (caller should persist this)
                self.credential.access_token = new_tokens["access_token"]
                self.credential.refresh_token = new_tokens["refresh_token"]
                self.credential.expires_at = new_tokens["expires_at"]
                self._token_refreshed = True
            except YahooOAuthError:
                raise

        return self.credential.access_token

    async def _fetch_api(self, endpoint: str) -> ET.Element:
        """
        Make an authenticated API call to Yahoo Fantasy API.

        Args:
            endpoint: API endpoint path (after /fantasy/v2)

        Returns:
            Parsed XML root element

        Raises:
            LeagueNotFoundError: If the league doesn't exist
            LeaguePrivateError: If the league is private/inaccessible
            PlatformError: If there's an API error
        """
        access_token = await self._ensure_valid_token()
        url = f"{self.BASE_URL}/{endpoint}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/xml",
                    }
                )

                if response.status_code == 404:
                    raise LeagueNotFoundError("League not found")

                if response.status_code == 401:
                    raise LeaguePrivateError(
                        "Yahoo authentication failed. Please reconnect your Yahoo account."
                    )

                if response.status_code == 403:
                    raise LeaguePrivateError(
                        "You don't have access to this league."
                    )

                response.raise_for_status()

                # Parse XML response
                return ET.fromstring(response.text)

            except httpx.HTTPStatusError as e:
                raise PlatformError(f"Yahoo API error: {e}")
            except httpx.RequestError as e:
                raise PlatformError(f"Network error: {e}")
            except ET.ParseError as e:
                raise PlatformError(f"Failed to parse Yahoo API response: {e}")

    def _find_text(self, element: ET.Element, path: str, default: str = "") -> str:
        """Find text in XML element with namespace handling."""
        # Try with namespace first
        result = element.find(f"yh:{path}", self.XML_NS)
        if result is not None and result.text:
            return result.text

        # Try without namespace (some responses don't use it)
        result = element.find(path)
        if result is not None and result.text:
            return result.text

        return default

    def _find_int(self, element: ET.Element, path: str, default: int = 0) -> int:
        """Find integer in XML element."""
        text = self._find_text(element, path)
        try:
            return int(text) if text else default
        except ValueError:
            return default

    def _find_element(self, element: ET.Element, path: str) -> Optional[ET.Element]:
        """Find child element with namespace handling."""
        result = element.find(f"yh:{path}", self.XML_NS)
        if result is not None:
            return result
        return element.find(path)

    def _find_all(self, element: ET.Element, path: str) -> List[ET.Element]:
        """Find all matching elements with namespace handling."""
        results = element.findall(f"yh:{path}", self.XML_NS)
        if results:
            return results
        return element.findall(path)

    async def validate_league(self, league_id: str, season: int) -> bool:
        """Validate that a league exists and is accessible."""
        league_key = self._build_league_key(league_id, season)
        try:
            await self._fetch_api(f"league/{league_key}")
            return True
        except (LeagueNotFoundError, LeaguePrivateError):
            raise
        except Exception as e:
            raise PlatformError(f"Error validating league: {e}")

    async def fetch_standings(
        self, league_id: str, season: int
    ) -> Tuple[Dict[int, Team], Dict[int, str]]:
        """
        Fetch current standings from Yahoo API.

        Returns:
            Tuple of (teams dict by id, division names dict)
        """
        league_key = self._build_league_key(league_id, season)
        root = await self._fetch_api(f"league/{league_key}/standings")

        # Find league element
        league = self._find_element(root, "league")
        if league is None:
            league = root  # Root might be the league element

        # Get division names
        division_names: Dict[int, str] = {}
        standings = self._find_element(league, "standings")
        if standings is not None:
            teams_element = self._find_element(standings, "teams")
        else:
            teams_element = self._find_element(league, "teams")

        # Build teams dict
        teams: Dict[int, Team] = {}

        if teams_element is not None:
            for team_elem in self._find_all(teams_element, "team"):
                team_key = self._find_text(team_elem, "team_key")
                # Extract team ID from team_key (format: {game_key}.l.{league_id}.t.{team_id})
                team_id_match = re.search(r'\.t\.(\d+)$', team_key)
                team_id = int(team_id_match.group(1)) if team_id_match else 0

                name = self._find_text(team_elem, "name", f"Team {team_id}")

                # Get division info
                division_id = self._find_int(team_elem, "division_id", 0)
                if division_id and division_id not in division_names:
                    division_names[division_id] = f"Division {division_id}"

                # Get standings data
                team_standings = self._find_element(team_elem, "team_standings")
                if team_standings is not None:
                    outcome_totals = self._find_element(team_standings, "outcome_totals")
                    if outcome_totals is not None:
                        wins = self._find_int(outcome_totals, "wins", 0)
                        losses = self._find_int(outcome_totals, "losses", 0)
                        ties = self._find_int(outcome_totals, "ties", 0)
                    else:
                        wins = losses = ties = 0

                    # Get division record if available
                    divisional_outcomes = self._find_element(team_standings, "divisional_outcome_totals")
                    if divisional_outcomes is not None:
                        division_wins = self._find_int(divisional_outcomes, "wins", 0)
                        division_losses = self._find_int(divisional_outcomes, "losses", 0)
                        division_ties = self._find_int(divisional_outcomes, "ties", 0)
                    else:
                        division_wins = division_losses = division_ties = 0
                else:
                    wins = losses = ties = 0
                    division_wins = division_losses = division_ties = 0

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
        Fetch schedule from Yahoo API and identify remaining matchups.

        Returns:
            Tuple of (remaining matchups, current week, total weeks)
        """
        league_key = self._build_league_key(league_id, season)
        root = await self._fetch_api(f"league/{league_key}/scoreboard")

        league = self._find_element(root, "league")
        if league is None:
            league = root

        # Get current week
        current_week = self._find_int(league, "current_week", 1)

        # Get total weeks from settings
        settings = await self._fetch_league_settings_internal(league_id, season)
        total_weeks = settings.get("total_weeks", 18)

        # Fetch all matchups
        remaining: List[Matchup] = []

        # We need to fetch matchups for remaining weeks
        for week in range(current_week, total_weeks + 1):
            week_root = await self._fetch_api(f"league/{league_key}/scoreboard;week={week}")
            week_league = self._find_element(week_root, "league")
            if week_league is None:
                week_league = week_root

            scoreboard = self._find_element(week_league, "scoreboard")
            if scoreboard is None:
                continue

            matchups_elem = self._find_element(scoreboard, "matchups")
            if matchups_elem is None:
                continue

            for matchup_elem in self._find_all(matchups_elem, "matchup"):
                status = self._find_text(matchup_elem, "status", "")
                # Only include matchups that haven't completed
                if status.lower() in ("postevent", "postgame"):
                    continue

                teams_in_matchup = self._find_element(matchup_elem, "teams")
                if teams_in_matchup is None:
                    continue

                team_elems = self._find_all(teams_in_matchup, "team")
                if len(team_elems) < 2:
                    continue

                # Extract team IDs
                team_ids = []
                for t_elem in team_elems[:2]:
                    t_key = self._find_text(t_elem, "team_key")
                    t_match = re.search(r'\.t\.(\d+)$', t_key)
                    if t_match:
                        team_ids.append(int(t_match.group(1)))

                if len(team_ids) < 2:
                    continue

                home_id, away_id = team_ids[0], team_ids[1]

                # Check if division game
                home_team = teams.get(home_id)
                away_team = teams.get(away_id)
                is_division_game = (
                    home_team and away_team and
                    home_team.division_id == away_team.division_id and
                    home_team.division_id != 0
                )

                remaining.append(Matchup(
                    home_team_id=home_id,
                    away_team_id=away_id,
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
        league_key = self._build_league_key(league_id, season)

        # Get total weeks
        settings = await self._fetch_league_settings_internal(league_id, season)
        total_weeks = settings.get("total_weeks", 18)

        # Track H2H records
        h2h: Dict[Tuple[int, int], List[int]] = defaultdict(lambda: [0, 0, 0])

        # Fetch completed matchups for all weeks
        for week in range(1, total_weeks + 1):
            try:
                week_root = await self._fetch_api(f"league/{league_key}/scoreboard;week={week}")
            except PlatformError:
                continue

            week_league = self._find_element(week_root, "league")
            if week_league is None:
                week_league = week_root

            scoreboard = self._find_element(week_league, "scoreboard")
            if scoreboard is None:
                continue

            matchups_elem = self._find_element(scoreboard, "matchups")
            if matchups_elem is None:
                continue

            for matchup_elem in self._find_all(matchups_elem, "matchup"):
                status = self._find_text(matchup_elem, "status", "")
                # Only include completed matchups
                if status.lower() not in ("postevent", "postgame"):
                    continue

                teams_in_matchup = self._find_element(matchup_elem, "teams")
                if teams_in_matchup is None:
                    continue

                team_elems = self._find_all(teams_in_matchup, "team")
                if len(team_elems) < 2:
                    continue

                # Extract team IDs and results
                results = []
                for t_elem in team_elems[:2]:
                    t_key = self._find_text(t_elem, "team_key")
                    t_match = re.search(r'\.t\.(\d+)$', t_key)
                    if not t_match:
                        continue

                    team_id = int(t_match.group(1))
                    win_prob = self._find_text(t_elem, "win_probability", "0")

                    # Determine winner based on win_probability (1.0 = won, 0.0 = lost, 0.5 = tie)
                    try:
                        prob = float(win_prob)
                        results.append((team_id, prob))
                    except ValueError:
                        results.append((team_id, 0.0))

                if len(results) < 2:
                    continue

                team1_id, team1_prob = results[0]
                team2_id, team2_prob = results[1]

                key = (min(team1_id, team2_id), max(team1_id, team2_id))

                if team1_prob > team2_prob:
                    # Team 1 won
                    if team1_id < team2_id:
                        h2h[key][0] += 1
                    else:
                        h2h[key][1] += 1
                elif team2_prob > team1_prob:
                    # Team 2 won
                    if team2_id < team1_id:
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
        league_key = self._build_league_key(league_id, season)
        root = await self._fetch_api(f"league/{league_key}/settings")

        league = self._find_element(root, "league")
        if league is None:
            league = root

        # Get league name
        league_name = self._find_text(league, "name", f"League {league_id}")

        # Get settings
        settings_elem = self._find_element(league, "settings")

        playoff_team_count = 6
        num_divisions = 0
        total_weeks = 18

        if settings_elem is not None:
            # Get playoff team count
            playoff_team_count = self._find_int(settings_elem, "playoff_team_count", 6)

            # Get number of divisions
            divisions = self._find_element(settings_elem, "divisions")
            if divisions is not None:
                num_divisions = len(self._find_all(divisions, "division"))

            # Get regular season weeks
            # In Yahoo, num_playoff_weeks tells us playoffs length
            num_playoff_weeks = self._find_int(settings_elem, "num_playoff_weeks", 3)
            end_week = self._find_int(league, "end_week", 21)
            total_weeks = end_week - num_playoff_weeks

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
        league_key = self._build_league_key(league_id, season)
        root = await self._fetch_api(f"league/{league_key}/settings")

        league = self._find_element(root, "league")
        if league is None:
            league = root

        settings_elem = self._find_element(league, "settings")
        divisions_list = []

        if settings_elem is not None:
            divisions = self._find_element(settings_elem, "divisions")
            if divisions is not None:
                for div in self._find_all(divisions, "division"):
                    div_id = self._find_int(div, "division_id", 0)
                    div_name = self._find_text(div, "name", f"Division {div_id}")
                    divisions_list.append({"id": div_id, "name": div_name})

        settings["divisions"] = divisions_list
        return settings
