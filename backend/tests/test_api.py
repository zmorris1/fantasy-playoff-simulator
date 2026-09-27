"""
API tests: simulation runs end to end (with a fake platform adapter), result
caching, auth edge cases, and the OAuth connection flow.
"""

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio

from app.main import app
from app.db import create_tables
from app.api.routes import simulations_routes
from app.api.oauth_state import create_oauth_state
from app.core import yahoo_oauth
from app.platforms import PlatformAdapter, UnsupportedLeagueError
from app.simulator import Team, Matchup


class FakeAdapter(PlatformAdapter):
    """Four-team league with one week left; team 4 is already out."""

    platform_name = "fake"

    def __init__(self, unsupported=False):
        self.unsupported = unsupported

    async def validate_league(self, league_id, season):
        return True

    async def fetch_standings(self, league_id, season):
        teams = {
            1: Team(1, "Aces", 0, wins=8, losses=1),
            2: Team(2, "Bears", 0, wins=6, losses=3),
            3: Team(3, "Cobras", 0, wins=5, losses=4),
            4: Team(4, "Dingos", 0, wins=0, losses=9),
        }
        return teams, {0: "League"}

    async def fetch_schedule(self, league_id, season, teams):
        return [Matchup(1, 4, 10, True), Matchup(2, 3, 10, True)], 10, 10

    async def fetch_head_to_head(self, league_id, season, teams):
        return {}

    async def fetch_league_settings(self, league_id, season):
        if self.unsupported:
            raise UnsupportedLeagueError("This league uses Roto scoring.")
        return {"league_name": "Fake League", "playoff_spots": 2, "num_divisions": 1}


@pytest.fixture
def fake_platform(monkeypatch):
    state = {"unsupported": False}

    def fake_get_adapter(platform, sport=None, **kwargs):
        return FakeAdapter(unsupported=state["unsupported"])

    monkeypatch.setattr(simulations_routes, "get_adapter", fake_get_adapter)
    return state


@pytest_asyncio.fixture
async def client():
    await create_tables()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def register(client) -> dict:
    email = f"user-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post("/api/auth/register", json={"email": email, "password": "correct-horse"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def league_id() -> str:
    return f"L{uuid.uuid4().hex[:8]}"


class TestSimulationRuns:

    @pytest.mark.asyncio
    async def test_run_to_results(self, client, fake_platform):
        r = await client.post("/api/simulations/run", json={
            "platform": "espn", "league_id": league_id(), "sport": "football", "season": 2026,
        })
        assert r.status_code == 202, r.text
        task_id = r.json()["task_id"]

        status = (await client.get(f"/api/simulations/{task_id}/status")).json()
        assert status["status"] == "completed", status
        assert status["progress"] == 100

        results = (await client.get(f"/api/simulations/{task_id}/results")).json()
        teams = {t["name"]: t for t in results["teams"]}
        assert results["league_name"] == "Fake League"
        assert results["cached"] is False
        # Exhaustive enumeration (2 games left) fixes these exactly
        assert teams["Aces"]["clinched_playoffs"] and teams["Aces"]["playoff_pct"] == 1.0
        assert teams["Dingos"]["eliminated_playoffs"] and teams["Dingos"]["playoff_pct"] == 0.0
        assert "Bears clinches playoff spot with a WIN vs Cobras" in results["clinch_scenarios"]
        # Undecided teams never show a flat 0% or 100%
        assert 0 < teams["Bears"]["playoff_pct"] < 1
        assert results["scenario_week"] == 10

    @pytest.mark.asyncio
    async def test_hockey_is_accepted(self, client, fake_platform):
        r = await client.post("/api/simulations/run", json={
            "platform": "espn", "league_id": league_id(), "sport": "hockey", "season": 2026,
        })
        assert r.status_code == 202, r.text

    @pytest.mark.asyncio
    async def test_recent_results_are_reused_unless_refreshed(self, client, fake_platform):
        body = {"platform": "espn", "league_id": league_id(), "sport": "football", "season": 2026}
        first = (await client.post("/api/simulations/run", json=body)).json()
        second = (await client.post("/api/simulations/run", json=body)).json()
        assert second["status"] == "completed"
        assert second["task_id"] != first["task_id"]

        cached = (await client.get(f"/api/simulations/{second['task_id']}/results")).json()
        assert cached["cached"] is True
        assert cached["cached_at"] is not None

        fresh = (await client.post("/api/simulations/run", json={**body, "refresh": True})).json()
        assert fresh["status"] == "pending"

    @pytest.mark.asyncio
    async def test_unsupported_league_is_a_clear_400(self, client, fake_platform):
        fake_platform["unsupported"] = True
        r = await client.post("/api/simulations/run", json={
            "platform": "espn", "league_id": league_id(), "sport": "basketball", "season": 2026,
        })
        assert r.status_code == 400
        assert "Roto" in r.json()["detail"]


