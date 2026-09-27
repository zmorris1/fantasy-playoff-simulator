"""
Tests for the simulation core: tiebreakers, playoff determination, Monte Carlo
engine, magic numbers, and clinch/elimination scenarios.
"""

import random
import re

import pytest

from app.simulator.tiebreakers import CoinFlipper, all_coin_flip_outcomes
from app.simulator import (
    Team,
    Matchup,
    resolve_tiebreaker,
    determine_playoffs,
    simulate_season,
    calculate_magic_numbers,
    generate_clinch_elimination_scenarios,
    brute_force_clinch_elimination,
    scenario_week,
)


def make_teams(records, divisions=None):
    """records: {id: (wins, losses)}; divisions: {id: division_id} (default all 0)."""
    divisions = divisions or {}
    return {
        tid: Team(id=tid, name=f"T{tid}", division_id=divisions.get(tid, 0), wins=w, losses=l)
        for tid, (w, l) in records.items()
    }


@pytest.fixture(autouse=True)
def seeded_random():
    random.seed(12345)


class TestTiebreakers:

    def test_h2h_decides_two_team_tie(self):
        teams = make_teams({1: (5, 5), 2: (5, 5)})
        h2h = {(1, 2): (0, 2, 0)}  # team 2 beat team 1 twice
        order = resolve_tiebreaker([teams[1], teams[2]], h2h, {})
        assert [t.id for t in order] == [2, 1]

    def test_historical_and_simulated_h2h_are_combined(self):
        teams = make_teams({1: (5, 5), 2: (5, 5)})
        h2h = {(1, 2): (1, 0, 0)}
        sim_h2h = {(1, 2): (0, 2, 0)}  # 1-2 overall for team 1
        order = resolve_tiebreaker([teams[1], teams[2]], h2h, sim_h2h)
        assert [t.id for t in order] == [2, 1]

    def test_division_record_breaks_h2h_split(self):
        teams = make_teams({1: (5, 5), 2: (5, 5)})
        teams[1].division_wins, teams[1].division_losses = 2, 2
        teams[2].division_wins, teams[2].division_losses = 3, 1
        h2h = {(1, 2): (1, 1, 0)}
        order = resolve_tiebreaker([teams[1], teams[2]], h2h, {})
        assert [t.id for t in order] == [2, 1]

    def test_team_that_lost_to_all_is_ranked_last_with_unequal_games(self):
        teams = make_teams({1: (5, 5), 2: (5, 5), 3: (5, 5)})
        # Unequal games played between pairs -> full H2H invalid
        h2h = {(1, 2): (1, 0, 0), (1, 3): (1, 0, 0), (2, 3): (2, 0, 0)}
        order = resolve_tiebreaker([teams[1], teams[2], teams[3]], h2h, {})
        assert order[-1].id == 3

    def test_coin_flip_respects_favor_and_disfavor_and_is_counted(self):
        teams = make_teams({1: (5, 5), 2: (5, 5), 3: (5, 5), 4: (5, 5)})
        group = list(teams.values())

        flipper = CoinFlipper()
        order = resolve_tiebreaker(group, {}, {}, disfavor_id=1, flipper=flipper)
        assert order[-1].id == 1
        assert flipper.flips == 1  # teams 2-4 were ordered randomly

        order = resolve_tiebreaker(group, {}, {}, favor_id=3)
        assert order[0].id == 3

    def test_two_team_coin_flip_with_one_pinned_is_not_random(self):
        teams = make_teams({1: (5, 5), 2: (5, 5)})
        flipper = CoinFlipper()
        order = resolve_tiebreaker([teams[1], teams[2]], {}, {}, disfavor_id=2, flipper=flipper)
        assert [t.id for t in order] == [1, 2]
        assert flipper.flips == 0

    def test_all_coin_flip_outcomes_enumerates_every_ordering_once(self):
        teams = make_teams({1: (5, 5), 2: (5, 5), 3: (5, 5)})
        group = list(teams.values())

        def run(flipper):
            return tuple(t.id for t in resolve_tiebreaker(group, {}, {}, flipper=flipper))

        orders = list(all_coin_flip_outcomes(run))
        assert len(orders) == 6
        assert len(set(orders)) == 6

    def test_all_coin_flip_outcomes_handles_several_flips(self):
        # A 2-way flip in each division, then the two division winners flip
        # for the #1 seed: 2 x 2 x 2 = 8 paths
        teams = make_teams(
            {1: (5, 5), 2: (5, 5), 3: (5, 5), 4: (5, 5)},
            {1: 0, 2: 0, 3: 1, 4: 1},
        )

        def run(flipper):
            return tuple(determine_playoffs(teams, {}, {}, playoff_spots=2, flipper=flipper)[0])

        seedings = list(all_coin_flip_outcomes(run))
        assert len(seedings) == 8
        assert len(set(seedings)) == 8
        assert {frozenset(s) for s in seedings} == {
            frozenset(p) for p in [(1, 3), (1, 4), (2, 3), (2, 4)]
        }


