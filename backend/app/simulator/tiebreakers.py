"""
Tiebreaker resolution logic for ESPN fantasy leagues.

ESPN tiebreaker order:
1. Head-to-head record among tied teams (only if all pairs played equal games)
1b. Pairwise H2H elimination (teams that lost to ALL others are ranked last)
2. Division record (intradivisional win%)
3. Coin flip (random)
"""

import random
from typing import Dict, List, Tuple, Optional

from .models import Team, H2HDict


def get_h2h_record(h2h: H2HDict, team1_id: int, team2_id: int) -> Tuple[int, int, int]:
    """Get head-to-head record for team1 vs team2."""
    key = (min(team1_id, team2_id), max(team1_id, team2_id))
    record = h2h.get(key, (0, 0, 0))

    if team1_id < team2_id:
        return record
    else:
        return (record[1], record[0], record[2])


def resolve_tiebreaker(
    tied_teams: List[Team],
    h2h: H2HDict,
    sim_h2h: H2HDict,
    disfavor_id: Optional[int] = None,
    favor_id: Optional[int] = None
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

    Returns:
        Teams in ranked order after tiebreaker resolution
    """
    if len(tied_teams) <= 1:
        return tied_teams

    # Combine historical H2H with simulated H2H
    combined_h2h = {}
    for key in set(h2h.keys()) | set(sim_h2h.keys()):
        hist = h2h.get(key, (0, 0, 0))
        sim = sim_h2h.get(key, (0, 0, 0))
        combined_h2h[key] = (hist[0] + sim[0], hist[1] + sim[1], hist[2] + sim[2])

    def _compute_h2h_pcts(group: List[Team]) -> Optional[Dict[int, float]]:
        """Compute H2H win% for each team in the group. Returns None if games are unequal."""
        # First check equal-games-played: all pairs must have played the same total games
        pair_totals = []
        for i, t1 in enumerate(group):
            for t2 in group[i+1:]:
                record = get_h2h_record(combined_h2h, t1.id, t2.id)
                pair_totals.append(sum(record))

        # If any pair has a different total, H2H is invalid
        if pair_totals and len(set(pair_totals)) > 1:
            return None

        h2h_pcts = {}
        for team in group:
            wins = 0
            losses = 0
            ties = 0
            for other in group:
                if team.id != other.id:
                    record = get_h2h_record(combined_h2h, team.id, other.id)
                    wins += record[0]
                    losses += record[1]
                    ties += record[2]

            total = wins + losses + ties
            if total > 0:
                h2h_pcts[team.id] = (wins + 0.5 * ties) / total
            else:
                h2h_pcts[team.id] = 0.5

        return h2h_pcts

    def _coin_flip_key(team: Team) -> float:
        """Generate coin flip sort key respecting disfavor/favor."""
        if team.id == disfavor_id:
            return 1.0  # Sorts last (worst)
        elif team.id == favor_id:
            return -1.0  # Sorts first (best)
        else:
            return random.random() * 0.0001

    # Iterative seat-one-at-a-time approach
    remaining = list(tied_teams)
    seated = []

    while len(remaining) > 1:
        # Step 1: Try H2H among remaining group
        h2h_pcts = _compute_h2h_pcts(remaining)
        seated_one = False

        if h2h_pcts is not None:
            # Check if any team is clearly best by H2H
            best_pct = max(h2h_pcts.values())
            best_teams = [t for t in remaining if h2h_pcts[t.id] == best_pct]

            if len(best_teams) == 1:
                # One team clearly wins H2H - seat them and restart
                seated.append(best_teams[0])
                remaining = [t for t in remaining if t.id != best_teams[0].id]
                seated_one = True
            elif len(best_teams) < len(remaining):
                # H2H separated some but not all - resolve subgroups
                best_resolved = resolve_tiebreaker(
                    best_teams, h2h, sim_h2h,
                    disfavor_id=disfavor_id, favor_id=favor_id
                )
                rest = [t for t in remaining if t.id not in {bt.id for bt in best_teams}]
                rest_resolved = resolve_tiebreaker(
                    rest, h2h, sim_h2h,
                    disfavor_id=disfavor_id, favor_id=favor_id
                )
                seated.extend(best_resolved)
                seated.extend(rest_resolved)
                return seated

        if not seated_one:
            # Step 1b: Pairwise H2H elimination
            # Even if full H2H is invalid, eliminate teams that lost to ALL others
            teams_lost_to_all = []
            for team in remaining:
                lost_to_all = True
                for other in remaining:
                    if team.id == other.id:
                        continue
                    record = get_h2h_record(combined_h2h, team.id, other.id)
                    # If wins >= losses against any opponent, they didn't lose to all
                    if record[0] >= record[1]:
                        lost_to_all = False
                        break
                if lost_to_all:
                    teams_lost_to_all.append(team)

            # If some teams lost to all others, rank them last
            if teams_lost_to_all and len(teams_lost_to_all) < len(remaining):
                winners = [t for t in remaining if t not in teams_lost_to_all]
                winners_resolved = resolve_tiebreaker(
                    winners, h2h, sim_h2h,
                    disfavor_id=disfavor_id, favor_id=favor_id
                )
                losers_resolved = resolve_tiebreaker(
                    teams_lost_to_all, h2h, sim_h2h,
                    disfavor_id=disfavor_id, favor_id=favor_id
                )
                seated.extend(winners_resolved)
                seated.extend(losers_resolved)
                return seated

            # Step 2: Try division record
            div_pcts = {t.id: t.division_win_pct for t in remaining}
            best_div = max(div_pcts.values())
            best_div_teams = [t for t in remaining if div_pcts[t.id] == best_div]

            if len(best_div_teams) == 1:
                seated.append(best_div_teams[0])
                remaining = [t for t in remaining if t.id != best_div_teams[0].id]
            elif len(best_div_teams) < len(remaining):
                # Division record separated some - resolve subgroups
                best_resolved = resolve_tiebreaker(
                    best_div_teams, h2h, sim_h2h,
                    disfavor_id=disfavor_id, favor_id=favor_id
                )
                rest = [t for t in remaining if t.id not in {bt.id for bt in best_div_teams}]
                rest_resolved = resolve_tiebreaker(
                    rest, h2h, sim_h2h,
                    disfavor_id=disfavor_id, favor_id=favor_id
                )
                seated.extend(best_resolved)
                seated.extend(rest_resolved)
                return seated
            else:
                # Step 3: Coin flip - all still tied
                remaining.sort(key=_coin_flip_key)
                seated.extend(remaining)
                return seated

    # Last remaining team
    if remaining:
        seated.append(remaining[0])

    return seated
