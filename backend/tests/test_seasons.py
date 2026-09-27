"""
Tests for season resolution: get_current_season, get_season_candidates,
and the validate-with-fallback behavior used by /leagues/validate.
"""

import datetime as real_datetime

import pytest

from app.core import sports
from app.core.sports import Sport, get_current_season, get_season_candidates
from app.api.routes.leagues_routes import validate_with_season_fallback
from app.platforms import LeagueNotFoundError, LeaguePrivateError


class FrozenDatetime(real_datetime.datetime):
    """datetime.datetime with a controllable now()."""

    frozen_now = None

    @classmethod
    def now(cls, tz=None):
        return cls.frozen_now


@pytest.fixture
def freeze_time(monkeypatch):
    """Freeze app.core.sports.datetime.now() to a given date."""

    def _freeze(year, month, day=15):
        FrozenDatetime.frozen_now = real_datetime.datetime(year, month, day)
        monkeypatch.setattr(sports, "datetime", FrozenDatetime)

    return _freeze


class TestGetCurrentSeason:
    """Season resolution per sport at different points in the year."""

    def test_football_in_season(self, freeze_time):
        freeze_time(2025, 10)
        assert get_current_season(Sport.FOOTBALL) == 2025

    def test_football_january_is_previous_season(self, freeze_time):
        freeze_time(2026, 1)
        assert get_current_season(Sport.FOOTBALL) == 2025

    def test_football_off_season_resolves_to_uncreated_season(self, freeze_time):
        # March-August: resolves to a season that may not exist yet on the
        # platform — this is why get_season_candidates exists
        freeze_time(2026, 8)
        assert get_current_season(Sport.FOOTBALL) == 2026

    def test_basketball_october_is_next_year(self, freeze_time):
        freeze_time(2025, 11)
        assert get_current_season(Sport.BASKETBALL) == 2026

    def test_basketball_spring_is_current_year(self, freeze_time):
        freeze_time(2026, 3)
        assert get_current_season(Sport.BASKETBALL) == 2026

    def test_baseball_calendar_year(self, freeze_time):
        freeze_time(2026, 7)
        assert get_current_season(Sport.BASEBALL) == 2026

    def test_hockey_october_is_next_year(self, freeze_time):
        freeze_time(2025, 10)
        assert get_current_season(Sport.HOCKEY) == 2026


class TestGetSeasonCandidates:
    """Candidate ordering for unpinned season resolution."""

    def test_current_first_then_prior(self, freeze_time):
        freeze_time(2026, 8)
        assert get_season_candidates(Sport.FOOTBALL) == [2026, 2025]

    def test_basketball_candidates(self, freeze_time):
        freeze_time(2026, 8)
        assert get_season_candidates(Sport.BASKETBALL) == [2026, 2025]


class FakeAdapter:
    """Adapter stub whose league only exists for the given seasons."""

    def __init__(self, existing_seasons, error=None):
        self.existing_seasons = set(existing_seasons)
        self.error = error
        self.validated_seasons = []

    async def validate_league(self, league_id, season):
        self.validated_seasons.append(season)
        if self.error is not None:
            raise self.error
        if season not in self.existing_seasons:
            raise LeagueNotFoundError(f"League {league_id} not found for season {season}")
        return True

    async def fetch_league_settings(self, league_id, season):
        return {"league_name": "Test League", "season": season}


class TestValidateWithSeasonFallback:
    """Fallback behavior for /leagues/validate."""

    @pytest.mark.asyncio
    async def test_current_season_exists_no_fallback(self):
        adapter = FakeAdapter(existing_seasons=[2026, 2025])
        settings, season = await validate_with_season_fallback(adapter, "123", [2026, 2025])
        assert season == 2026
        assert adapter.validated_seasons == [2026]
        assert settings["league_name"] == "Test League"

    @pytest.mark.asyncio
    async def test_falls_back_to_prior_season(self):
        # Off-season case: current season not created yet on the platform
        adapter = FakeAdapter(existing_seasons=[2025])
        settings, season = await validate_with_season_fallback(adapter, "123", [2026, 2025])
        assert season == 2025
        assert adapter.validated_seasons == [2026, 2025]

    @pytest.mark.asyncio
    async def test_no_candidate_exists_raises_not_found(self):
        adapter = FakeAdapter(existing_seasons=[])
        with pytest.raises(LeagueNotFoundError):
            await validate_with_season_fallback(adapter, "123", [2026, 2025])
        assert adapter.validated_seasons == [2026, 2025]

    @pytest.mark.asyncio
    async def test_explicit_season_is_honored_exactly(self):
        # A pinned season gets a single candidate: no silent substitution
        adapter = FakeAdapter(existing_seasons=[2025])
        with pytest.raises(LeagueNotFoundError):
            await validate_with_season_fallback(adapter, "123", [2026])
        assert adapter.validated_seasons == [2026]

    @pytest.mark.asyncio
    async def test_private_league_error_propagates_immediately(self):
        # A private league must not be masked by a fallback attempt
        adapter = FakeAdapter(existing_seasons=[2026], error=LeaguePrivateError("private"))
        with pytest.raises(LeaguePrivateError):
            await validate_with_season_fallback(adapter, "123", [2026, 2025])
        assert adapter.validated_seasons == [2026]
