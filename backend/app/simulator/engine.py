"""
Monte Carlo simulation engine for playoff probability calculations.
"""

import random
from collections import defaultdict
from typing import Callable, Dict, List, Tuple, Optional

from .models import Team, Matchup, H2HDict, SimulationResult
from .tiebreakers import CoinFlipper, H2HTable, resolve_tiebreaker


PLAYOFF_SPOTS = 6


def _record_h2h(sim_h2h: Dict[Tuple[int, int], List[int]], team1_id: int, team2_id: int,
                team1_wins: int, team2_wins: int) -> None:
    """Add a result to a mutable H2H dict keyed (min_id, max_id)."""
    if team1_id < team2_id:
        entry = sim_h2h[(team1_id, team2_id)]
        entry[0] += team1_wins
        entry[1] += team2_wins
    else:
        entry = sim_h2h[(team2_id, team1_id)]
        entry[0] += team2_wins
        entry[1] += team1_wins


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

        _record_h2h(sim_h2h, winner_id, loser_id, 1, 0)

    # Convert lists to tuples
    return sim_teams, {k: tuple(v) for k, v in sim_h2h.items()}


def determine_playoffs(
    teams: Dict[int, Team],
    h2h: H2HDict,
    sim_h2h: H2HDict,
    playoff_spots: int = PLAYOFF_SPOTS,
    disfavor_id: Optional[int] = None,
    favor_id: Optional[int] = None,
    flipper: Optional[CoinFlipper] = None
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
        flipper: Orders teams still tied after every tiebreaker (default: random)

    Returns:
        Tuple of (playoff team IDs in seeding order, division winner IDs)
    """
    table = H2HTable(h2h, sim_h2h)
    pct = {tid: t.win_pct for tid, t in teams.items()}

    def resolve(group: List[Team]) -> List[Team]:
        return resolve_tiebreaker(
            group, h2h, sim_h2h,
            disfavor_id=disfavor_id, favor_id=favor_id,
            flipper=flipper, table=table
        )

    # Group teams by division
    divisions = defaultdict(list)
    for team in teams.values():
        divisions[team.division_id].append(team)

    # Find division winners
    division_winners = []
    for div_id in sorted(divisions, key=str):
        div_teams = divisions[div_id]
        best_pct = max(pct[t.id] for t in div_teams)
        tied_for_first = [t for t in div_teams if pct[t.id] == best_pct]

        if len(tied_for_first) > 1:
            tied_for_first = resolve(tied_for_first)

        division_winners.append(tied_for_first[0].id)

    # Get remaining teams for wild card spots
    winner_set = set(division_winners)
    remaining_teams = [t for t in teams.values() if t.id not in winner_set]

    # Sort remaining teams by win percentage
    remaining_sorted = sorted(remaining_teams, key=lambda t: pct[t.id], reverse=True)

    # Fill remaining playoff spots with tiebreaker resolution
    wild_card = []
    i = 0
    spots_needed = playoff_spots - len(division_winners)

    while len(wild_card) < spots_needed and i < len(remaining_sorted):
        # Find all teams tied at this record
        current_pct = pct[remaining_sorted[i].id]
        tied_group = [t for t in remaining_sorted[i:] if pct[t.id] == current_pct]

        # Only break the tie if it straddles the playoff line
        if len(tied_group) > 1 and len(wild_card) + len(tied_group) > spots_needed:
            tied_group = resolve(tied_group)

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
    playoff_teams_sorted = sorted(all_playoff_ids, key=pct.__getitem__, reverse=True)

    # Handle ties for #1 seed using tiebreaker
    if len(playoff_teams_sorted) >= 2:
        best_pct = pct[playoff_teams_sorted[0]]
        tied_for_first = [teams[tid] for tid in playoff_teams_sorted if pct[tid] == best_pct]
        if len(tied_for_first) > 1:
            tied_for_first = resolve(tied_for_first)
            # Rebuild the list with tiebreaker order for tied teams
            tied_ids = [t.id for t in tied_for_first]
            other_ids = [tid for tid in playoff_teams_sorted if pct[tid] != best_pct]
            playoff_teams_sorted = tied_ids + other_ids

    return playoff_teams_sorted, division_winners


def simulate_season(
    teams: Dict[int, Team],
    remaining: List[Matchup],
    h2h: H2HDict,
    n_simulations: int = 10000,
    playoff_spots: int = PLAYOFF_SPOTS,
    progress_callback: Optional[Callable[[float], None]] = None,
    categories_per_matchup: int = 1
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
        categories_per_matchup: 1 for leagues where each matchup is a single
            win/loss (points, most-categories). For "each category" leagues,
            the number of categories: every matchup then splits that many
            wins between the two teams, each category a 50/50 coin flip.

    Returns:
        Dict mapping team_id -> SimulationResult
    """
    results = {
        team_id: SimulationResult(team_id=team_id)
        for team_id in teams
    }

    n_cats = max(1, int(categories_per_matchup))
    getrandbits = random.getrandbits
    games = [(m.home_team_id, m.away_team_id, m.is_division_game) for m in remaining]
    report_every = max(1, n_simulations // 100)

    for sim_idx in range(n_simulations):
        # Report progress periodically
        if progress_callback and sim_idx % report_every == 0:
            progress_callback(sim_idx / n_simulations * 100)

        # Copy current standings
        sim_teams = {tid: t.copy() for tid, t in teams.items()}

        # Track simulated H2H results
        sim_h2h: Dict[Tuple[int, int], List[int]] = defaultdict(lambda: [0, 0, 0])

        for home_id, away_id, is_div in games:
            home = sim_teams[home_id]
            away = sim_teams[away_id]

            if n_cats == 1:
                # Single result per matchup, 50/50
                home_wins = getrandbits(1)
                away_wins = 1 - home_wins
            else:
                # Each category is an independent 50/50 coin flip
                home_wins = getrandbits(n_cats).bit_count()
                away_wins = n_cats - home_wins

            home.wins += home_wins
            home.losses += away_wins
            away.wins += away_wins
            away.losses += home_wins

            if is_div:
                home.division_wins += home_wins
                home.division_losses += away_wins
                away.division_wins += away_wins
                away.division_losses += home_wins

            _record_h2h(sim_h2h, home_id, away_id, home_wins, away_wins)

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
        worst_pct = min(t.win_pct for t in sim_teams.values())
        tied_for_last = [t for t in sim_teams.values() if t.win_pct == worst_pct]

        if len(tied_for_last) > 1:
            # Last place is the LAST in the resolved order (worst of the worst)
            tied_for_last = resolve_tiebreaker(tied_for_last, h2h, sim_h2h_tuples)

        results[tied_for_last[-1].id].last_place += 1

    # Final progress update
    if progress_callback:
        progress_callback(100)

    return results
