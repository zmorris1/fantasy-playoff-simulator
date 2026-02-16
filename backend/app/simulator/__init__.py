"""
Fantasy Basketball Playoff Simulator

Monte Carlo simulation to calculate playoff probabilities.
"""

from .models import Team, Matchup, LeagueSettings, SimulationResult, MagicNumbers, H2HDict
from .engine import simulate_season, determine_playoffs, apply_outcome
from .tiebreakers import resolve_tiebreaker, get_h2h_record
from .magic_numbers import calculate_magic_numbers
from .scenarios import generate_clinch_elimination_scenarios, brute_force_clinch_elimination

__all__ = [
    # Models
    "Team",
    "Matchup",
    "LeagueSettings",
    "SimulationResult",
    "MagicNumbers",
    "H2HDict",
    # Engine
    "simulate_season",
    "determine_playoffs",
    "apply_outcome",
    # Tiebreakers
    "resolve_tiebreaker",
    "get_h2h_record",
    # Magic numbers
    "calculate_magic_numbers",
    # Scenarios
    "generate_clinch_elimination_scenarios",
    "brute_force_clinch_elimination",
]
