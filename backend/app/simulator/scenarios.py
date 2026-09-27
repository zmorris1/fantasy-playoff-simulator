"""
Clinch and elimination scenario generation.

Generates narrative scenarios for the current week describing how teams can
clinch playoffs/division or be eliminated.
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .models import Team, Matchup, H2HDict
from .engine import determine_playoffs, apply_outcome
from .tiebreakers import CoinFlipper, all_coin_flip_outcomes
from .magic_numbers import LeagueMath


PLAYOFF_SPOTS = 6

# Exhaustive enumeration covers every outcome of every remaining game (2^n),
# so it is only used near the end of the season
BRUTE_FORCE_MAX_GAMES = 10

# Cap on coin-flip orderings examined per team and outcome (6! = a 6-way
# coin flip; real leagues essentially never get near it)
COIN_FLIP_ORDERINGS_LIMIT = 720

GOAL_LABELS = {
    "playoffs": "playoff spot",
    "division": "division",
    "first_seed": "#1 seed",
}

ELIMINATION_LABELS = {
    "playoffs": "eliminated from playoffs",
    "division": "eliminated from division race",
}


@dataclass
class ScenarioReport:
    """Narrative scenarios for this week, plus exact status when known."""

    clinch: List[str]
    elimination: List[str]
    # team_id -> {"clinched_playoffs": bool, ...}. Only set by exhaustive
    # enumeration, where clinched/eliminated are known exactly.
    statuses: Optional[Dict[int, Dict[str, bool]]] = None


def scenario_week(remaining: List[Matchup], current_week: int) -> int:
    """The week scenarios describe: the current week, or the next week with games."""
    weeks = {m.week for m in remaining}
    if current_week in weeks or not weeks:
        return current_week
    return min(weeks)


def _opponents(remaining: List[Matchup], week: int) -> Dict[int, int]:
    opponents = {}
    for m in remaining:
        if m.week == week:
            opponents[m.home_team_id] = m.away_team_id
            opponents[m.away_team_id] = m.home_team_id
    return opponents


def _dedupe(items: List[str]) -> List[str]:
    return list(dict.fromkeys(items))


def generate_clinch_elimination_scenarios(
    teams: Dict[int, Team],
    remaining: List[Matchup],
    h2h: H2HDict,
    current_week: int,
    playoff_spots: int = PLAYOFF_SPOTS,
    categories_per_matchup: int = 1
) -> ScenarioReport:
    """
    Generate narrative clinch and elimination scenarios for the current week.

    This is the analytical approach used when there are too many remaining games
    for brute-force enumeration. A scenario is only reported when it holds no
    matter how every other game (this week and later) turns out.

    Args:
        teams: Current team standings
        remaining: List of remaining matchups
        h2h: Historical head-to-head records
        current_week: Current week number
        playoff_spots: Number of playoff spots
        categories_per_matchup: Units per matchup (see simulate_season)

    Returns:
        ScenarioReport with clinch and elimination scenario strings
    """
    league = LeagueMath(teams, remaining, h2h, playoff_spots, categories_per_matchup)
    units = league.units
    opponents = _opponents(remaining, scenario_week(remaining, current_week))

    clinch_scenarios = []
    elimination_scenarios = []

    for team in teams.values():
        opponent_id = opponents.get(team.id)
        if opponent_id is None:
            continue
        opponent = teams[opponent_id]
        eff = league.eff(team)
        later_gain = league.max_gain(team.id) - units

        # === CLINCH SCENARIOS ===
        for goal, label in GOAL_LABELS.items():
            if league.magic_number(team, goal) == 0:
                continue  # Already clinched

            # Fewest units won this week that clinch, even if the team loses
            # everything afterwards
            for won in range(1, units + 1):
                ahead = league.can_finish_ahead(team, eff + won, {opponent_id: won})
                if league.clinched_given(team, ahead, goal):
                    if units == 1:
                        text = f"{team.name} clinches {label} with a WIN vs {opponent.name}"
                    else:
                        text = (f"{team.name} clinches {label} by winning {won}+ of "
                                f"{units} categories vs {opponent.name}")
                    clinch_scenarios.append(text)
                    break

        # === ELIMINATION SCENARIOS ===
        for goal, label in ELIMINATION_LABELS.items():
            if league.eliminated(team, goal):
                continue  # Already eliminated

            # Most units won this week that still eliminate the team, even if
            # it wins everything afterwards
            for won in range(units - 1, -1, -1):
                best = eff + won + later_gain
                ahead = league.certainly_ahead(team, best, {opponent_id: units - won})
                if league.eliminated_given(team, ahead, goal):
                    if units == 1:
                        text = f"{team.name} {label} if: LOSS to {opponent.name}"
                    else:
                        text = (f"{team.name} {label} if: they win {won} or fewer of "
                                f"{units} categories vs {opponent.name}")
                    elimination_scenarios.append(text)
                    break

    return ScenarioReport(_dedupe(clinch_scenarios), _dedupe(elimination_scenarios))


def _achieved(team_id: int, playoff_teams: List[int], division_winners: List[int]) -> Dict[str, bool]:
    return {
        "playoffs": team_id in playoff_teams,
        "division": team_id in division_winners,
        "first_seed": bool(playoff_teams) and playoff_teams[0] == team_id,
    }


def brute_force_clinch_elimination(
    teams: Dict[int, Team],
    remaining: List[Matchup],
    h2h: H2HDict,
    current_week: int,
    playoff_spots: int = PLAYOFF_SPOTS,
    progress_callback: Optional[Callable[[float], None]] = None
) -> ScenarioReport:
    """
    Enumerate every outcome of every remaining game and use determine_playoffs()
    directly to find exact clinch/elimination scenarios. Only used when there
    are at most BRUTE_FORCE_MAX_GAMES remaining games.

    For each team and goal (playoffs, division, #1 seed):
    - Clinched: achieved in ALL outcomes with the team losing every coin flip.
    - Eliminated: missed in ALL outcomes with the team winning every coin flip.
    - "Clinches with a WIN": achieved in all outcomes where the team wins this
      week's game. "Eliminated if LOSS": missed in all outcomes where it loses.

    When a coin flip decided something, every possible ordering of the other
    teams' coin flips is checked as well.

    Args:
        teams: Current team standings
        remaining: List of remaining matchups
        h2h: Historical head-to-head records
        current_week: Current week number
        playoff_spots: Number of playoff spots
        progress_callback: Optional callback for progress updates

    Returns:
        ScenarioReport with scenario strings and exact per-team statuses
    """
    week = scenario_week(remaining, current_week)
    opponents = _opponents(remaining, week)
    team_ids = list(teams.keys())

    # Index of each team's game this week within `remaining`
    this_week_game = {}
    for idx, m in enumerate(remaining):
        if m.week == week:
            this_week_game[m.home_team_id] = idx
            this_week_game[m.away_team_id] = idx

    game_options = [(m.home_team_id, m.away_team_id) for m in remaining]
    n_games = len(remaining)
    total_outcomes = 1 << n_games
    report_every = max(1, total_outcomes // 100)

    goals = tuple(GOAL_LABELS)
    always = {g: dict.fromkeys(team_ids, True) for g in goals}
    never = {g: dict.fromkeys(team_ids, True) for g in goals}
    # "With a WIN" / "if LOSS" only apply to teams that play this week
    has_game = {tid: tid in this_week_game for tid in team_ids}
    always_if_win = {g: dict(has_game) for g in goals}
    never_if_loss = {g: dict(has_game) for g in goals}

    def pinned_result(sim_teams, sim_h2h, tid: int, favor: bool, wanted: List[str]) -> Dict[str, bool]:
        """
        Goals achieved with `tid` losing (favor=False) or winning (favor=True)
        every coin flip, over every possible ordering of other teams' coin
        flips. Worst case needs a goal under every ordering; best case under any.
        """
        def run(flipper):
            p, d = determine_playoffs(
                sim_teams, h2h, sim_h2h,
                playoff_spots=playoff_spots,
                favor_id=tid if favor else None,
                disfavor_id=None if favor else tid,
                flipper=flipper
            )
            return _achieved(tid, p, d)

        result = {g: not favor for g in wanted}
        for achieved in all_coin_flip_outcomes(run, limit=COIN_FLIP_ORDERINGS_LIMIT):
            for g in wanted:
                result[g] = (result[g] or achieved[g]) if favor else (result[g] and achieved[g])
            # Stop once more orderings can't change anything
            if all(result[g] == favor for g in wanted):
                break
        return result

    def anything_open() -> bool:
        return any(
            always[g][tid] or never[g][tid] or always_if_win[g][tid] or never_if_loss[g][tid]
            for g in goals for tid in team_ids
        )

    for outcome_idx in range(total_outcomes):
        if progress_callback and outcome_idx % report_every == 0:
            progress_callback(outcome_idx / total_outcomes * 100)

        winners = [game_options[i][(outcome_idx >> i) & 1] for i in range(n_games)]

        # Only evaluate teams whose answers this outcome could still change.
        # Every flag only ever flips from True to False, so once a team is
        # neither clinched, eliminated, nor has a win/loss scenario, it's settled.
        pending = {}
        for tid in team_ids:
            game_idx = this_week_game.get(tid)
            won = game_idx is not None and winners[game_idx] == tid
            lost = game_idx is not None and not won
            worst_goals = [g for g in goals if always[g][tid] or (won and always_if_win[g][tid])]
            best_goals = [g for g in goals if never[g][tid] or (lost and never_if_loss[g][tid])]
            if worst_goals or best_goals:
                pending[tid] = (won, lost, worst_goals, best_goals)

        if not pending:
            if not anything_open():
                break  # Every answer is final
            continue

        sim_teams, sim_h2h = apply_outcome(teams, remaining, winners, h2h)

        flipper = CoinFlipper()
        playoff_teams, division_winners = determine_playoffs(
            sim_teams, h2h, sim_h2h, playoff_spots=playoff_spots, flipper=flipper
        )

        for tid, (won, lost, worst_goals, best_goals) in pending.items():
            if not flipper.flips:
                # No coin flips: standings are fully determined for everyone
                worst = best = _achieved(tid, playoff_teams, division_winners)
            else:
                worst = pinned_result(sim_teams, sim_h2h, tid, False, worst_goals) if worst_goals else {}
                best = pinned_result(sim_teams, sim_h2h, tid, True, best_goals) if best_goals else {}

            for g in worst_goals:
                if not worst[g]:
                    always[g][tid] = False
                    if won:
                        always_if_win[g][tid] = False
            for g in best_goals:
                if best[g]:
                    never[g][tid] = False
                    if lost:
                        never_if_loss[g][tid] = False

    # Extract scenarios
    clinch_scenarios = []
    elimination_scenarios = []

    for tid in team_ids:
        opponent_id = opponents.get(tid)
        if opponent_id is None:
            continue
        team = teams[tid]
        opponent = teams[opponent_id]

        for goal, label in GOAL_LABELS.items():
            if not always[goal][tid] and always_if_win[goal][tid]:
                clinch_scenarios.append(f"{team.name} clinches {label} with a WIN vs {opponent.name}")

        for goal, label in ELIMINATION_LABELS.items():
            if not never[goal][tid] and never_if_loss[goal][tid]:
                elimination_scenarios.append(f"{team.name} {label} if: LOSS to {opponent.name}")

    statuses = {
        tid: {
            **{f"clinched_{g}": always[g][tid] for g in goals},
            **{f"eliminated_{g}": never[g][tid] for g in goals},
        }
        for tid in team_ids
    }

    if progress_callback:
        progress_callback(100)

    return ScenarioReport(_dedupe(clinch_scenarios), _dedupe(elimination_scenarios), statuses)