class TestDeterminePlayoffs:

    def test_division_winner_qualifies_over_better_record(self):
        # Division 0 is strong, division 1 is weak; 2 spots
        teams = make_teams(
            {1: (9, 1), 2: (8, 2), 3: (3, 7), 4: (2, 8)},
            {1: 0, 2: 0, 3: 1, 4: 1},
        )
        playoffs, winners = determine_playoffs(teams, {}, {}, playoff_spots=2)
        assert set(winners) == {1, 3}
        assert set(playoffs) == {1, 3}
        assert playoffs[0] == 1  # best record is the #1 seed

    def test_wildcard_tie_broken_by_h2h(self):
        teams = make_teams({1: (8, 2), 2: (6, 4), 3: (6, 4), 4: (1, 9)})
        h2h = {(2, 3): (0, 1, 0)}
        playoffs, _ = determine_playoffs(teams, h2h, {}, playoff_spots=2)
        assert set(playoffs) == {1, 3}


class TestSimulateSeason:

    def test_no_remaining_games_is_deterministic(self):
        teams = make_teams({1: (9, 1), 2: (6, 4), 3: (4, 6), 4: (1, 9)})
        results = simulate_season(teams, [], {}, n_simulations=200, playoff_spots=2)
        assert results[1].playoff_appearances == 200
        assert results[2].playoff_appearances == 200
        assert results[3].playoff_appearances == 0
        assert results[1].first_seed == 200
        assert results[4].last_place == 200

    def test_counts_are_consistent(self):
        teams = make_teams(
            {i: (5, 5) for i in range(1, 9)},
            {i: (0 if i <= 4 else 1) for i in range(1, 9)},
        )
        remaining = [Matchup(1, 5, 11, False), Matchup(2, 6, 11, False),
                     Matchup(3, 4, 11, True), Matchup(7, 8, 11, True)]
        n = 500
        results = simulate_season(teams, remaining, {}, n_simulations=n, playoff_spots=4)
        assert sum(r.playoff_appearances for r in results.values()) == 4 * n
        assert sum(r.division_wins for r in results.values()) == 2 * n
        assert sum(r.first_seed for r in results.values()) == n
        assert sum(r.last_place for r in results.values()) == n

    def test_each_category_mode_distributes_all_categories(self, monkeypatch):
        teams = make_teams({1: (40, 32), 2: (36, 36)})
        remaining = [Matchup(1, 2, 9, True), Matchup(2, 1, 10, True)]
        seen = []

        # Capture the simulated standings via determine_playoffs
        import app.simulator.engine as engine
        real = engine.determine_playoffs

        def spy(sim_teams, *args, **kwargs):
            seen.append({tid: (t.wins, t.losses) for tid, t in sim_teams.items()})
            return real(sim_teams, *args, **kwargs)

        monkeypatch.setattr(engine, "determine_playoffs", spy)
        simulate_season(teams, remaining, {}, n_simulations=50, playoff_spots=1,
                        categories_per_matchup=9)

        for standings in seen:
            # Two matchups x 9 categories = 18 decisions per team
            assert sum(standings[1]) == 72 + 18
            assert sum(standings[2]) == 72 + 18
            assert standings[1][0] + standings[2][0] == 40 + 36 + 18
        # Categories really are split, not awarded as a block
        assert any(s[1][0] - 40 not in (0, 9, 18) for s in seen)


