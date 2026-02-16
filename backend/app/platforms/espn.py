"""
ESPN Fantasy platform adapter.

Fetches league data from ESPN's public API for fantasy basketball, football,
and baseball leagues.
"""

import httpx
from collections import defaultdict
from typing import Dict, List, Tuple, Any, Optional

from .base import (
    PlatformAdapter,
    LeagueNotFoundError,
    LeaguePrivateError,
    PlatformError
)
from ..simulator.models import Team, Matchup, H2HDict
from ..core.sports import Sport, ESPN_SPORT_CODES


class ESPNAdapter(PlatformAdapter):
    """ESPN Fantasy platform adapter supporting basketball, football, and baseball."""

    BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/{sport_code}/seasons/{season}/segments/0/leagues/{league_id}"

    def __init__(self, sport: Sport = Sport.BASKETBALL, timeout: float = 30.0):
        """
        Initialize the ESPN adapter.

        Args:
            sport: The sport type (basketball, football, baseball)
            timeout: HTTP request timeout in seconds
        """
        self.sport = sport
        self.timeout = timeout

    def _get_sport_code(self) -> str:
        """Get the ESPN API sport code for the current sport."""
        return ESPN_SPORT_CODES[self.sport]

    @property
    def platform_name(self) -> str:
        return "espn"

    def _get_url(self, league_id: str, season: int) -> str:
        """Build the API URL for a league."""
        return self.BASE_URL.format(
            sport_code=self._get_sport_code(),
            season=season,
            league_id=league_id
        )

    async def _fetch_league_data(
        self, league_id: str, season: int, views: List[str]
    ) -> Dict[str, Any]:
        """
        Fetch league data with specified views from ESPN API.

        Args:
            league_id: The league identifier
            season: The season year
            views: List of views to request (e.g., ["mTeam", "mSettings"])

        Returns:
            JSON response data

        Raises:
            LeagueNotFoundError: If the league doesn't exist
            LeaguePrivateError: If the league is private
            PlatformError: If there's an API error
        """
        url = self._get_url(league_id, season)
        params = {"view": views}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(url, params=params)

                if response.status_code == 404:
                    raise LeagueNotFoundError(
                        f"League {league_id} not found for season {season}"
                    )

                if response.status_code == 401:
                    raise LeaguePrivateError(
                        f"League {league_id} is private. Public leagues only."
                    )

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                raise PlatformError(f"ESPN API error: {e}")
            except httpx.RequestError as e:
                raise PlatformError(f"Network error: {e}")

    async def validate_league(self, league_id: str, season: int) -> bool:
        """Validate that a league exists and is accessible."""
        try:
            await self._fetch_league_data(league_id, season, ["mSettings"])
            return True
        except (LeagueNotFoundError, LeaguePrivateError):
            raise
        except Exception as e:
            raise PlatformError(f"Error validating league: {e}")

    async def fetch_standings(
        self, league_id: str, season: int
    ) -> Tuple[Dict[int, Team], Dict[int, str]]:
        """
        Fetch current standings from ESPN API.

        Returns:
            Tuple of (teams dict by id, division names dict)
        """
        data = await self._fetch_league_data(
            league_id, season, ["mTeam", "mSettings", "mStandings"]
        )

        # Get division names from settings
        division_names = {}
        settings = data.get("settings", {})
        schedule_settings = settings.get("scheduleSettings", {})
        divisions = schedule_settings.get("divisions", [])
        for div in divisions:
            division_names[div["id"]] = div.get("name", f"Division {div['id']}")

        # Build teams dict
        teams = {}
        for team_data in data.get("teams", []):
            team_id = team_data["id"]
            name = team_data.get("name", team_data.get("nickname", f"Team {team_id}"))
            division_id = team_data.get("divisionId", 0)

            # Get record from the team data
            record = team_data.get("record", {}).get("overall", {})
            wins = record.get("wins", 0)
            losses = record.get("losses", 0)
            ties = record.get("ties", 0)

            # Get division record
            div_record = team_data.get("record", {}).get("division", {})
            division_wins = div_record.get("wins", 0)
            division_losses = div_record.get("losses", 0)
            division_ties = div_record.get("ties", 0)

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
        Fetch schedule from ESPN API and identify remaining matchups.

        Returns:
            Tuple of (remaining matchups, current week, total weeks)
        """
        data = await self._fetch_league_data(
            league_id, season, ["mMatchup", "mSettings"]
        )

        # Get season info from settings
        settings = data.get("settings", {})
        schedule_settings = settings.get("scheduleSettings", {})

        # matchupPeriodCount is the total number of regular season weeks
        total_weeks = schedule_settings.get("matchupPeriodCount", 18)

        # Get current week from status
        status = data.get("status", {})
        current_week = status.get("currentMatchupPeriod", 1)

        schedule = data.get("schedule", [])

        # Build list of remaining matchups
        remaining = []
        for matchup in schedule:
            week = matchup.get("matchupPeriodId", 0)

            # Skip past weeks and playoff weeks
            if week < current_week or week > total_weeks:
                continue

            home = matchup.get("home", {})
            away = matchup.get("away", {})

            home_id = home.get("teamId")
            away_id = away.get("teamId")

            if home_id is None or away_id is None:
                continue

            # Check if this is a division game
            home_team = teams.get(home_id)
            away_team = teams.get(away_id)
            is_division_game = (
                home_team and away_team and
                home_team.division_id == away_team.division_id
            )

            # Only add if not yet played (no winner determined)
            winner = matchup.get("winner")
            if winner == "UNDECIDED" or winner is None:
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
        data = await self._fetch_league_data(league_id, season, ["mMatchup", "mSettings"])
        schedule = data.get("schedule", [])

        # Get regular season week count to filter out playoff matchups
        settings = data.get("settings", {})
        schedule_settings = settings.get("scheduleSettings", {})
        total_weeks = schedule_settings.get("matchupPeriodCount", 18)

        # Track H2H records
        h2h: Dict[Tuple[int, int], List[int]] = defaultdict(lambda: [0, 0, 0])

        for matchup in schedule:
            week = matchup.get("matchupPeriodId", 0)

            # Skip playoff matchups - only count regular season for tiebreakers
            if week > total_weeks:
                continue
            home = matchup.get("home", {})
            away = matchup.get("away", {})

            home_id = home.get("teamId")
            away_id = away.get("teamId")
            winner = matchup.get("winner")

            if home_id is None or away_id is None:
                continue

            # Determine matchup result
            if winner == "HOME":
                # Home team won
                key = (min(home_id, away_id), max(home_id, away_id))
                if home_id < away_id:
                    h2h[key][0] += 1
                else:
                    h2h[key][1] += 1
            elif winner == "AWAY":
                # Away team won
                key = (min(home_id, away_id), max(home_id, away_id))
                if away_id < home_id:
                    h2h[key][0] += 1
                else:
                    h2h[key][1] += 1
            elif winner == "TIE":
                key = (min(home_id, away_id), max(home_id, away_id))
                h2h[key][2] += 1

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
        data = await self._fetch_league_data(league_id, season, ["mSettings"])

        settings = data.get("settings", {})
        schedule_settings = settings.get("scheduleSettings", {})

        # Get playoff settings
        playoff_team_count = schedule_settings.get("playoffTeamCount", 6)
        divisions = schedule_settings.get("divisions", [])
        matchup_period_count = schedule_settings.get("matchupPeriodCount", 18)

        # Get league name
        league_name = settings.get("name", f"League {league_id}")

        return {
            "league_name": league_name,
            "playoff_spots": playoff_team_count,
            "num_divisions": len(divisions),
            "total_weeks": matchup_period_count,
            "divisions": [
                {"id": d["id"], "name": d.get("name", f"Division {d['id']}")}
                for d in divisions
            ]
        }
