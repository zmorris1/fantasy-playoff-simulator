"""
Tests for the ESPN platform adapter.
"""

from unittest.mock import patch

import pytest

from app.platforms.espn import ESPNAdapter
from app.platforms import UnsupportedLeagueError
from app.core.sports import Sport


def league_data(scoring_type="H2H_POINTS", n_categories=9):
    return {
        "settings": {
            "name": "Test League",
            "scoringSettings": {
                "scoringType": scoring_type,
                "scoringItems": [{"statId": i} for i in range(n_categories)],
            },
            "scheduleSettings": {"matchupPeriodCount": 2, "playoffTeamCount": 2, "divisions": []},
        },
        "status": {"currentMatchupPeriod": 2},
        "teams": [
            {"id": 1, "name": "A", "divisionId": 0, "record": {"overall": {"wins": 6, "losses": 3}}},
            {"id": 2, "name": "B", "divisionId": 0, "record": {"overall": {"wins": 3, "losses": 6}}},
        ],
        "schedule": [
            {"matchupPeriodId": 1, "winner": "HOME",
             "home": {"teamId": 1, "cumulativeScore": {"wins": 6, "losses": 3, "ties": 0}},
             "away": {"teamId": 2, "cumulativeScore": {"wins": 3, "losses": 6, "ties": 0}}},
            {"matchupPeriodId": 2, "winner": "UNDECIDED",
             "home": {"teamId": 2}, "away": {"teamId": 1}},
        ],
    }


@pytest.fixture
def adapter():
    return ESPNAdapter(sport=Sport.BASKETBALL)


@pytest.mark.asyncio
async def test_all_data_comes_from_one_request(adapter):
    with patch.object(adapter, "_fetch_league_data", return_value=league_data()) as fetch:
        teams, _ = await adapter.fetch_standings("1", 2026)
        await adapter.fetch_schedule("1", 2026, teams)
        await adapter.fetch_head_to_head("1", 2026, teams)
        await adapter.fetch_league_settings("1", 2026)
    assert fetch.call_count == 1


@pytest.mark.asyncio
async def test_points_league_counts_matchups(adapter):
    with patch.object(adapter, "_fetch_league_data", return_value=league_data("H2H_POINTS")):
        settings = await adapter.fetch_league_settings("1", 2026)
        h2h = await adapter.fetch_head_to_head("1", 2026, {})
    assert settings["categories_per_matchup"] == 1
    assert h2h == {(1, 2): (1, 0, 0)}


@pytest.mark.asyncio
async def test_each_category_league_counts_categories(adapter):
    with patch.object(adapter, "_fetch_league_data", return_value=league_data("H2H_CATEGORY", 9)):
        settings = await adapter.fetch_league_settings("1", 2026)
        h2h = await adapter.fetch_head_to_head("1", 2026, {})
    assert settings["categories_per_matchup"] == 9
    assert h2h == {(1, 2): (6, 3, 0)}


@pytest.mark.asyncio
async def test_most_categories_is_one_win_per_matchup(adapter):
    with patch.object(adapter, "_fetch_league_data", return_value=league_data("H2H_MOST_CATEGORIES", 9)):
        settings = await adapter.fetch_league_settings("1", 2026)
    assert settings["categories_per_matchup"] == 1


@pytest.mark.asyncio
async def test_roto_league_is_unsupported(adapter):
    with patch.object(adapter, "_fetch_league_data", return_value=league_data("ROTO")):
        with pytest.raises(UnsupportedLeagueError):
            await adapter.fetch_league_settings("1", 2026)
