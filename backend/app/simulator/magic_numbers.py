"""
Magic number calculations for clinching and elimination scenarios.

Magic number = wins needed to clinch (or losses needed for last place).
Returns None if already clinched or eliminated, or if impossible to achieve.
"""

import math
from collections import defaultdict
from typing import Dict, List, Any, Optional

from .models import Team, Matchup, MagicNumbers, H2HDict
from .tiebreakers import get_h2h_record


PLAYOFF_SPOTS = 6


def calculate_magic_numbers(
    teams: Dict[int, Team],
    remaining: List[Matchup],
    h2h: H2HDict,
    playoff_spots: int = PLAYOFF_SPOTS
) -> Dict[int, MagicNumbers]:
    """
    Calculate magic numbers for each team.

    Magic number = wins needed to clinch (or losses needed for last place).
    Returns None if already clinched or eliminated, or if impossible to achieve.

    Uses effective wins (wins + 0.5 * ties) to properly account for ties.
    Accounts for direct matchups (rival can't win games against the team if team wins them).
    Accounts for H2H tiebreakers (team only needs to tie if they own the tiebreaker).

    Args:
        teams: Current team standings
        remaining: List of remaining matchups
        h2h: Historical head-to-head records
        playoff_spots: Number of playoff spots

    Returns:
        Dict mapping team_id -> MagicNumbers
    """
    # Count remaining games for each team
    games_remaining = defaultdict(int)
    # Count remaining games between specific pairs of teams
    games_between = defaultdict(lambda: defaultdict(int))

    for matchup in remaining:
        games_remaining[matchup.home_team_id] += 1
        games_remaining[matchup.away_team_id] += 1
        games_between[matchup.home_team_id][matchup.away_team_id] += 1
        games_between[matchup.away_team_id][matchup.home_team_id] += 1

    # Helper to get effective wins (accounting for ties)
    def effective_wins(team: Team) -> float:
        return team.wins + 0.5 * team.ties

    # Helper to check tiebreaker ownership: H2H -> division record -> uncertain
    def owns_tiebreaker(team1_id: int, team2_id: int) -> str:
        """
        Returns 'win' if team1 owns tiebreaker, 'lose' if team2 owns it,
        'uncertain' if it would go to coin flip.

        Checks full chain: H2H -> division record -> uncertain (coin flip).
        Conservative about future H2H games: if teams still play each other,
        the trailing team could catch up.
        """
        key = (min(team1_id, team2_id), max(team1_id, team2_id))
        record = h2h.get(key, (0, 0, 0))
        if team1_id < team2_id:
            t1_wins, t2_wins, _ = record
        else:
            t1_wins, t2_wins = record[1], record[0]

        remaining_h2h = games_between[team1_id][team2_id]

        # H2H check
        if remaining_h2h > 0:
            # Conservative: team2 could win all remaining
            t2_potential = t2_wins + remaining_h2h
            t1_potential = t1_wins + remaining_h2h
            if t1_wins > t2_potential:
                h2h_result = "win"
            elif t2_wins > t1_potential:
                h2h_result = "lose"
            else:
                h2h_result = "tied"
        else:
            if t1_wins > t2_wins:
                h2h_result = "win"
            elif t2_wins > t1_wins:
                h2h_result = "lose"
            else:
                h2h_result = "tied"

        if h2h_result != "tied":
            return h2h_result

        # Division record check
        team1 = teams[team1_id]
        team2 = teams[team2_id]
        if team1.division_win_pct > team2.division_win_pct:
            return "win"
        elif team2.division_win_pct > team1.division_win_pct:
            return "lose"

        # Coin flip - uncertain
        return "uncertain"

    # Group teams by division
    divisions = defaultdict(list)
    for team in teams.values():
        divisions[team.division_id].append(team)

    magic_numbers = {}

    for team in teams.values():
        team_remaining = games_remaining[team.id]
        team_eff_wins = effective_wins(team)

        # === Magic Number for Division ===
        div_rivals = [t for t in divisions[team.division_id] if t.id != team.id]
        if div_rivals:
            magic_div_conservative = 0
            magic_div_with_sub = 0

            for rival in div_rivals:
                games_vs_team = games_between[rival.id][team.id]

                # Conservative: rival wins all their games
                rival_max_full = effective_wins(rival) + games_remaining[rival.id]
                # With subtraction: rival loses games vs team
                rival_max_sub = rival_max_full - games_vs_team

                # Calculate wins needed for each approach
                if owns_tiebreaker(team.id, rival.id) == "win":
                    gap_full = rival_max_full - team_eff_wins
                    gap_sub = rival_max_sub - team_eff_wins
                    needed_cons = 0 if gap_full <= 0 else math.ceil(gap_full)
                    needed_sub = 0 if gap_sub <= 0 else math.ceil(gap_sub)
                else:
                    gap_full = rival_max_full - team_eff_wins
                    gap_sub = rival_max_sub - team_eff_wins
                    needed_cons = 0 if gap_full < 0 else math.ceil(gap_full + 0.001)
                    needed_sub = 0 if gap_sub < 0 else math.ceil(gap_sub + 0.001)

                magic_div_conservative = max(magic_div_conservative, needed_cons)
                magic_div_with_sub = max(magic_div_with_sub, needed_sub)

            # Determine final magic number
            if magic_div_conservative <= team_remaining:
                magic_div = magic_div_conservative
            elif magic_div_with_sub <= team_remaining:
                magic_div = team_remaining
            else:
                magic_div = None  # Impossible

            if magic_div == 0:
                magic_div = None  # Already clinched
        else:
            magic_div = None

        # === Magic Number for Playoffs (top N) ===
        other_teams = [t for t in teams.values() if t.id != team.id]

        # Calculate both conservative and with-subtraction for each team
        potential_conservative = []
        potential_with_sub = []
        for other in other_teams:
            games_vs_team = games_between[other.id][team.id]
            other_max_full = effective_wins(other) + games_remaining[other.id]
            other_max_sub = other_max_full - games_vs_team
            potential_conservative.append((other.id, other_max_full))
            potential_with_sub.append((other.id, other_max_sub))

        potential_conservative.sort(key=lambda x: x[1], reverse=True)
        potential_with_sub.sort(key=lambda x: x[1], reverse=True)

        if len(potential_conservative) >= playoff_spots:
            # Nth best using conservative (no subtraction)
            nth_cons_max = potential_conservative[playoff_spots - 1][1]
            nth_cons_id = potential_conservative[playoff_spots - 1][0]

            # Nth best using with-subtraction (team beats opponents)
            nth_sub_max = potential_with_sub[playoff_spots - 1][1]
            nth_sub_id = potential_with_sub[playoff_spots - 1][0]

            # Conservative calculation
            if owns_tiebreaker(team.id, nth_cons_id) == "win":
                gap_cons = nth_cons_max - team_eff_wins
                needed_cons = 0 if gap_cons <= 0 else math.ceil(gap_cons)
            else:
                gap_cons = nth_cons_max - team_eff_wins
                needed_cons = 0 if gap_cons < 0 else math.ceil(gap_cons + 0.001)

            # With-subtraction calculation
            if owns_tiebreaker(team.id, nth_sub_id) == "win":
                gap_sub = nth_sub_max - team_eff_wins
                needed_sub = 0 if gap_sub <= 0 else math.ceil(gap_sub)
            else:
                gap_sub = nth_sub_max - team_eff_wins
                needed_sub = 0 if gap_sub < 0 else math.ceil(gap_sub + 0.001)

            # Determine final magic number
            if needed_cons <= team_remaining:
                magic_playoff = needed_cons
            elif needed_sub <= team_remaining:
                magic_playoff = team_remaining  # Must win all
            else:
                magic_playoff = None  # Impossible

            if magic_playoff == 0:
                magic_playoff = None  # Already clinched
        else:
            magic_playoff = None  # Fewer than playoff_spots + 1 teams total

        # === Magic Number for #1 Seed ===
        if other_teams:
            magic_first_conservative = 0
            magic_first_with_sub = 0

            for other in other_teams:
                games_vs_team = games_between[other.id][team.id]
                other_max_full = effective_wins(other) + games_remaining[other.id]
                other_max_sub = other_max_full - games_vs_team

                if owns_tiebreaker(team.id, other.id) == "win":
                    gap_full = other_max_full - team_eff_wins
                    gap_sub = other_max_sub - team_eff_wins
                    needed_cons = 0 if gap_full <= 0 else math.ceil(gap_full)
                    needed_sub = 0 if gap_sub <= 0 else math.ceil(gap_sub)
                else:
                    gap_full = other_max_full - team_eff_wins
                    gap_sub = other_max_sub - team_eff_wins
                    needed_cons = 0 if gap_full < 0 else math.ceil(gap_full + 0.001)
                    needed_sub = 0 if gap_sub < 0 else math.ceil(gap_sub + 0.001)

                magic_first_conservative = max(magic_first_conservative, needed_cons)
                magic_first_with_sub = max(magic_first_with_sub, needed_sub)

            # Determine final magic number
            if magic_first_conservative <= team_remaining:
                magic_first = magic_first_conservative
            elif magic_first_with_sub <= team_remaining:
                magic_first = team_remaining
            else:
                magic_first = None  # Impossible

            if magic_first == 0:
                magic_first = None  # Already clinched
        else:
            magic_first = None

        # === Magic Number for Last Place (losses needed) ===
        if other_teams:
            min_other_eff_wins = min(effective_wins(t) for t in other_teams)
            gap = team_eff_wins + team_remaining - min_other_eff_wins
            if gap < 0:
                magic_last = None  # Already clinched last
            else:
                magic_last = math.ceil(gap + 0.001)
                if magic_last > team_remaining:
                    magic_last = None  # Impossible to get last
        else:
            magic_last = None

        magic_numbers[team.id] = MagicNumbers(
            team_id=team.id,
            magic_division=magic_div,
            magic_playoffs=magic_playoff,
            magic_first_seed=magic_first,
            magic_last=magic_last
        )

    return magic_numbers
