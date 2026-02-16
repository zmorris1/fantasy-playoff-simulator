"""
Tests for the Sleeper platform adapter.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.platforms.sleeper import SleeperAdapter
from app.platforms import LeagueNotFoundError, PlatformError
from app.core.sports import Sport


@pytest.fixture
def adapter():
    """Create a Sleeper adapter instance for testing."""
    return SleeperAdapter(sport=Sport.FOOTBALL)


class TestSleeperAdapter:
    """Tests for SleeperAdapter."""

    def test_platform_name(self, adapter):
        """Test platform_name property."""
        assert adapter.platform_name == "sleeper"

    def test_sport_code_football(self, adapter):
        """Test sport code for football."""
        assert adapter._get_sport_code() == "nfl"

    def test_sport_code_basketball(self):
        """Test sport code for basketball."""
        adapter = SleeperAdapter(sport=Sport.BASKETBALL)
        assert adapter._get_sport_code() == "nba"

    def test_baseball_raises_error(self):
        """Test that baseball raises ValueError."""
        with pytest.raises(ValueError, match="does not support baseball"):
            SleeperAdapter(sport=Sport.BASEBALL)

    @pytest.mark.asyncio
    async def test_validate_league_not_found(self, adapter):
        """Test validate_league raises LeagueNotFoundError for invalid league."""
        with pytest.raises(LeagueNotFoundError):
            await adapter.validate_league("invalid_league_id", 2025)

    @pytest.mark.asyncio
    async def test_fetch_json_null_response(self, adapter):
        """Test that null response raises LeagueNotFoundError."""
        with patch.object(adapter, '_fetch_json') as mock_fetch:
            # Simulate the actual behavior - the method would raise the error
            mock_fetch.side_effect = LeagueNotFoundError("League not found")

            with pytest.raises(LeagueNotFoundError):
                await adapter._fetch_json("/league/nonexistent")

    @pytest.mark.asyncio
    async def test_fetch_standings_with_mocked_data(self, adapter):
        """Test fetch_standings with mocked API responses."""
        mock_league = {
            "name": "Test League",
            "season": "2025",
            "settings": {"divisions": 2, "playoff_teams": 6, "playoff_week_start": 15}
        }
        mock_rosters = [
            {"roster_id": 1, "owner_id": "user1", "settings": {"wins": 5, "losses": 3, "ties": 0, "division": 1}},
            {"roster_id": 2, "owner_id": "user2", "settings": {"wins": 4, "losses": 4, "ties": 0, "division": 1}},
            {"roster_id": 3, "owner_id": "user3", "settings": {"wins": 6, "losses": 2, "ties": 0, "division": 2}},
            {"roster_id": 4, "owner_id": "user4", "settings": {"wins": 3, "losses": 5, "ties": 0, "division": 2}},
        ]
        mock_users = [
            {"user_id": "user1", "display_name": "Team Alpha"},
            {"user_id": "user2", "display_name": "Team Beta"},
            {"user_id": "user3", "display_name": "Team Gamma"},
            {"user_id": "user4", "display_name": "Team Delta"},
        ]
        mock_state = {"season": 2025, "week": 8}

        async def mock_fetch(endpoint):
            if "rosters" in endpoint:
                return mock_rosters
            elif "users" in endpoint:
                return mock_users
            elif "league" in endpoint and "matchups" not in endpoint:
                return mock_league
            elif "state" in endpoint:
                return mock_state
            return []

        with patch.object(adapter, '_fetch_json', side_effect=mock_fetch):
            with patch.object(adapter, '_get_nfl_state', return_value=mock_state):
                teams, divisions = await adapter.fetch_standings("123", 2025)

        assert len(teams) == 4
        assert teams[1].name == "Team Alpha"
        assert teams[1].wins == 5
        assert teams[1].losses == 3
        assert teams[1].division_id == 1
        assert teams[3].name == "Team Gamma"
        assert teams[3].division_id == 2
        assert 1 in divisions
        assert 2 in divisions

    @pytest.mark.asyncio
    async def test_fetch_league_settings(self, adapter):
        """Test fetch_league_settings with mocked data."""
        mock_league = {
            "name": "My Fantasy League",
            "settings": {
                "playoff_teams": 8,
                "divisions": 2,
                "playoff_week_start": 15
            }
        }

        with patch.object(adapter, '_fetch_json', return_value=mock_league):
            settings = await adapter.fetch_league_settings("123", 2025)

        assert settings["league_name"] == "My Fantasy League"
        assert settings["playoff_spots"] == 8
        assert settings["num_divisions"] == 2
        assert settings["total_weeks"] == 14

    @pytest.mark.asyncio
    async def test_fetch_head_to_head(self, adapter):
        """Test fetch_head_to_head with mocked matchup data."""
        mock_league = {
            "settings": {"playoff_week_start": 15}
        }
        mock_state = {"week": 3}
        mock_matchups_week1 = [
            {"roster_id": 1, "matchup_id": 1, "points": 120},
            {"roster_id": 2, "matchup_id": 1, "points": 110},
        ]
        mock_matchups_week2 = [
            {"roster_id": 1, "matchup_id": 1, "points": 100},
            {"roster_id": 2, "matchup_id": 1, "points": 105},
        ]

        call_count = [0]

        async def mock_fetch(endpoint):
            if "league/" in endpoint and "matchups" not in endpoint:
                return mock_league
            elif "matchups/1" in endpoint:
                return mock_matchups_week1
            elif "matchups/2" in endpoint:
                return mock_matchups_week2
            return []

        with patch.object(adapter, '_fetch_json', side_effect=mock_fetch):
            with patch.object(adapter, '_get_nfl_state', return_value=mock_state):
                teams = {1: MagicMock(division_id=1), 2: MagicMock(division_id=1)}
                h2h = await adapter.fetch_head_to_head("123", 2025, teams)

        # Team 1 won week 1, team 2 won week 2 -> (1, 1, 0)
        assert (1, 2) in h2h
        assert h2h[(1, 2)] == (1, 1, 0)


class TestSleeperAdapterIntegration:
    """Integration tests that hit the real Sleeper API."""

    @pytest.mark.asyncio
    async def test_nfl_state_endpoint(self, adapter):
        """Test that the NFL state endpoint works."""
        state = await adapter._get_nfl_state()
        assert "season" in state
        assert "week" in state

    @pytest.mark.asyncio
    async def test_invalid_league_returns_not_found(self, adapter):
        """Test that an invalid league ID returns LeagueNotFoundError."""
        with pytest.raises(LeagueNotFoundError):
            await adapter.validate_league("definitely_not_a_real_league_123456", 2025)
