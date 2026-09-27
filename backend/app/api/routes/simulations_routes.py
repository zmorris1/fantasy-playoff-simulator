"""
Simulation API routes.
"""

import asyncio
import json
import logging
import os
import time
from typing import Callable, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import (
    SimulationRunRequest,
    SimulationTaskResponse,
    SimulationResultsResponse,
    TeamResult
)
from ..auth import get_current_user
from .leagues_routes import validate_with_season_fallback
from ...db import (
    get_db,
    async_session_maker,
    SimulationCacheRepository,
    SimulationTaskRepository,
    YahooCredentialRepository,
    CBSCredentialRepository,
    User
)
from ...platforms import (
    get_adapter,
    LeagueNotFoundError,
    LeaguePrivateError,
    PlatformError,
    UnsupportedLeagueError
)
from ...core.yahoo_oauth import YahooTokenExpiredError
from ...core.cbs_oauth import CBSTokenExpiredError
from ...simulator import (
    simulate_season,
    calculate_magic_numbers,
    generate_clinch_elimination_scenarios,
    brute_force_clinch_elimination,
    scenario_week,
    BRUTE_FORCE_MAX_GAMES
)
from ...core.sports import Sport, get_season_candidates


logger = logging.getLogger("app")

router = APIRouter(prefix="/simulations", tags=["simulations"])

QUICK_MODE_SIMULATIONS = 1000

# Simulations are CPU-bound Python. They run in worker threads so the event
# loop keeps answering other requests, and only a few run at once so a burst
# of requests can't starve the server.
MAX_CONCURRENT_SIMULATIONS = int(os.getenv("MAX_CONCURRENT_SIMULATIONS", "2"))
_simulation_slots = asyncio.Semaphore(MAX_CONCURRENT_SIMULATIONS)

# Progress of tasks running in this process, updated continuously by the
# worker thread (the database copy is only written at milestones)
_live_progress: Dict[str, int] = {}

# Old tasks and expired cache entries are pruned at most this often
CLEANUP_INTERVAL_SECONDS = 3600
_last_cleanup = 0.0


def _compute(
    teams, remaining, h2h, playoff_spots: int, categories: int, current_week: int,
    n_simulations: int, report: Callable[[float], None]
):
    """
    All the CPU-heavy work for one simulation. Runs in a worker thread.

    Returns (magic numbers, scenario report, scenario week, simulation results).
    """
    report(40)
    magic_numbers = calculate_magic_numbers(teams, remaining, h2h, playoff_spots, categories)

    week = scenario_week(remaining, current_week)
    if categories == 1 and len(remaining) <= BRUTE_FORCE_MAX_GAMES:
        scenarios = brute_force_clinch_elimination(
            teams, remaining, h2h, week, playoff_spots,
            progress_callback=lambda pct: report(40 + pct * 0.10)
        )
        # Exhaustive enumeration knows clinched/eliminated exactly
        for team_id, team_status in scenarios.statuses.items():
            magic = magic_numbers[team_id]
            for goal in ("division", "playoffs", "first_seed"):
                clinched = team_status[f"clinched_{goal}"]
                eliminated = team_status[f"eliminated_{goal}"]
                setattr(magic, f"clinched_{goal}", clinched)
                setattr(magic, f"eliminated_{goal}", eliminated)
                if clinched or eliminated:
                    setattr(magic, f"magic_{goal}", None)
    else:
        scenarios = generate_clinch_elimination_scenarios(
            teams, remaining, h2h, week, playoff_spots, categories
        )

    report(50)
    results = simulate_season(
        teams, remaining, h2h, n_simulations, playoff_spots,
        progress_callback=lambda pct: report(50 + pct * 0.45),
        categories_per_matchup=categories
    )
    return magic_numbers, scenarios, week, results


def _display_pct(count: int, n_simulations: int, clinched: bool, eliminated: bool) -> float:
    """
    Simulated probability, kept consistent with the math: 100% only when
    clinched, 0% only when eliminated. Otherwise it stays strictly between,
    so the UI can show ">99.9%" / "<0.1%" instead of a misleading 100% or 0%.
    """
    if clinched:
        return 1.0
    if eliminated:
        return 0.0
    pct = count / n_simulations
    return min(max(pct, 0.0001), 0.9999)


