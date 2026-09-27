"""
Magic number calculations for clinching and elimination scenarios.

Magic number = wins needed to clinch regardless of other results (or losses
needed for last place). It is None when the goal is already clinched, already
lost, or cannot be guaranteed by the team's own results alone; the clinched_*
and eliminated_* flags on MagicNumbers tell those cases apart.

Playoff math is division-aware: division winners qualify regardless of record,
so only (playoff_spots - number of divisions) spots are open to everyone else.
"""

import math
from collections import defaultdict
from typing import Dict, List, Optional

from .models import Team, Matchup, MagicNumbers, H2HDict
from .tiebreakers import get_h2h_record


PLAYOFF_SPOTS = 6


class LeagueMath:
    """
    Clinch/elimination bookkeeping shared by magic numbers and scenarios.

    All win counts are in "units": one unit per matchup for points and
    most-categories leagues, one unit per category for each-category leagues.
    """

    def __init__(
        self,
        teams: Dict[int, Team],
        remaining: List[Matchup],
        h2h: H2HDict,
        playoff_spots: int = PLAYOFF_SPOTS,
        units_per_game: int = 1
    ):
        self.teams = teams
        self.h2h = h2h
        self.units = max(1, int(units_per_game))
        self.playoff_spots = playoff_spots

        self.games_remaining: Dict[int, int] = defaultdict(int)
        self.division_games_remaining: Dict[int, int] = defaultdict(int)
        self.games_between: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        for m in remaining:
            self.games_remaining[m.home_team_id] += 1
            self.games_remaining[m.away_team_id] += 1
            self.games_between[m.home_team_id][m.away_team_id] += 1
            self.games_between[m.away_team_id][m.home_team_id] += 1
            if m.is_division_game:
                self.division_games_remaining[m.home_team_id] += 1
                self.division_games_remaining[m.away_team_id] += 1

        self.num_divisions = len({t.division_id for t in teams.values()})
        # Spots left once every division winner has taken one
        self.wildcard_spots = playoff_spots - self.num_divisions

    # ----- basic quantities -------------------------------------------------

    @staticmethod
    def eff(team: Team) -> float:
        """Effective wins (ties count half)."""
        return team.wins + 0.5 * team.ties

    def max_gain(self, team_id: int) -> int:
        """Most units a team can still add."""
        return self.games_remaining[team_id] * self.units

    def others(self, team: Team) -> List[Team]:
        return [t for t in self.teams.values() if t.id != team.id]

    def tiebreak(self, team1: Team, team2: Team) -> str:
        """
        'win' if team1 is certain to own the tiebreaker over team2, 'lose' if
        team2 is certain to own it, 'uncertain' otherwise.

        Checks H2H (allowing for H2H games still to be played), then division
        record (only once neither team has division games left).
        """
        t1_wins, t2_wins, _ = get_h2h_record(self.h2h, team1.id, team2.id)
        remaining_h2h = self.games_between[team1.id][team2.id] * self.units

        if t1_wins > t2_wins + remaining_h2h:
            return "win"
        if t2_wins > t1_wins + remaining_h2h:
            return "lose"
        if remaining_h2h > 0:
            # H2H could still go either way
            return "uncertain"

        if self.division_games_remaining[team1.id] or self.division_games_remaining[team2.id]:
            return "uncertain"
        if team1.division_win_pct > team2.division_win_pct:
            return "win"
        if team2.division_win_pct > team1.division_win_pct:
            return "lose"

        # Coin flip
        return "uncertain"

    # ----- clinching (worst case) -------------------------------------------

    def can_finish_ahead(
        self,
        team: Team,
        team_final: float,
        adjustments: Optional[Dict[int, float]] = None
    ) -> List[Team]:
        """
        Teams that could still finish ahead of `team` if it ends on team_final.

        Every other team is assumed to win all its remaining games, minus any
        per-team `adjustments` (games we know it loses, e.g. to `team`).
        """
        adjustments = adjustments or {}
        ahead = []
        for other in self.others(team):
            other_max = self.eff(other) + self.max_gain(other.id) - adjustments.get(other.id, 0)
            if other_max > team_final or (
                other_max == team_final and self.tiebreak(team, other) != "win"
            ):
                ahead.append(other)
        return ahead

    def clinched_given(self, team: Team, ahead: List[Team], goal: str) -> bool:
        """Is `goal` guaranteed if only the teams in `ahead` can pass `team`?"""
        if goal == "first_seed":
            return not ahead

        division_rival_ahead = any(t.division_id == team.division_id for t in ahead)
        if goal == "division":
            return not division_rival_ahead

        # Playoffs: a division title is enough on its own
        if not division_rival_ahead:
            return True
        if self.wildcard_spots <= 0:
            return False
        # Worst case every team in `ahead` passes us. Each division among them
        # produces one division winner; the rest compete with us for wildcards.
        non_winners_ahead = len(ahead) - len({t.division_id for t in ahead})
        return non_winners_ahead < self.wildcard_spots

    def magic_number(self, team: Team, goal: str) -> Optional[int]:
        """
        Fewest additional units that guarantee `goal` whatever else happens.
        0 means already clinched; None means it can't be guaranteed alone.
        """
        max_gain = self.max_gain(team.id)
        for gained in range(max_gain + 1):
            # Winning out also means every remaining opponent loses to us
            adjustments = None
            if gained == max_gain:
                adjustments = {
                    other_id: count * self.units
                    for other_id, count in self.games_between[team.id].items()
                }
            ahead = self.can_finish_ahead(team, self.eff(team) + gained, adjustments)
            if self.clinched_given(team, ahead, goal):
                return gained
        return None

    # ----- elimination (best case) ------------------------------------------

    def certainly_ahead(
        self,
        team: Team,
        team_best: float,
        bonuses: Optional[Dict[int, float]] = None
    ) -> List[Team]:
        """
        Teams guaranteed to finish strictly ahead of `team` even if it ends on
        team_best. Other teams are assumed to lose every remaining game except
        known `bonuses` (e.g. a win over `team`). Ties never count, since a
        multi-team tiebreaker could still go our way.
        """
        bonuses = bonuses or {}
        return [
            other for other in self.others(team)
            if self.eff(other) + bonuses.get(other.id, 0) > team_best
        ]

    def eliminated_given(self, team: Team, ahead: List[Team], goal: str) -> bool:
        """Is `goal` impossible if every team in `ahead` finishes above `team`?"""
        if goal == "first_seed":
            return bool(ahead)

        division_rival_ahead = any(t.division_id == team.division_id for t in ahead)
        if goal == "division":
            return division_rival_ahead

        if not division_rival_ahead:
            return False
        if self.wildcard_spots <= 0:
            return True
        # At most one team per division among `ahead` can be a division winner
        non_winners_ahead = len(ahead) - len({t.division_id for t in ahead})
        return non_winners_ahead >= self.wildcard_spots

    def eliminated(self, team: Team, goal: str) -> bool:
        best = self.eff(team) + self.max_gain(team.id)
        return self.eliminated_given(team, self.certainly_ahead(team, best), goal)


