"""
Tiebreaker resolution logic for ESPN fantasy leagues.

ESPN tiebreaker order:
1. Head-to-head record among tied teams (only if all pairs played equal games)
1b. Pairwise H2H elimination (teams that lost to ALL others are ranked last)
2. Division record (intradivisional win%)
3. Coin flip (random)
"""

import itertools
import random
from typing import Callable, Dict, Iterator, List, Tuple, Optional, TypeVar

from .models import Team, H2HDict


class CoinFlipper:
    """Orders teams still tied after every tiebreaker, and counts the flips."""

    def __init__(self):
        self.flips = 0

    def order(self, teams: List[Team]) -> List[Team]:
        self.flips += 1
        shuffled = list(teams)
        random.shuffle(shuffled)
        return shuffled


class ScriptedFlipper(CoinFlipper):
    """
    Plays back a fixed sequence of coin-flip choices (indexes into each tied
    group's permutations), recording how many choices each flip had, so every
    possible ordering can be enumerated. See all_coin_flip_outcomes().
    """

    def __init__(self, script: List[int]):
        super().__init__()
        self.script = script
        self.branching: List[int] = []

    def order(self, teams: List[Team]) -> List[Team]:
        perms = list(itertools.permutations(teams))
        choice = self.script[self.flips] if self.flips < len(self.script) else 0
        self.branching.append(len(perms))
        self.flips += 1
        return list(perms[choice])


T = TypeVar("T")


def all_coin_flip_outcomes(
    run: Callable[[CoinFlipper], T], limit: int = 720
) -> Iterator[T]:
    """
    Yield run(flipper) once for every distinct sequence of coin-flip orderings.

    Which flips happen can depend on earlier flips, so this walks the decision
    tree depth-first, like an odometer whose wheel sizes are discovered as it
    goes. Stops after `limit` runs (only reachable with huge multi-way ties).
    """
    script: List[int] = []
    for _ in range(limit):
        flipper = ScriptedFlipper(script)
        yield run(flipper)

        # Advance to the next unexplored path
        path = script[:len(flipper.branching)]
        path += [0] * (len(flipper.branching) - len(path))
        i = len(path) - 1
        while i >= 0 and path[i] + 1 >= flipper.branching[i]:
            i -= 1
        if i < 0:
            return
        script = path[:i] + [path[i] + 1]


def get_h2h_record(h2h: H2HDict, team1_id: int, team2_id: int) -> Tuple[int, int, int]:
    """Get head-to-head record for team1 vs team2."""
    key = (min(team1_id, team2_id), max(team1_id, team2_id))
    record = h2h.get(key, (0, 0, 0))

    if team1_id < team2_id:
        return record
    else:
        return (record[1], record[0], record[2])


class H2HTable:
    """
    Historical + simulated H2H lookups for one set of standings.

    Records are combined on first use and memoized, so repeated tiebreakers
    over the same standings don't redo the work.
    """

    __slots__ = ("_h2h", "_sim_h2h", "_cache")

    def __init__(self, h2h: H2HDict, sim_h2h: H2HDict):
        self._h2h = h2h
        self._sim_h2h = sim_h2h
        self._cache: Dict[Tuple[int, int], Tuple[int, int, int]] = {}

    def record(self, team1_id: int, team2_id: int) -> Tuple[int, int, int]:
        """Combined (team1_wins, team2_wins, ties) for team1 vs team2."""
        key = (team1_id, team2_id)
        rec = self._cache.get(key)
        if rec is None:
            hist = get_h2h_record(self._h2h, team1_id, team2_id)
            sim = get_h2h_record(self._sim_h2h, team1_id, team2_id)
            rec = (hist[0] + sim[0], hist[1] + sim[1], hist[2] + sim[2])
            self._cache[key] = rec
        return rec