class TestMagicNumbers:

    def test_simple_magic_number_without_divisions(self):
        # 3 teams, 1 spot, 3 games left each (round robin-ish)
        teams = make_teams({1: (8, 2), 2: (6, 4), 3: (5, 5)})
        remaining = [Matchup(1, 3, 11, True), Matchup(2, 3, 12, True), Matchup(1, 2, 13, True)]
        magic = calculate_magic_numbers(teams, remaining, {}, playoff_spots=1)
        # Team 2 can reach 8 wins. Team 1 needs a 9th win to stay ahead,
        # and ties with team 2 aren't certain to go its way -> 1 more win.
        assert magic[1].magic_playoffs == 1
        assert not magic[1].clinched_playoffs

    def test_no_false_clinch_when_division_winner_takes_a_spot(self):
        # 3 spots, 2 divisions -> only 1 wildcard. Teams 2 and 3 (same
        # division as team 1) are both guaranteed to finish ahead of team 1,
        # and division B's winner takes a spot regardless of record.
        teams = make_teams(
            {1: (7, 2), 2: (9, 0), 3: (9, 0), 4: (0, 9),
             5: (3, 6), 6: (3, 6), 7: (2, 7), 8: (2, 7)},
            {1: 0, 2: 0, 3: 0, 4: 0, 5: 1, 6: 1, 7: 1, 8: 1},
        )
        remaining = [Matchup(1, 4, 10, True), Matchup(2, 3, 10, True),
                     Matchup(5, 6, 10, True), Matchup(7, 8, 10, True)]
        magic = calculate_magic_numbers(teams, remaining, {}, playoff_spots=3)
        assert not magic[1].clinched_playoffs
        assert magic[1].eliminated_playoffs

        results = simulate_season(teams, remaining, {}, n_simulations=500, playoff_spots=3)
        assert results[1].playoff_appearances == 0

    def test_clinched_and_eliminated_flags(self):
        teams = make_teams({1: (10, 0), 2: (5, 5), 3: (4, 6), 4: (0, 10)})
        remaining = [Matchup(1, 4, 11, False), Matchup(2, 3, 11, False)]
        magic = calculate_magic_numbers(teams, remaining, {}, playoff_spots=2)
        assert magic[1].clinched_playoffs and magic[1].clinched_first_seed
        assert magic[1].magic_playoffs is None
        assert magic[4].eliminated_playoffs
        assert magic[4].magic_playoffs is None
        assert not magic[2].clinched_playoffs and not magic[2].eliminated_playoffs

    def test_category_units(self):
        # Each-category league: 9 categories per matchup
        teams = make_teams({1: (60, 30), 2: (45, 45)})
        remaining = [Matchup(1, 2, 11, True)]
        magic = calculate_magic_numbers(teams, remaining, {}, playoff_spots=1,
                                        categories_per_matchup=9)
        # Team 2 can reach 54; team 1 is already at 60
        assert magic[1].clinched_playoffs


class TestBruteForceScenarios:

    def four_team_league(self):
        teams = make_teams({1: (5, 2), 2: (4, 3), 3: (4, 3), 4: (1, 6)})
        remaining = [
            Matchup(1, 4, 8, True), Matchup(2, 3, 8, True),
            Matchup(1, 2, 9, True), Matchup(3, 4, 9, True),
            Matchup(1, 3, 10, True), Matchup(2, 4, 10, True),
        ]
        return teams, remaining

    def test_considers_all_remaining_weeks(self):
        # Previously only this week's games were enumerated, as if the season
        # ended after them, which produced false clinches and eliminations.
        teams, remaining = self.four_team_league()
        report = brute_force_clinch_elimination(teams, remaining, {}, 8, playoff_spots=2)

        # A week-8 win leaves T1 at 6-2 while T2 can still reach 7-3.
        assert not any(s.startswith("T1 clinches division") for s in report.clinch)
        # A week-8 loss leaves T1 at 5-3 with two games left: still alive.
        assert not any(s.startswith("T1 eliminated") for s in report.elimination)
        # T2 at 4-4 can still reach 6-4.
        assert not any(s.startswith("T2 eliminated from playoffs") for s in report.elimination)
        # T4 (1-6) can reach 4 wins at most; T1 already has 5.
        assert report.statuses[4]["eliminated_division"] is True
        assert report.statuses[1]["clinched_division"] is False

    def test_final_week_scenarios(self):
        teams = make_teams({1: (7, 2), 2: (6, 3), 3: (5, 4), 4: (0, 9)})
        remaining = [Matchup(1, 4, 10, True), Matchup(2, 3, 10, True)]
        report = brute_force_clinch_elimination(teams, remaining, {}, 10, playoff_spots=2)
        assert report.statuses[1]["clinched_playoffs"]
        assert "T2 clinches playoff spot with a WIN vs T3" in report.clinch
        assert report.statuses[4]["eliminated_playoffs"]

    def test_scenario_week_skips_to_next_week_with_games(self):
        remaining = [Matchup(1, 2, 5, False)]
        assert scenario_week(remaining, 4) == 5
        assert scenario_week(remaining, 5) == 5
        assert scenario_week([], 7) == 7