def calculate_magic_numbers(
    teams: Dict[int, Team],
    remaining: List[Matchup],
    h2h: H2HDict,
    playoff_spots: int = PLAYOFF_SPOTS,
    categories_per_matchup: int = 1
) -> Dict[int, MagicNumbers]:
    """
    Calculate magic numbers for each team.

    Magic number = wins needed to clinch (or losses needed for last place).
    Returns None if already clinched or eliminated, or if impossible to achieve.

    Uses effective wins (wins + 0.5 * ties) to properly account for ties.
    Accounts for direct matchups (rival can't win games against the team if team wins them).
    Accounts for H2H tiebreakers (team only needs to tie if they own the tiebreaker).
    Accounts for division winners' guaranteed playoff spots.

    Args:
        teams: Current team standings
        remaining: List of remaining matchups
        h2h: Historical head-to-head records
        playoff_spots: Number of playoff spots
        categories_per_matchup: Units per matchup (see simulate_season)

    Returns:
        Dict mapping team_id -> MagicNumbers
    """
    math_ = LeagueMath(teams, remaining, h2h, playoff_spots, categories_per_matchup)
    magic_numbers = {}

    for team in teams.values():
        result = MagicNumbers(team_id=team.id)

        for goal in ("division", "playoffs", "first_seed"):
            needed = math_.magic_number(team, goal)
            if needed == 0:
                setattr(result, f"clinched_{goal}", True)
            else:
                setattr(result, f"magic_{goal}", needed)
                if math_.eliminated(team, goal):
                    setattr(result, f"eliminated_{goal}", True)

        # === Magic Number for Last Place (losses needed) ===
        others = math_.others(team)
        if others:
            team_remaining = math_.max_gain(team.id)
            min_other_eff_wins = min(math_.eff(t) for t in others)
            gap = math_.eff(team) + team_remaining - min_other_eff_wins
            if gap >= 0:
                magic_last = math.ceil(gap + 0.001)
                if magic_last <= team_remaining:
                    result.magic_last = magic_last

        magic_numbers[team.id] = result

    return magic_numbers