def resolve_tiebreaker(
    tied_teams: List[Team],
    h2h: H2HDict,
    sim_h2h: H2HDict,
    disfavor_id: Optional[int] = None,
    favor_id: Optional[int] = None,
    flipper: Optional[CoinFlipper] = None,
    table: Optional[H2HTable] = None
) -> List[Team]:
    """
    Resolve tiebreaker between teams with identical records.

    ESPN tiebreaker order:
    1. Head-to-head record among tied teams (only if all pairs played equal games)
    2. Division record (intradivisional win%)
    3. Coin flip (random) - disfavor_id always loses, favor_id always wins

    Multi-team ties: after seating one team via H2H, restart from H2H for remaining group.

    Args:
        tied_teams: List of teams tied on win percentage
        h2h: Historical head-to-head records
        sim_h2h: Simulated head-to-head records from this simulation
        disfavor_id: Team that always loses coin flips (worst case for clinch check)
        favor_id: Team that always wins coin flips (best case for elimination check)
        flipper: Orders groups that are still tied (default: random shuffle).
            Only called when 2+ teams aren't pinned by favor/disfavor, so
            flipper.flips == 0 afterwards means the result was deterministic.
        table: Optional shared H2HTable for h2h + sim_h2h (saves recombining
            records across several tiebreakers on the same standings)

    Returns:
        Teams in ranked order after tiebreaker resolution
    """
    if len(tied_teams) <= 1:
        return list(tied_teams)

    if table is None:
        table = H2HTable(h2h, sim_h2h)

    def record(t1: Team, t2: Team) -> Tuple[int, int, int]:
        return table.record(t1.id, t2.id)

    def _compute_h2h_pcts(group: List[Team]) -> Optional[Dict[int, float]]:
        """Compute H2H win% for each team in the group. Returns None if games are unequal."""
        # First check equal-games-played: all pairs must have played the same total games
        pair_totals = set()
        for i, t1 in enumerate(group):
            for t2 in group[i+1:]:
                pair_totals.add(sum(record(t1, t2)))

        # If any pair has a different total, H2H is invalid
        if len(pair_totals) > 1:
            return None

        h2h_pcts = {}
        for team in group:
            wins = 0
            losses = 0
            ties = 0
            for other in group:
                if team.id != other.id:
                    w, l, t = record(team, other)
                    wins += w
                    losses += l
                    ties += t

            total = wins + losses + ties
            if total > 0:
                h2h_pcts[team.id] = (wins + 0.5 * ties) / total
            else:
                h2h_pcts[team.id] = 0.5

        return h2h_pcts

    def _coin_flip(group: List[Team]) -> List[Team]:
        """Order a still-tied group randomly, respecting disfavor/favor."""
        pinned_first = [t for t in group if t.id == favor_id]
        pinned_last = [t for t in group if t.id == disfavor_id and t.id != favor_id]
        free = [t for t in group if t.id != favor_id and t.id != disfavor_id]
        if len(free) > 1:
            if flipper is None:
                random.shuffle(free)
            else:
                free = flipper.order(free)
        return pinned_first + free + pinned_last

    def _resolve(group: List[Team]) -> List[Team]:
        if len(group) <= 1:
            return list(group)

        # Iterative seat-one-at-a-time approach
        remaining = list(group)
        seated: List[Team] = []

        while len(remaining) > 1:
            # Step 1: Try H2H among remaining group
            h2h_pcts = _compute_h2h_pcts(remaining)

            if h2h_pcts is not None:
                best_pct = max(h2h_pcts.values())
                best_teams = [t for t in remaining if h2h_pcts[t.id] == best_pct]

                if len(best_teams) == 1:
                    # One team clearly wins H2H - seat them and restart
                    seated.append(best_teams[0])
                    remaining = [t for t in remaining if t.id != best_teams[0].id]
                    continue
                if len(best_teams) < len(remaining):
                    # H2H separated some but not all - resolve subgroups
                    best_ids = {bt.id for bt in best_teams}
                    rest = [t for t in remaining if t.id not in best_ids]
                    return seated + _resolve(best_teams) + _resolve(rest)

            # Step 1b: Pairwise H2H elimination
            # Even if full H2H is invalid, eliminate teams that lost to ALL others
            teams_lost_to_all = []
            for team in remaining:
                lost_to_all = True
                for other in remaining:
                    if team.id == other.id:
                        continue
                    w, l, _ = record(team, other)
                    # If wins >= losses against any opponent, they didn't lose to all
                    if w >= l:
                        lost_to_all = False
                        break
                if lost_to_all:
                    teams_lost_to_all.append(team)

            # If some teams lost to all others, rank them last
            if teams_lost_to_all and len(teams_lost_to_all) < len(remaining):
                loser_ids = {t.id for t in teams_lost_to_all}
                winners = [t for t in remaining if t.id not in loser_ids]
                return seated + _resolve(winners) + _resolve(teams_lost_to_all)

            # Step 2: Try division record
            div_pcts = {t.id: t.division_win_pct for t in remaining}
            best_div = max(div_pcts.values())
            best_div_teams = [t for t in remaining if div_pcts[t.id] == best_div]

            if len(best_div_teams) == 1:
                seated.append(best_div_teams[0])
                remaining = [t for t in remaining if t.id != best_div_teams[0].id]
            elif len(best_div_teams) < len(remaining):
                # Division record separated some - resolve subgroups
                best_ids = {bt.id for bt in best_div_teams}
                rest = [t for t in remaining if t.id not in best_ids]
                return seated + _resolve(best_div_teams) + _resolve(rest)
            else:
                # Step 3: Coin flip - all still tied
                return seated + _coin_flip(remaining)

        # Last remaining team
        return seated + remaining

    return _resolve(list(tied_teams))