def _notes(settings: dict, remaining: list, categories: int) -> List[str]:
    notes = []
    if not remaining:
        notes.append("The regular season is over, so these are the final standings.")
    if categories > 1:
        notes.append(
            f"Each-category league: each matchup is worth {categories} category wins, so records, "
            "magic numbers and the simulation all count categories. Every category is treated as a coin flip."
        )
    if settings.get("median_games"):
        notes.append(
            "This league also plays a weekly game against the league median. Those games aren't "
            "simulated yet, so remaining weeks count once instead of twice and the odds are more "
            "certain than they should be."
        )
    return notes


async def run_simulation_task(
    task_id: str,
    request: SimulationRunRequest,
    season: int,
    user_id: Optional[int] = None
):
    """
    Background task to run a simulation.

    Network I/O runs on the event loop; the CPU-heavy parts run in a worker
    thread so the API stays responsive.

    Args:
        task_id: The simulation task ID
        request: The simulation request parameters
        season: The season resolved when the task was started
        user_id: The user ID (required for Yahoo/CBS platforms)
    """
    async with async_session_maker() as db:
        task_repo = SimulationTaskRepository(db)
        cache_repo = SimulationCacheRepository(db)

        task = await task_repo.get_by_id(task_id)
        if task is None:
            return

        async def milestone(progress: int) -> None:
            _live_progress[task_id] = progress
            await task_repo.update_progress(task, progress)
            await db.commit()

        def report(progress: float) -> None:
            # Called from the worker thread; a dict store is atomic
            _live_progress[task_id] = int(progress)

        try:
            # Convert sport string to Sport enum
            sport_enum = Sport(request.sport.lower())

            # Get Yahoo credential if needed
            yahoo_credential = None
            if request.platform.lower() == "yahoo" and user_id:
                cred_repo = YahooCredentialRepository(db)
                yahoo_credential = await cred_repo.get_by_user_id(user_id)
                if yahoo_credential is None:
                    raise PlatformError("Yahoo credential not found. Please reconnect your Yahoo account.")

            # Get CBS credential if needed
            cbs_credential = None
            if request.platform.lower() == "cbs" and user_id:
                cbs_cred_repo = CBSCredentialRepository(db)
                cbs_credential = await cbs_cred_repo.get_by_user_id(user_id)
                if cbs_credential is None:
                    raise PlatformError("CBS credential not found. Please reconnect your CBS account.")

            # Get platform adapter
            adapter = get_adapter(request.platform, sport_enum, yahoo_credential=yahoo_credential, cbs_credential=cbs_credential)

            await milestone(5)

            # Fetch league data
            teams, division_names = await adapter.fetch_standings(request.league_id, season)
            if not teams:
                raise PlatformError("No teams were found in this league.")
            await milestone(15)

            remaining, current_week, total_weeks = await adapter.fetch_schedule(
                request.league_id, season, teams
            )
            await milestone(25)

            h2h = await adapter.fetch_head_to_head(request.league_id, season, teams)
            settings = await adapter.fetch_league_settings(request.league_id, season)

            # If Yahoo or CBS token was refreshed, persist the new tokens
            if getattr(adapter, "_token_refreshed", False):
                await db.flush()

            await milestone(35)

            playoff_spots = settings.get("playoff_spots", 6)
            categories = settings.get("categories_per_matchup", 1)

            # Determine simulation count
            n_simulations = request.n_simulations
            if request.quick_mode:
                n_simulations = QUICK_MODE_SIMULATIONS

            async with _simulation_slots:
                magic_numbers, scenarios, week, results = await asyncio.to_thread(
                    _compute, teams, remaining, h2h, playoff_spots, categories,
                    current_week, n_simulations, report
                )
            await milestone(95)

            # Build response data
            team_results = []
            for team in sorted(teams.values(), key=lambda t: results[t.id].playoff_appearances, reverse=True):
                team_result = results[team.id]
                team_magic = magic_numbers[team.id]

                # Cap at 99.9% if not mathematically clinched (last place has no clinch flag)
                last_pct = team_result.last_place / n_simulations
                if team_magic.magic_last is not None and last_pct >= 0.9995:
                    last_pct = 0.999

                team_results.append(TeamResult(
                    id=team.id,
                    name=team.name,
                    division_id=team.division_id,
                    division_name=division_names.get(team.division_id, f"Division {team.division_id}"),
                    wins=team.wins,
                    losses=team.losses,
                    ties=team.ties,
                    record=team.record_str,
                    division_record=team.division_record_str,
                    win_pct=team.win_pct,
                    division_pct=_display_pct(
                        team_result.division_wins, n_simulations,
                        team_magic.clinched_division, team_magic.eliminated_division
                    ),
                    playoff_pct=_display_pct(
                        team_result.playoff_appearances, n_simulations,
                        team_magic.clinched_playoffs, team_magic.eliminated_playoffs
                    ),
                    first_seed_pct=_display_pct(
                        team_result.first_seed, n_simulations,
                        team_magic.clinched_first_seed, team_magic.eliminated_first_seed
                    ),
                    last_place_pct=last_pct,
                    magic_division=team_magic.magic_division,
                    magic_playoffs=team_magic.magic_playoffs,
                    magic_first_seed=team_magic.magic_first_seed,
                    magic_last=team_magic.magic_last,
                    clinched_division=team_magic.clinched_division,
                    clinched_playoffs=team_magic.clinched_playoffs,
                    clinched_first_seed=team_magic.clinched_first_seed,
                    eliminated_division=team_magic.eliminated_division,
                    eliminated_playoffs=team_magic.eliminated_playoffs,
                    eliminated_first_seed=team_magic.eliminated_first_seed
                ))

            response_data = SimulationResultsResponse(
                league_name=settings.get("league_name", f"League {request.league_id}"),
                platform=request.platform,
                league_id=request.league_id,
                season=season,
                sport=request.sport,
                current_week=current_week,
                total_weeks=total_weeks,
                n_simulations=n_simulations,
                teams=team_results,
                clinch_scenarios=scenarios.clinch,
                elimination_scenarios=scenarios.elimination,
                scenario_week=week,
                categories_per_matchup=categories,
                notes=_notes(settings, remaining, categories)
            )
            results_json = response_data.model_dump(mode="json")

            # Cache the results
            await cache_repo.set(
                platform=request.platform,
                league_id=request.league_id,
                season=season,
                week=current_week,
                results=results_json,
                sport=request.sport
            )

            # Mark task complete
            await task_repo.complete(task, results_json)
            await db.commit()

        except Exception as e:
            if isinstance(e, (LeagueNotFoundError, LeaguePrivateError, PlatformError,
                              YahooTokenExpiredError, CBSTokenExpiredError)):
                message = str(e)
            else:
                logger.exception("Simulation %s failed", task_id)
                message = f"Unexpected error while simulating: {e}"
            # The session may be unusable after a failed statement; the
            # rollback also expires `task`, so load it again
            await db.rollback()
            task = await task_repo.get_by_id(task_id)
            if task is not None:
                await task_repo.fail(task, message)
                await db.commit()
        finally:
            _live_progress.pop(task_id, None)