def random_league(rng):
    n_teams = rng.choice([4, 6, 8])
    n_divs = rng.choice([1, 2])
    played = rng.randint(4, 9)
    teams = {}
    for tid in range(1, n_teams + 1):
        wins = rng.randint(0, played)
        teams[tid] = Team(id=tid, name=f"T{tid}", division_id=tid % n_divs,
                          wins=wins, losses=played - wins)
    ids = list(teams)
    remaining = []
    week = played + 1
    while len(remaining) + n_teams // 2 <= 10:
        rng.shuffle(ids)
        for a, b in zip(ids[::2], ids[1::2]):
            remaining.append(Matchup(a, b, week, teams[a].division_id == teams[b].division_id))
        week += 1
        if rng.random() < 0.4:
            break
    spots = rng.choice([2, 3, 4]) if n_teams > 4 else 2
    return teams, remaining, spots, played + 1


CLINCH_RE = re.compile(r"^T(\d+) clinches (playoff spot|division|#1 seed) with a WIN")
ELIM_RE = re.compile(r"^T(\d+) (eliminated from playoffs|eliminated from division race) if: LOSS")
GOAL_OF = {
    "playoff spot": "playoffs", "division": "division", "#1 seed": "first_seed",
    "eliminated from playoffs": "playoffs", "eliminated from division race": "division",
}


class TestAnalyticalMathIsSound:
    """
    Whatever the fast analytical math claims must agree with exhaustive
    enumeration: it may miss clinches/eliminations, but never invent them.
    """

    @pytest.mark.parametrize("seed", range(40))
    def test_against_brute_force(self, seed):
        rng = random.Random(seed)
        for _ in range(5):
            teams, remaining, spots, week = random_league(rng)
            exact = brute_force_clinch_elimination(teams, remaining, {}, week, playoff_spots=spots)
            magic = calculate_magic_numbers(teams, remaining, {}, playoff_spots=spots)
            analytic = generate_clinch_elimination_scenarios(teams, remaining, {}, week, playoff_spots=spots)
            context = (teams, remaining, spots)

            for tid, m in magic.items():
                status = exact.statuses[tid]
                for goal in ("playoffs", "division", "first_seed"):
                    if getattr(m, f"clinched_{goal}"):
                        assert status[f"clinched_{goal}"], (tid, goal, context)
                    if getattr(m, f"eliminated_{goal}"):
                        assert status[f"eliminated_{goal}"], (tid, goal, context)

            # Each analytical scenario must be true. Exhaustive enumeration
            # omits it only when the team has in fact already clinched (or
            # been eliminated) outright, which the analytical math may miss.
            for text in analytic.clinch:
                tid, label = CLINCH_RE.match(text).groups()
                already = exact.statuses[int(tid)][f"clinched_{GOAL_OF[label]}"]
                assert text in exact.clinch or already, (text, context)
            for text in analytic.elimination:
                tid, label = ELIM_RE.match(text).groups()
                already = exact.statuses[int(tid)][f"eliminated_{GOAL_OF[label]}"]
                assert text in exact.elimination or already, (text, context)
