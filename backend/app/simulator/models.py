"""
Data models for the playoff simulator.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional


@dataclass
class Team:
    """Represents a fantasy team with their record and division info."""

    id: int
    name: str
    division_id: int
    wins: int = 0
    losses: int = 0
    ties: int = 0
    division_wins: int = 0
    division_losses: int = 0
    division_ties: int = 0

    @property
    def record_str(self) -> str:
        return f"{self.wins}-{self.losses}-{self.ties}"

    @property
    def division_record_str(self) -> str:
        return f"{self.division_wins}-{self.division_losses}-{self.division_ties}"

    @property
    def win_pct(self) -> float:
        total = self.wins + self.losses + self.ties
        if total == 0:
            return 0.0
        return (self.wins + 0.5 * self.ties) / total

    @property
    def division_win_pct(self) -> float:
        total = self.division_wins + self.division_losses + self.division_ties
        if total == 0:
            return 0.0
        return (self.division_wins + 0.5 * self.division_ties) / total

    def copy(self) -> 'Team':
        """Create a copy of this team for simulation."""
        return Team(
            id=self.id,
            name=self.name,
            division_id=self.division_id,
            wins=self.wins,
            losses=self.losses,
            ties=self.ties,
            division_wins=self.division_wins,
            division_losses=self.division_losses,
            division_ties=self.division_ties
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "division_id": self.division_id,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "division_wins": self.division_wins,
            "division_losses": self.division_losses,
            "division_ties": self.division_ties,
            "record": self.record_str,
            "division_record": self.division_record_str,
            "win_pct": self.win_pct,
            "division_win_pct": self.division_win_pct
        }


@dataclass
class Matchup:
    """Represents a scheduled matchup between two teams."""

    home_team_id: int
    away_team_id: int
    week: int
    is_division_game: bool

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "home_team_id": self.home_team_id,
            "away_team_id": self.away_team_id,
            "week": self.week,
            "is_division_game": self.is_division_game
        }


@dataclass
class LeagueSettings:
    """League configuration settings."""

    playoff_spots: int = 6
    num_divisions: int = 2
    total_weeks: int = 18


@dataclass
class SimulationResult:
    """Results from a Monte Carlo simulation."""

    team_id: int
    division_wins: int = 0
    playoff_appearances: int = 0
    first_seed: int = 0
    last_place: int = 0

    def to_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "division_wins": self.division_wins,
            "playoff_appearances": self.playoff_appearances,
            "first_seed": self.first_seed,
            "last_place": self.last_place
        }


@dataclass
class MagicNumbers:
    """Magic numbers for a team."""

    team_id: int
    magic_division: Optional[int] = None
    magic_playoffs: Optional[int] = None
    magic_first_seed: Optional[int] = None
    magic_last: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "magic_division": self.magic_division,
            "magic_playoffs": self.magic_playoffs,
            "magic_first_seed": self.magic_first_seed,
            "magic_last": self.magic_last
        }


# Type aliases for head-to-head records
H2HRecord = Tuple[int, int, int]  # (team1_wins, team2_wins, ties)
H2HDict = Dict[Tuple[int, int], H2HRecord]