class TestAuth:

    @pytest.mark.asyncio
    async def test_overlong_password_is_rejected_not_a_500(self, client):
        email = f"user-{uuid.uuid4().hex[:10]}@example.com"
        r = await client.post("/api/auth/register", json={"email": email, "password": "é" * 40})
        assert r.status_code == 422  # 80 bytes

        r = await client.post("/api/auth/login", json={"email": email, "password": "x" * 90})
        assert r.status_code == 401


class TestYahooOAuth:

    @pytest.fixture
    def yahoo_configured(self, monkeypatch):
        monkeypatch.setattr(yahoo_oauth, "YAHOO_CLIENT_ID", "client-id")
        monkeypatch.setattr(yahoo_oauth, "YAHOO_CLIENT_SECRET", "client-secret")

        async def fake_exchange(code):
            if code != "good-code":
                raise yahoo_oauth.YahooOAuthError("bad code")
            return {
                "access_token": "access", "refresh_token": "refresh",
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
                "yahoo_guid": "GUID123",
            }

        monkeypatch.setattr(yahoo_oauth, "exchange_code_for_tokens", fake_exchange)

    @pytest.mark.asyncio
    async def test_frontend_callback_connects_account(self, client, yahoo_configured):
        auth = await register(client)
        r = await client.get("/api/oauth/yahoo/authorize", headers=auth)
        assert r.status_code == 200
        state = r.json()["state"]
        assert parse_qs(urlparse(r.json()["url"]).query)["state"] == [state]

        r = await client.post("/api/oauth/yahoo/callback", headers=auth,
                              json={"code": "good-code", "state": state})
        assert r.status_code == 200, r.text
        assert r.json() == {"connected": True, "account_id": "GUID123"}

        status = (await client.get("/api/oauth/yahoo/status", headers=auth)).json()
        assert status["connected"] is True

    @pytest.mark.asyncio
    async def test_state_from_another_account_is_rejected(self, client, yahoo_configured):
        victim = await register(client)
        attacker = await register(client)
        attacker_state = (await client.get("/api/oauth/yahoo/authorize", headers=attacker)).json()["state"]

        r = await client.post("/api/oauth/yahoo/callback", headers=victim,
                              json={"code": "good-code", "state": attacker_state})
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_browser_redirect_callback_needs_no_auth_header(self, client, yahoo_configured):
        auth = await register(client)
        state = (await client.get("/api/oauth/yahoo/authorize", headers=auth)).json()["state"]

        r = await client.get("/api/oauth/yahoo/callback", params={"code": "good-code", "state": state})
        assert r.status_code in (302, 307)
        assert "yahoo_connected=true" in r.headers["location"]
        assert (await client.get("/api/oauth/yahoo/status", headers=auth)).json()["connected"]

        r = await client.get("/api/oauth/yahoo/callback", params={"code": "good-code", "state": "forged"})
        assert "yahoo_error=" in r.headers["location"]

    @pytest.mark.asyncio
    async def test_state_token_cannot_be_used_to_log_in(self, client):
        auth = await register(client)
        me = (await client.get("/api/auth/me", headers=auth)).json()
        state = create_oauth_state(me["id"], "yahoo")

        r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {state}"})
        assert r.status_code == 401
