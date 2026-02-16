"""
Monte Carlo simulation engine for playoff probability calculations.
"""

import random
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

from .models import Team, Matchup, H2HDict, SimulationResult
from .tiebreakers import resolve_tiebreaker


PLAYOFF_SPOTS = 6


def apply_outcome(
    teams: Dict[int, Team],
    matchups: List[Matchup],
    outcomes: List[int],
    h2h: H2HDict
) -> Tuple[Dict[int, Team], H2HDict]:
    """
    Apply a specific set of outcomes to the current standings.

    Args:
        teams: Current team standings
        matchups: List of matchups to resolve
        outcomes: List of winner IDs (one per matchup)
        h2h: Historical H2H records

    Returns:
        Tuple of (updated teams dict copies, sim_h2h dict for these outcomes)
    """
    sim_teams = {tid: t.copy() for tid, t in teams.items()}
    sim_h2h: Dict[Tuple[int, int], List[int]] = defaultdict(lambda: [0, 0, 0])

    for matchup, winner_id in zip(matchups, outcomes):
        loser_id = (matchup.away_team_id if winner_id == matchup.home_team_id
                    else matchup.home_team_id)

        sim_teams[winner_id].wins += 1
        sim_teams[loser_id].losses += 1

        if matchup.is_division_game:
            sim_teams[winner_id].division_wins += 1
            sim_teams[loser_id].division_losses += 1

        key = (min(winner_id, loser_id), max(winner_id, loser_id))
        if winner_id < loser_id:
            sim_h2h[key][0] += 1
        else:
            sim_h2h[key][1] += 1

    # Convert lists to tuples
    return sim_teams, {k: tuple(v) for k, v in sim_h2h.items()}


def determine_playoffs(
    teams: Dict[int, Team],
    h2h: H2HDict,
    sim_h2h: H2HDict,
    playoff_spots: int = PLAYOFF_SPOTS,
    disfavor_id: Optional[int] = None,
    favor_id: Optional[int] = None
) -> Tuple[List[int], List[int]]:
    """
    Determine playoff teams based on standings and tiebreakers.

    Args:
        teams: Team standings
        h2h: Historical head-to-head records
        sim_h2h: Simulated head-to-head records
        playoff_spots: Number of playoff spots
        disfavor_id: Team that always loses coin flips (worst case for clinch)
        favor_id: Team that always wins coin flips (best case for elimination)

    Returns:
        Tuple of (playoff team IDs in seeding order, division winner IDs)
    """
    # Group teams by division
    divisions = defaultdict(list)
    for team in teams.values():
        divisions[team.division_id].append(team)

    # Find division winners
    division_winners = []
    for div_id, div_teams in sorted(divisions.items()):
        # Sort by win percentage
        sorted_div = sorted(div_teams, key=lambda t: t.win_pct, reverse=True)

        # Find teams tied for best record
        best_pct = sorted_div[0].win_pct
        tied_for_first = [t for t in sorted_div if t.win_pct == best_pct]

        if len(tied_for_first) > 1:
            tied_for_first = resolve_tiebreaker(
                tied_for_first, h2h, sim_h2h,
                disfavor_id=disfavor_id, favor_id=favor_id
            )

        division_winners.append(tied_for_first[0].id)

    # Get remaining teams for wild card spots
    remaining_teams = [t for t in teams.values() if t.id not in division_winners]

    # Sort remaining teams by win percentage
    remaining_sorted = sorted(remaining_teams, key=lambda t: t.win_pct, reverse=True)

    # Fill remaining playoff spots with tiebreaker resolution
    wild_card = []
    i = 0
    spots_needed = playoff_spots - len(division_winners)

    while len(wild_card) < spots_needed and i < len(remaining_sorted):
        # Find all teams tied at this record
        current_pct = remaining_sorted[i].win_pct
        tied_group = [t for t in remaining_sorted[i:] if t.win_pct == current_pct]

        if len(tied_group) > 1:
            tied_group = resolve_tiebreaker(
                tied_group, h2h, sim_h2h,
                disfavor_id=disfavor_id, favor_id=favor_id
            )

        # Add teams from this group up to spots needed
        for team in tied_group:
            if len(wild_card) < spots_needed:
                wild_card.append(team.id)
            else:
                break

        i += len(tied_group)

    # Combine all playoff teams
    all_playoff_ids = division_winners + wild_card

    # Sort all playoff teams by record to determine seeding (#1 seed = best record)
    playoff_teams_sorted = sorted(
        all_playoff_ids,
        key=lambda tid: teams[tid].win_pct,
        reverse=True
    )

    # Handle ties for #1 seed using tiebreaker
    if len(playoff_teams_sorted) >= 2:
        best_pct = teams[playoff_teams_sorted[0]].win_pct
        tied_for_first = [teams[tid] for tid in playoff_teams_sorted if teams[tid].win_pct == best_pct]
        if len(tied_for_first) > 1:
            tied_for_first = resolve_tiebreaker(
                tied_for_first, h2h, sim_h2h,
                disfavor_id=disfavor_id, favor_id=favor_id
            )
            # Rebuild the list with tiebreaker order for tied teams
            tied_ids = [t.id for t in tied_for_first]
            other_ids = [tid for tid in playoff_teams_sorted if teams[tid].win_pct != best_pct]
            playoff_teams_sorted = tied_ids + other_ids

    return playoff_teams_sorted, division_winners


