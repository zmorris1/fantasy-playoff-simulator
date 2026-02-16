"""
Clinch and elimination scenario generation.

Generates narrative scenarios for the current week describing how teams can
clinch playoffs/division or be eliminated.
"""

import itertools
from collections import defaultdict
from typing import Dict, List, Tuple, Any, Optional

from .models import Team, Matchup, MagicNumbers, H2HDict
from .engine import determine_playoffs, apply_outcome


PLAYOFF_SPOTS = 6


def generate_clinch_elimination_scenarios(
    teams: Dict[int, Team],
    remaining: List[Matchup],
    magic_numbers: Dict[int, MagicNumbers],
    division_names: Dict[int, str],
    current_week: int,
    playoff_spots: int = PLAYOFF_SPOTS
) -> Tuple[List[str], List[str]]:
    """
    Generate narrative clinch and elimination scenarios for the current week.

    This is the analytical approach used when there are too many remaining games
    for brute-force enumeration.

    Args:
        teams: Current team standings
        remaining: List of remaining matchups
        magic_numbers: Pre-calculated magic numbers
        division_names: Division ID to name mapping
        current_week: Current week number
        playoff_spots: Number of playoff spots

    Returns:
        Tuple of (clinch_scenarios, elimination_scenarios) as lists of strings
    """
    # Get current week's matchups only
    current_week_matchups = [m for m in remaining if m.week == current_week]

    # Build lookup: team_id -> opponent_id for this week
    opponents = {}
    for m in current_week_matchups:
        opponents[m.home_team_id] = m.away_team_id
        opponents[m.away_team_id] = m.home_team_id

    # Helper to get effective wins
    def effective_wins(team: Team) -> float:
        return team.wins + 0.5 * team.ties

    # Count remaining games per team
    games_remaining = defaultdict(int)
    for m in remaining:
        games_remaining[m.home_team_id] += 1
        games_remaining[m.away_team_id] += 1

    # Group teams by division
    divisions = defaultdict(list)
    for team in teams.values():
        divisions[team.division_id].append(team)

    clinch_scenarios = []
    elimination_scenarios = []

    for team in teams.values():
        team_magic = magic_numbers[team.id]
        opponent_id = opponents.get(team.id)
        opponent = teams.get(opponent_id) if opponent_id else None

        # === CLINCH SCENARIOS ===

        # Can clinch division with a win (magic number 1)
        if team_magic.magic_division == 1 and opponent:
            clinch_scenarios.append(
                f"{team.name} clinches division with a WIN vs {opponent.name}"
            )

        # Can clinch playoffs with a win (magic number 1)
        if team_magic.magic_playoffs == 1 and opponent:
            clinch_scenarios.append(
                f"{team.name} clinches playoff spot with a WIN vs {opponent.name}"
            )

        # Can clinch #1 seed with a win
        if team_magic.magic_first_seed == 1 and opponent:
            clinch_scenarios.append(
                f"{team.name} clinches #1 seed with a WIN vs {opponent.name}"
            )

        # === ELIMINATION SCENARIOS ===

        # Check if team can be eliminated from playoff contention this week
        team_max_potential = effective_wins(team) + games_remaining[team.id]

        if opponent:
            team_max_if_loses = team_max_potential - 1

            # Count how many teams would have higher guaranteed minimums
            scenario_mins = []
            for other in teams.values():
                if other.id == team.id:
                    continue
                if other.id == opponent_id:
                    # Opponent wins, gets +1
                    min_wins = effective_wins(other) + 1
                else:
                    min_wins = effective_wins(other)
                scenario_mins.append((other.id, min_wins))

            scenario_mins.sort(key=lambda x: x[1], reverse=True)

            # Calculate current standings to check if already eliminated
            current_eff_wins = [(t.id, effective_wins(t)) for t in teams.values() if t.id != team.id]
            current_eff_wins.sort(key=lambda x: x[1], reverse=True)
            sixth_best_current = current_eff_wins[playoff_spots - 1][1] if len(current_eff_wins) >= playoff_spots else 0

            not_already_eliminated = team_max_potential >= sixth_best_current

            if len(scenario_mins) >= playoff_spots:
                sixth_best_min = scenario_mins[playoff_spots - 1][1]
                if sixth_best_min > team_max_if_loses and not_already_eliminated:
                    elimination_scenarios.append(
                        f"{team.name} eliminated from playoffs if: LOSS to {opponent.name}"
                    )

    # Remove duplicates
    seen_clinch = set()
    unique_clinch = []
    for s in clinch_scenarios:
        if s not in seen_clinch:
            seen_clinch.add(s)
            unique_clinch.append(s)

    seen_elim = set()
    unique_elim = []
    for s in elimination_scenarios:
        if s not in seen_elim:
            seen_elim.add(s)
            unique_elim.append(s)

    return unique_clinch, unique_elim


