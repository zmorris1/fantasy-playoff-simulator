"""
Tests for the Yahoo Fantasy platform adapter.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET

from app.platforms.yahoo import YahooAdapter
from app.platforms import LeagueNotFoundError, LeaguePrivateError, PlatformError
from app.core.sports import Sport
from app.db.models import YahooCredential


def create_mock_credential(expired: bool = False) -> MagicMock:
    """Create a mock YahooCredential for testing."""
    cred = MagicMock(spec=YahooCredential)
    cred.access_token = "mock_access_token"
    cred.refresh_token = "mock_refresh_token"
    if expired:
        cred.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        cred.is_expired = True
    else:
        cred.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        cred.is_expired = False
    return cred


@pytest.fixture
def adapter():
    """Create a Yahoo adapter instance with mock credential for testing."""
    cred = create_mock_credential()
    return YahooAdapter(sport=Sport.BASKETBALL, credential=cred)


@pytest.fixture
def football_adapter():
    """Create a Yahoo adapter for football."""
    cred = create_mock_credential()
    return YahooAdapter(sport=Sport.FOOTBALL, credential=cred)


class TestYahooAdapterBasics:
    """Basic tests for YahooAdapter properties."""

    def test_platform_name(self, adapter):
        """Test platform_name property."""
        assert adapter.platform_name == "yahoo"

    def test_game_key_basketball(self, adapter):
        """Test game key for basketball."""
        assert adapter._get_game_key() == "nba"

    def test_game_key_football(self, football_adapter):
        """Test game key for football."""
        assert football_adapter._get_game_key() == "nfl"

    def test_game_key_baseball(self):
        """Test game key for baseball."""
        cred = create_mock_credential()
        adapter = YahooAdapter(sport=Sport.BASEBALL, credential=cred)
        assert adapter._get_game_key() == "mlb"

    def test_build_league_key(self, adapter):
        """Test league key building."""
        key = adapter._build_league_key("12345", 2025)
        assert key == "nba.l.12345"

    def test_build_league_key_football(self, football_adapter):
        """Test league key for football."""
        key = football_adapter._build_league_key("67890", 2025)
        assert key == "nfl.l.67890"


class TestYahooAdapterXMLParsing:
    """Tests for XML parsing helper methods."""

    def test_find_text_with_namespace(self, adapter):
        """Test finding text with namespace."""
        xml_str = '''
        <root xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng">
            <name>Test League</name>
        </root>
        '''
        root = ET.fromstring(xml_str)
        result = adapter._find_text(root, "name", "default")
        assert result == "Test League"

    def test_find_text_without_namespace(self, adapter):
        """Test finding text without namespace."""
        xml_str = '''
        <root>
            <name>Test League</name>
        </root>
        '''
        root = ET.fromstring(xml_str)
        result = adapter._find_text(root, "name", "default")
        assert result == "Test League"

    def test_find_text_missing_returns_default(self, adapter):
        """Test finding missing element returns default."""
        xml_str = '<root></root>'
        root = ET.fromstring(xml_str)
        result = adapter._find_text(root, "missing", "default_value")
        assert result == "default_value"

    def test_find_int(self, adapter):
        """Test finding integer value."""
        xml_str = '<root><count>42</count></root>'
        root = ET.fromstring(xml_str)
        result = adapter._find_int(root, "count", 0)
        assert result == 42

    def test_find_int_invalid_returns_default(self, adapter):
        """Test finding invalid integer returns default."""
        xml_str = '<root><count>not_a_number</count></root>'
        root = ET.fromstring(xml_str)
        result = adapter._find_int(root, "count", 99)
        assert result == 99


class TestYahooAdapterTokenHandling:
    """Tests for OAuth token handling."""

    def test_no_credential_raises_error(self):
        """Test that missing credential raises PlatformError."""
        adapter = YahooAdapter(sport=Sport.BASKETBALL, credential=None)
        with pytest.raises(PlatformError, match="credential is required"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(adapter._ensure_valid_token())

    @pytest.mark.asyncio
    async def test_valid_token_returned_directly(self, adapter):
        """Test that valid token is returned without refresh."""
        token = await adapter._ensure_valid_token()
        assert token == "mock_access_token"

    @pytest.mark.asyncio
    async def test_expired_token_triggers_refresh(self):
        """Test that expired token triggers refresh."""
        cred = create_mock_credential(expired=True)
        adapter = YahooAdapter(sport=Sport.BASKETBALL, credential=cred)

        mock_refresh_result = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1)
        }

        with patch('app.platforms.yahoo.refresh_access_token', return_value=mock_refresh_result) as mock_refresh:
            token = await adapter._ensure_valid_token()
            mock_refresh.assert_called_once_with("mock_refresh_token")
            assert token == "new_access_token"
            assert cred.access_token == "new_access_token"


class TestYahooAdapterFetchStandings:
    """Tests for fetch_standings method."""

    @pytest.mark.asyncio
    async def test_fetch_standings_parses_teams(self, adapter):
        """Test fetch_standings correctly parses team data."""
        standings_xml = '''
        <fantasy_content xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng">
            <league>
                <name>Test League</name>
                <standings>
                    <teams>
                        <team>
                            <team_key>nba.l.12345.t.1</team_key>
                            <name>Team Alpha</name>
                            <division_id>1</division_id>
                            <team_standings>
                                <outcome_totals>
                                    <wins>10</wins>
                                    <losses>5</losses>
                                    <ties>0</ties>
                                </outcome_totals>
                                <divisional_outcome_totals>
                                    <wins>4</wins>
                                    <losses>2</losses>
                                    <ties>0</ties>
                                </divisional_outcome_totals>
                            </team_standings>
                        </team>
                        <team>
                            <team_key>nba.l.12345.t.2</team_key>
                            <name>Team Beta</name>
                            <division_id>2</division_id>
                            <team_standings>
                                <outcome_totals>
                                    <wins>8</wins>
                                    <losses>7</losses>
                                    <ties>0</ties>
                                </outcome_totals>
                            </team_standings>
                        </team>
                    </teams>
                </standings>
            </league>
        </fantasy_content>
        '''
        root = ET.fromstring(standings_xml)

        with patch.object(adapter, '_fetch_api', return_value=root):
            teams, divisions = await adapter.fetch_standings("12345", 2025)

        assert len(teams) == 2
        assert teams[1].name == "Team Alpha"
        assert teams[1].wins == 10
        assert teams[1].losses == 5
        assert teams[1].division_id == 1
        assert teams[1].division_wins == 4
        assert teams[1].division_losses == 2

        assert teams[2].name == "Team Beta"
        assert teams[2].wins == 8
        assert teams[2].losses == 7
        assert teams[2].division_id == 2

        assert 1 in divisions
        assert 2 in divisions


class TestYahooAdapterFetchSchedule:
    """Tests for fetch_schedule method."""

    @pytest.mark.asyncio
    async def test_fetch_schedule_parses_matchups(self, adapter):
        """Test fetch_schedule correctly parses matchup data."""
        scoreboard_xml = '''
        <fantasy_content xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng">
            <league>
                <current_week>5</current_week>
                <scoreboard>
                    <matchups>
                        <matchup>
                            <status>midevent</status>
                            <teams>
                                <team><team_key>nba.l.12345.t.1</team_key></team>
                                <team><team_key>nba.l.12345.t.2</team_key></team>
                            </teams>
                        </matchup>
                        <matchup>
                            <status>postevent</status>
                            <teams>
                                <team><team_key>nba.l.12345.t.3</team_key></team>
                                <team><team_key>nba.l.12345.t.4</team_key></team>
                            </teams>
                        </matchup>
                    </matchups>
                </scoreboard>
            </league>
        </fantasy_content>
        '''
        root = ET.fromstring(scoreboard_xml)

        mock_settings = {"total_weeks": 18}
        teams = {
            1: MagicMock(division_id=1),
            2: MagicMock(division_id=1),
            3: MagicMock(division_id=2),
            4: MagicMock(division_id=2),
        }

        with patch.object(adapter, '_fetch_api', return_value=root):
            with patch.object(adapter, '_fetch_league_settings_internal', return_value=mock_settings):
                remaining, current_week, total_weeks = await adapter.fetch_schedule("12345", 2025, teams)

        # Should only include the midevent matchup (5-18 weeks)
        # The test returns the same XML for all weeks, so we get one matchup per remaining week
        assert current_week == 5
        assert total_weeks == 18
        # Check that at least one remaining matchup exists (midevent status)
        assert any(m.home_team_id == 1 and m.away_team_id == 2 for m in remaining)


class TestYahooAdapterFetchLeagueSettings:
    """Tests for fetch_league_settings method."""

    @pytest.mark.asyncio
    async def test_fetch_league_settings(self, adapter):
        """Test fetch_league_settings correctly parses settings."""
        settings_xml = '''
        <fantasy_content xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng">
            <league>
                <name>My Fantasy League</name>
                <end_week>23</end_week>
                <settings>
                    <playoff_team_count>8</playoff_team_count>
                    <num_playoff_weeks>3</num_playoff_weeks>
                    <divisions>
                        <division>
                            <division_id>1</division_id>
                            <name>East</name>
                        </division>
                        <division>
                            <division_id>2</division_id>
                            <name>West</name>
                        </division>
                    </divisions>
                </settings>
            </league>
        </fantasy_content>
        '''
        root = ET.fromstring(settings_xml)

        with patch.object(adapter, '_fetch_api', return_value=root):
            settings = await adapter.fetch_league_settings("12345", 2025)

        assert settings["league_name"] == "My Fantasy League"
        assert settings["playoff_spots"] == 8
        assert settings["num_divisions"] == 2
        assert settings["total_weeks"] == 20  # 23 - 3 playoff weeks
        assert len(settings["divisions"]) == 2
        assert settings["divisions"][0]["name"] == "East"
        assert settings["divisions"][1]["name"] == "West"


class TestYahooAdapterFetchHeadToHead:
    """Tests for fetch_head_to_head method."""

    @pytest.mark.asyncio
    async def test_fetch_head_to_head_completed_matchups(self, adapter):
        """Test fetch_head_to_head correctly tracks wins/losses."""
        # Week 1: Team 1 beats Team 2
        # Week 2: Team 2 beats Team 1
        matchup_xml_week1 = '''
        <fantasy_content xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng">
            <league>
                <scoreboard>
                    <matchups>
                        <matchup>
                            <status>postevent</status>
                            <teams>
                                <team>
                                    <team_key>nba.l.12345.t.1</team_key>
                                    <win_probability>1.0</win_probability>
                                </team>
                                <team>
                                    <team_key>nba.l.12345.t.2</team_key>
                                    <win_probability>0.0</win_probability>
                                </team>
                            </teams>
                        </matchup>
                    </matchups>
                </scoreboard>
            </league>
        </fantasy_content>
        '''

        matchup_xml_week2 = '''
        <fantasy_content xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng">
            <league>
                <scoreboard>
                    <matchups>
                        <matchup>
                            <status>postevent</status>
                            <teams>
                                <team>
                                    <team_key>nba.l.12345.t.1</team_key>
                                    <win_probability>0.0</win_probability>
                                </team>
                                <team>
                                    <team_key>nba.l.12345.t.2</team_key>
                                    <win_probability>1.0</win_probability>
                                </team>
                            </teams>
                        </matchup>
                    </matchups>
                </scoreboard>
            </league>
        </fantasy_content>
        '''

        mock_settings = {"total_weeks": 2}
        teams = {1: MagicMock(division_id=1), 2: MagicMock(division_id=1)}

        call_count = [0]
        def mock_fetch(endpoint):
            call_count[0] += 1
            if "week=1" in endpoint:
                return ET.fromstring(matchup_xml_week1)
            elif "week=2" in endpoint:
                return ET.fromstring(matchup_xml_week2)
            return ET.fromstring('<fantasy_content/>')

        with patch.object(adapter, '_fetch_api', side_effect=mock_fetch):
            with patch.object(adapter, '_fetch_league_settings_internal', return_value=mock_settings):
                h2h = await adapter.fetch_head_to_head("12345", 2025, teams)

        # Team 1 and Team 2 each have 1 win
        assert (1, 2) in h2h
        assert h2h[(1, 2)] == (1, 1, 0)


class TestYahooAdapterErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_404_raises_league_not_found(self, adapter):
        """Test that 404 response raises LeagueNotFoundError."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            with pytest.raises(LeagueNotFoundError):
                await adapter.validate_league("nonexistent", 2025)

    @pytest.mark.asyncio
    async def test_401_raises_league_private(self, adapter):
        """Test that 401 response raises LeaguePrivateError."""
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            with pytest.raises(LeaguePrivateError, match="authentication failed"):
                await adapter.validate_league("12345", 2025)

    @pytest.mark.asyncio
    async def test_403_raises_league_private(self, adapter):
        """Test that 403 response raises LeaguePrivateError."""
        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            with pytest.raises(LeaguePrivateError, match="don't have access"):
                await adapter.validate_league("12345", 2025)


class TestYahooAdapterValidateLeague:
    """Tests for validate_league method."""

    @pytest.mark.asyncio
    async def test_validate_league_success(self, adapter):
        """Test validate_league returns True for valid league."""
        valid_xml = '''
        <fantasy_content xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng">
            <league>
                <name>Test League</name>
            </league>
        </fantasy_content>
        '''
        root = ET.fromstring(valid_xml)

        with patch.object(adapter, '_fetch_api', return_value=root):
            result = await adapter.validate_league("12345", 2025)

        assert result is True
