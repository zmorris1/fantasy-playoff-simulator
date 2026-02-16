"""
Simulation API routes.
"""

import asyncio
import json
from typing import Optional
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
from ...db import (
    get_db,
    async_session_maker,
    SimulationCacheRepository,
    SimulationTaskRepository,
    YahooCredentialRepository,
    CBSCredentialRepository,
    User
)
from ...platforms import get_adapter, LeagueNotFoundError, LeaguePrivateError, PlatformError
from ...core.yahoo_oauth import YahooTokenExpiredError
from ...core.cbs_oauth import CBSTokenExpiredError
from ...simulator import (
    simulate_season,
    calculate_magic_numbers,
    generate_clinch_elimination_scenarios,
    brute_force_clinch_elimination
)
from ...core.sports import Sport, get_current_season


router = APIRouter(prefix="/simulations", tags=["simulations"])


async def run_simulation_task(task_id: str, request: SimulationRunRequest, user_id: int | None = None):
    """
    Background task to run a simulation.

    This runs in a separate async context to avoid blocking the API.

    Args:
        task_id: The simulation task ID
        request: The simulation request parameters
        user_id: The user ID (required for Yahoo platform)
    """
    async with async_session_maker() as db:
        task_repo = SimulationTaskRepository(db)
        cache_repo = SimulationCacheRepository(db)

        task = await task_repo.get_by_id(task_id)
        if task is None:
            return

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
            season = request.season or get_current_season(sport_enum)

            # Update status to running
            await task_repo.update_progress(task, 5)
            await db.commit()

            # Fetch league data
            teams, division_names = await adapter.fetch_standings(request.league_id, season)
            await task_repo.update_progress(task, 15)
            await db.commit()

            remaining, current_week, total_weeks = await adapter.fetch_schedule(
                request.league_id, season, teams
            )
            await task_repo.update_progress(task, 25)
            await db.commit()

            h2h = await adapter.fetch_head_to_head(request.league_id, season, teams)
            settings = await adapter.fetch_league_settings(request.league_id, season)

            # If Yahoo or CBS token was refreshed, persist the new tokens
            if hasattr(adapter, '_token_refreshed') and adapter._token_refreshed:
                await db.flush()

            await task_repo.update_progress(task, 35)
            await db.commit()

            playoff_spots = settings.get("playoff_spots", 6)

            # Calculate magic numbers
            magic_numbers = calculate_magic_numbers(teams, remaining, h2h, playoff_spots)
            await task_repo.update_progress(task, 40)
            await db.commit()

            # Generate scenarios
            if len(remaining) <= 10:
                clinch_scenarios, elimination_scenarios = brute_force_clinch_elimination(
                    teams, remaining, h2h, division_names, current_week, playoff_spots
                )
            else:
                clinch_scenarios, elimination_scenarios = generate_clinch_elimination_scenarios(
                    teams, remaining, magic_numbers, division_names, current_week, playoff_spots
                )
            await task_repo.update_progress(task, 50)
            await db.commit()

            # Determine simulation count
            n_simulations = request.n_simulations
            if request.quick_mode:
                n_simulations = 1000

            # Run simulation with progress updates
            def progress_callback(pct: float):
                # Map simulation progress (0-100) to task progress (50-95)
                nonlocal task
                task.progress = int(50 + pct * 0.45)

            results = simulate_season(
                teams, remaining, h2h, n_simulations, playoff_spots,
                progress_callback=progress_callback
            )
            await task_repo.update_progress(task, 95)
            await db.commit()

            # Build response data
            team_results = []
            for team in sorted(teams.values(), key=lambda t: results[t.id].playoff_appearances, reverse=True):
                team_result = results[team.id]
                team_magic = magic_numbers[team.id]

                # Calculate percentages
                div_pct = team_result.division_wins / n_simulations
                playoff_pct = team_result.playoff_appearances / n_simulations
                first_seed_pct = team_result.first_seed / n_simulations
                last_pct = team_result.last_place / n_simulations

                # Cap at 99.9% if not mathematically clinched
                if team_magic.magic_division is not None and div_pct >= 0.9995:
                    div_pct = 0.999
                if team_magic.magic_playoffs is not None and playoff_pct >= 0.9995:
                    playoff_pct = 0.999
                if team_magic.magic_first_seed is not None and first_seed_pct >= 0.9995:
                    first_seed_pct = 0.999
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
                    division_pct=div_pct,
                    playoff_pct=playoff_pct,
                    first_seed_pct=first_seed_pct,
                    last_place_pct=last_pct,
                    magic_division=team_magic.magic_division,
                    magic_playoffs=team_magic.magic_playoffs,
                    magic_first_seed=team_magic.magic_first_seed,
                    magic_last=team_magic.magic_last
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
                clinch_scenarios=clinch_scenarios,
                elimination_scenarios=elimination_scenarios
            )

            # Cache the results
            await cache_repo.set(
                platform=request.platform,
                league_id=request.league_id,
                season=season,
                week=current_week,
                results=response_data.model_dump(),
                sport=request.sport
            )

            # Mark task complete
            await task_repo.complete(task, response_data.model_dump())
            await db.commit()

        except Exception as e:
            await task_repo.fail(task, str(e))
            await db.commit()


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
    The simulation runs in the background.
    """
    # Convert sport string to Sport enum
    try:
        sport_enum = Sport(request.sport.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid sport: {request.sport}. Supported: basketball, football, baseball, hockey"
        )

    season = request.season or get_current_season(sport_enum)

    # Check cache first
    cache_repo = SimulationCacheRepository(db)
    cached = await cache_repo.get(request.platform, request.league_id, season, 0, request.sport)

    # Note: We don't have the current week yet, so we check for any cached result
    # A more sophisticated approach would be to fetch the current week first

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

    # Validate the league
    try:
        adapter = get_adapter(request.platform, sport_enum, yahoo_credential=yahoo_credential, cbs_credential=cbs_credential)
        await adapter.validate_league(request.league_id, season)

        # If token was refreshed, persist the new tokens
        if hasattr(adapter, '_token_refreshed') and adapter._token_refreshed:
            await db.commit()
    except LeagueNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"League {request.league_id} not found"
        )
    except LeaguePrivateError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This league is private. Only public leagues can be simulated."
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

    # Create task
    task_repo = SimulationTaskRepository(db)
    task = await task_repo.create(request.platform, request.league_id, season, request.sport)
    await db.commit()

    # Start background task (pass user_id for Yahoo credential lookup)
    user_id = current_user.id if current_user else None
    background_tasks.add_task(run_simulation_task, task.id, request, user_id)

    return SimulationTaskResponse(
        task_id=task.id,
        status="pending",
        progress=0
    )


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
        progress=task.progress,
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
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Simulation is still running"
        )

    if task.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Simulation failed: {task.error_message}"
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
                    "progress": current_task.progress
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