async def _maybe_cleanup(db: AsyncSession) -> None:
    """Prune old tasks and expired cache entries, at most once an hour."""
    global _last_cleanup
    now = time.monotonic()
    if now - _last_cleanup < CLEANUP_INTERVAL_SECONDS:
        return
    _last_cleanup = now
    try:
        await SimulationTaskRepository(db).cleanup_old_tasks(hours=24)
        await SimulationCacheRepository(db).cleanup_expired()
        await db.commit()
    except Exception:
        logger.exception("Cleanup of old simulation tasks failed")
        await db.rollback()


@router.post("/run", response_model=SimulationTaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_simulation(
    request: SimulationRunRequest,
    background_tasks: BackgroundTasks,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> SimulationTaskResponse:
    """
    Start a simulation for a league.

    Returns a task ID that can be used to poll for status and results.
    The simulation runs in the background. Results from the last 15 minutes
    are reused unless `refresh` is set.
    """
    # Convert sport string to Sport enum
    try:
        sport_enum = Sport(request.sport.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sport: {request.sport}. Supported: basketball, football, baseball, hockey"
        )

    # An explicitly chosen season is honored exactly; otherwise fall back
    # to the prior season when the current one doesn't exist yet (off-season)
    if request.season is not None:
        season_candidates = [request.season]
    else:
        season_candidates = get_season_candidates(sport_enum)

    # Handle Yahoo platform - requires authentication and Yahoo credential
    yahoo_credential = None
    if request.platform.lower() == "yahoo":
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to access Yahoo Fantasy leagues"
            )

        cred_repo = YahooCredentialRepository(db)
        yahoo_credential = await cred_repo.get_by_user_id(current_user.id)
        if yahoo_credential is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please connect your Yahoo account first"
            )

    # Handle CBS platform - requires authentication and CBS credential
    cbs_credential = None
    if request.platform.lower() == "cbs":
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to access CBS Sports Fantasy leagues"
            )

        cbs_cred_repo = CBSCredentialRepository(db)
        cbs_credential = await cbs_cred_repo.get_by_user_id(current_user.id)
        if cbs_credential is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please connect your CBS account first"
            )

    # Validate the league (and that it's a format we can simulate)
    try:
        adapter = get_adapter(request.platform, sport_enum, yahoo_credential=yahoo_credential, cbs_credential=cbs_credential)
        _, season = await validate_with_season_fallback(adapter, request.league_id, season_candidates)

        # If token was refreshed, persist the new tokens
        if getattr(adapter, "_token_refreshed", False):
            await db.commit()
    except LeagueNotFoundError:
        seasons_tried = ", ".join(str(s) for s in season_candidates)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"League {request.league_id} not found for season{'s' if len(season_candidates) > 1 else ''} {seasons_tried}"
        )
    except (LeaguePrivateError, UnsupportedLeagueError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except YahooTokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Yahoo authentication expired. Please reconnect your Yahoo account."
        )
    except CBSTokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CBS authentication expired. Please reconnect your CBS account."
        )
    except PlatformError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error communicating with {request.platform}: {str(e)}"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    await _maybe_cleanup(db)

    task_repo = SimulationTaskRepository(db)
    n_simulations = QUICK_MODE_SIMULATIONS if request.quick_mode else request.n_simulations

    # Reuse recent results for the same league
    if not request.refresh:
        cached = await SimulationCacheRepository(db).get_latest(
            request.platform, request.league_id, season, request.sport
        )
        if cached is not None:
            results, cached_at = cached
            if results.get("n_simulations", 0) >= n_simulations:
                results.update(cached=True, cached_at=cached_at.isoformat())
                task = await task_repo.create(request.platform, request.league_id, season, request.sport)
                await task_repo.complete(task, results)
                await db.commit()
                return SimulationTaskResponse(task_id=task.id, status="completed", progress=100)

    # Create task
    task = await task_repo.create(request.platform, request.league_id, season, request.sport)
    await db.commit()

    # Start background task (pass user_id for Yahoo credential lookup)
    user_id = current_user.id if current_user else None
    background_tasks.add_task(run_simulation_task, task.id, request, season, user_id)

    return SimulationTaskResponse(
        task_id=task.id,
        status="pending",
        progress=0
    )