def brute_force_clinch_elimination(
    teams: Dict[int, Team],
    remaining: List[Matchup],
    h2h: H2HDict,
    division_names: Dict[int, str],
    current_week: int,
    playoff_spots: int = PLAYOFF_SPOTS,
    progress_callback: Optional[callable] = None
) -> Tuple[List[str], List[str]]:
    """
    Enumerate all possible outcomes for remaining games and use determine_playoffs()
    directly to verify clinch/elimination scenarios. Only used when remaining games <= 10.

    For each team:
    - Clinch: call determine_playoffs with disfavor_id (team loses all coin flips).
      If team makes playoffs in ALL outcomes, it has clinched.
    - Elimination: call determine_playoffs with favor_id (team wins all coin flips).
      If team misses playoffs in ALL outcomes, it is eliminated.

    Multiple runs per outcome (25) handle randomness in OTHER teams' coin flips.

    Args:
        teams: Current team standings
        remaining: List of remaining matchups
        h2h: Historical head-to-head records
        division_names: Division ID to name mapping
        current_week: Current week number
        playoff_spots: Number of playoff spots
        progress_callback: Optional callback for progress updates

    Returns:
        Tuple of (clinch_scenarios, elimination_scenarios) as lists of strings
    """
    # Get current week matchups
    current_week_matchups = [m for m in remaining if m.week == current_week]

    if len(current_week_matchups) == 0:
        return [], []

    # Build lookup: team_id -> opponent_id for this week
    opponents = {}
    for m in current_week_matchups:
        opponents[m.home_team_id] = m.away_team_id
        opponents[m.away_team_id] = m.home_team_id

    # For each game, the two possible winners
    n_games = len(current_week_matchups)
    game_options = [(m.home_team_id, m.away_team_id) for m in current_week_matchups]

    total_outcomes = 2 ** n_games
    coin_flip_runs = 25

    team_ids = list(teams.keys())

    # Track results
    clinch_all = {tid: True for tid in team_ids}
    elim_all = {tid: True for tid in team_ids}
    team_clinch_when_wins = {tid: True for tid in team_ids}
    team_elim_when_loses = {tid: True for tid in team_ids}
    div_clinch_all = {tid: True for tid in team_ids}
    div_elim_all = {tid: True for tid in team_ids}
    team_div_clinch_when_wins = {tid: True for tid in team_ids}
    team_div_elim_when_loses = {tid: True for tid in team_ids}

    # Map team_id -> game index
    team_game_idx = {}
    for idx, m in enumerate(current_week_matchups):
        team_game_idx[m.home_team_id] = idx
        team_game_idx[m.away_team_id] = idx

    outcome_playoff_results = {}

    for outcome_idx in range(total_outcomes):
        if progress_callback and outcome_idx % 10 == 0:
            progress_callback(outcome_idx / total_outcomes * 100)

        # Convert outcome index to list of winners
        winners = []
        for game_idx in range(n_games):
            bit = (outcome_idx >> game_idx) & 1
            winners.append(game_options[game_idx][bit])

        outcome_key = tuple(winners)

        # Apply this week's outcomes
        sim_teams, sim_h2h = apply_outcome(teams, current_week_matchups, winners, h2h)

        outcome_results = {}

        for tid in team_ids:
            # Clinch check: disfavor this team (worst case)
            made_playoffs_all_runs = True
            won_division_all_runs = True
            for _ in range(coin_flip_runs):
                playoff_teams, division_winners = determine_playoffs(
                    sim_teams, h2h, sim_h2h,
                    playoff_spots=playoff_spots,
                    disfavor_id=tid
                )
                if tid not in playoff_teams:
                    made_playoffs_all_runs = False
                if tid not in division_winners:
                    won_division_all_runs = False
                if not made_playoffs_all_runs and not won_division_all_runs:
                    break

            if not made_playoffs_all_runs:
                clinch_all[tid] = False
                game_idx = team_game_idx.get(tid)
                if game_idx is not None and winners[game_idx] == tid:
                    team_clinch_when_wins[tid] = False

            if not won_division_all_runs:
                div_clinch_all[tid] = False
                game_idx = team_game_idx.get(tid)
                if game_idx is not None and winners[game_idx] == tid:
                    team_div_clinch_when_wins[tid] = False

            # Elimination check: favor this team (best case)
            missed_playoffs_all_runs = True
            missed_division_all_runs = True
            for _ in range(coin_flip_runs):
                playoff_teams, division_winners = determine_playoffs(
                    sim_teams, h2h, sim_h2h,
                    playoff_spots=playoff_spots,
                    favor_id=tid
                )
                if tid in playoff_teams:
                    missed_playoffs_all_runs = False
                if tid in division_winners:
                    missed_division_all_runs = False
                if not missed_playoffs_all_runs and not missed_division_all_runs:
                    break

            if not missed_playoffs_all_runs:
                elim_all[tid] = False
                game_idx = team_game_idx.get(tid)
                if game_idx is not None and winners[game_idx] != tid:
                    team_elim_when_loses[tid] = False

            if not missed_division_all_runs:
                div_elim_all[tid] = False
                game_idx = team_game_idx.get(tid)
                if game_idx is not None and winners[game_idx] != tid:
                    team_div_elim_when_loses[tid] = False

            outcome_results[tid] = {
                'clinch': made_playoffs_all_runs,
                'elim': missed_playoffs_all_runs,
                'div_clinch': won_division_all_runs,
                'div_elim': missed_division_all_runs
            }

        outcome_playoff_results[outcome_key] = outcome_results

    # Extract scenarios
    clinch_scenarios = []
    elimination_scenarios = []

    for tid in team_ids:
        team = teams[tid]
        opponent_id = opponents.get(tid)
        opponent = teams.get(opponent_id) if opponent_id else None

        # === PLAYOFF CLINCH ===
        if clinch_all[tid]:
            pass  # Already clinched
        elif team_clinch_when_wins[tid] and opponent:
            clinch_scenarios.append(
                f"{team.name} clinches playoff spot with a WIN vs {opponent.name}"
            )

        # === DIVISION CLINCH ===
        if div_clinch_all[tid]:
            pass  # Already clinched
        elif team_div_clinch_when_wins[tid] and opponent:
            clinch_scenarios.append(
                f"{team.name} clinches division with a WIN vs {opponent.name}"
            )

        # === PLAYOFF ELIMINATION ===
        if elim_all[tid]:
            pass  # Already eliminated
        elif team_elim_when_loses[tid] and opponent:
            elimination_scenarios.append(
                f"{team.name} eliminated from playoffs if: LOSS to {opponent.name}"
            )

        # === DIVISION ELIMINATION ===
        if div_elim_all[tid]:
            pass  # Already eliminated
        elif team_div_elim_when_loses[tid] and opponent:
            elimination_scenarios.append(
                f"{team.name} eliminated from division race if: LOSS to {opponent.name}"
            )

    if progress_callback:
        progress_callback(100)

    # Deduplicate
    seen = set()
    unique_clinch = []
    for s in clinch_scenarios:
        if s not in seen:
            seen.add(s)
            unique_clinch.append(s)

    seen_elim = set()
    unique_elim = []
    for s in elimination_scenarios:
        if s not in seen_elim:
            seen_elim.add(s)
            unique_elim.append(s)

    return unique_clinch, unique_elim