def simulate_season(
    teams: Dict[int, Team],
    remaining: List[Matchup],
    h2h: H2HDict,
    n_simulations: int = 10000,
    playoff_spots: int = PLAYOFF_SPOTS,
    progress_callback: Optional[callable] = None
) -> Dict[int, SimulationResult]:
    """
    Run Monte Carlo simulation of the remaining season.

    Args:
        teams: Current team standings
        remaining: List of remaining matchups
        h2h: Historical head-to-head records
        n_simulations: Number of simulations to run
        playoff_spots: Number of playoff spots
        progress_callback: Optional callback for progress updates (receives percent complete)

    Returns:
        Dict mapping team_id -> SimulationResult
    """
    results = {
        team_id: SimulationResult(team_id=team_id)
        for team_id in teams
    }

    for sim_idx in range(n_simulations):
        # Report progress periodically
        if progress_callback and sim_idx % 100 == 0:
            progress_callback(sim_idx / n_simulations * 100)

        # Copy current standings
        sim_teams = {tid: t.copy() for tid, t in teams.items()}

        # Track simulated H2H results
        sim_h2h: Dict[Tuple[int, int], List[int]] = defaultdict(lambda: [0, 0, 0])

        # Simulate remaining matchups (50/50 random)
        for matchup in remaining:
            winner_id = random.choice([matchup.home_team_id, matchup.away_team_id])
            loser_id = (matchup.away_team_id if winner_id == matchup.home_team_id
                       else matchup.home_team_id)

            # Update records
            sim_teams[winner_id].wins += 1
            sim_teams[loser_id].losses += 1

            # Update division records if applicable
            if matchup.is_division_game:
                sim_teams[winner_id].division_wins += 1
                sim_teams[loser_id].division_losses += 1

            # Track simulated H2H
            key = (min(winner_id, loser_id), max(winner_id, loser_id))
            if winner_id < loser_id:
                sim_h2h[key][0] += 1
            else:
                sim_h2h[key][1] += 1

        # Convert lists to tuples for sim_h2h
        sim_h2h_tuples = {k: tuple(v) for k, v in sim_h2h.items()}

        # Determine final standings
        playoff_teams, division_winners = determine_playoffs(
            sim_teams, h2h, sim_h2h_tuples, playoff_spots
        )

        # Record division winners
        for team_id in division_winners:
            results[team_id].division_wins += 1

        # Record playoff appearances
        for team_id in playoff_teams:
            results[team_id].playoff_appearances += 1

        # Record #1 seed (first playoff team is the #1 seed)
        if playoff_teams:
            results[playoff_teams[0]].first_seed += 1

        # Record last place - find teams with worst record, use tiebreaker for ties
        all_teams = list(sim_teams.values())
        worst_pct = min(t.win_pct for t in all_teams)
        tied_for_last = [t for t in all_teams if t.win_pct == worst_pct]

        if len(tied_for_last) > 1:
            # Use tiebreaker in reverse (worst team first) - no favor/disfavor for fair randomization
            tied_for_last = resolve_tiebreaker(tied_for_last, h2h, sim_h2h_tuples)
            # Last place is the LAST in the resolved order (worst of the worst)
            last_place_team = tied_for_last[-1]
        else:
            last_place_team = tied_for_last[0]

        results[last_place_team.id].last_place += 1

    # Final progress update
    if progress_callback:
        progress_callback(100)

    return results