def _task_progress(task) -> int:
    """Stored progress, or the live figure while the task runs in this process."""
    if task.status in ("pending", "running"):
        return max(task.progress, _live_progress.get(task.id, 0))
    return task.progress


@router.get("/{task_id}/status", response_model=SimulationTaskResponse)
async def get_simulation_status(
    task_id: str,
    db: AsyncSession = Depends(get_db)
) -> SimulationTaskResponse:
    """
    Get the status of a running simulation.
    """
    task_repo = SimulationTaskRepository(db)
    task = await task_repo.get_by_id(task_id)

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    return SimulationTaskResponse(
        task_id=task.id,
        status=task.status,
        progress=_task_progress(task),
        error=task.error_message
    )


@router.get("/{task_id}/results", response_model=SimulationResultsResponse)
async def get_simulation_results(
    task_id: str,
    db: AsyncSession = Depends(get_db)
) -> SimulationResultsResponse:
    """
    Get the results of a completed simulation.
    """
    task_repo = SimulationTaskRepository(db)
    task = await task_repo.get_by_id(task_id)

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    if task.status == "pending" or task.status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Simulation is still running"
        )

    if task.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=task.error_message or "Simulation failed"
        )

    if task.results_json is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No results available"
        )

    results = json.loads(task.results_json)
    return SimulationResultsResponse(**results)


@router.get("/{task_id}/stream")
async def stream_simulation_progress(
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Stream simulation progress via Server-Sent Events (SSE).

    This allows real-time progress updates without polling.
    """
    task_repo = SimulationTaskRepository(db)
    task = await task_repo.get_by_id(task_id)

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    async def event_generator():
        while True:
            async with async_session_maker() as session:
                repo = SimulationTaskRepository(session)
                current_task = await repo.get_by_id(task_id)

                if current_task is None:
                    yield f"data: {json.dumps({'error': 'Task not found'})}\n\n"
                    break

                data = {
                    "task_id": current_task.id,
                    "status": current_task.status,
                    "progress": _task_progress(current_task)
                }

                if current_task.error_message:
                    data["error"] = current_task.error_message

                yield f"data: {json.dumps(data)}\n\n"

                if current_task.status in ("completed", "failed"):
                    break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
