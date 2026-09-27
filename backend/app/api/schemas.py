"""
Pydantic schemas for API request/response validation.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# Platforms and sports the simulator accepts
PLATFORM_PATTERN = "^(espn|yahoo|sleeper|fantrax)$"
SPORT_PATTERN = "^(basketball|football|baseball|hockey)$"


# ============== Auth Schemas ==============

class UserRegister(BaseModel):
    """User registration request."""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        # bcrypt only accepts 72 bytes; non-ASCII characters take several
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password is too long (72 bytes max)")
        return value


class UserLogin(BaseModel):
    """User login request."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """User information response."""
    id: int
    email: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============== League Schemas ==============

class LeagueValidateRequest(BaseModel):
    """League validation request."""
    platform: str = Field(..., pattern=PLATFORM_PATTERN)
    league_id: str = Field(..., min_length=1, max_length=50)
    season: Optional[int] = None  # Defaults to current season
    sport: str = Field(default="basketball", pattern=SPORT_PATTERN)


class LeagueValidateResponse(BaseModel):
    """League validation response."""
    valid: bool
    league_name: Optional[str] = None
    playoff_spots: Optional[int] = None
    num_divisions: Optional[int] = None
    sport: Optional[str] = None
    season: Optional[int] = None  # The season that was actually validated
    error: Optional[str] = None


class SavedLeagueCreate(BaseModel):
    """Create a saved league."""
    platform: str = Field(..., pattern=PLATFORM_PATTERN)
    league_id: str = Field(..., min_length=1, max_length=50)
    season: int
    sport: str = Field(default="basketball", pattern=SPORT_PATTERN)
    nickname: Optional[str] = Field(None, max_length=255)


class SavedLeagueResponse(BaseModel):
    """Saved league response."""
    id: int
    platform: str
    league_id: str
    season: int
    sport: str
    nickname: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============== Simulation Schemas ==============

class SimulationRunRequest(BaseModel):
    """Start a simulation request."""
    platform: str = Field(..., pattern=PLATFORM_PATTERN)
    league_id: str = Field(..., min_length=1, max_length=50)
    season: Optional[int] = None
    sport: str = Field(default="basketball", pattern=SPORT_PATTERN)
    n_simulations: int = Field(default=10000, ge=100, le=25000)
    quick_mode: bool = False  # If true, use 1000 simulations for faster results
    refresh: bool = False  # If true, ignore results cached in the last 15 minutes


class SimulationTaskResponse(BaseModel):
    """Simulation task status response."""
    task_id: str
    status: str  # pending, running, completed, failed
    progress: int  # 0-100
    error: Optional[str] = None


class TeamResult(BaseModel):
    """Simulation results for a single team."""
    id: int
    name: str
    division_id: int
    division_name: str
    wins: int
    losses: int
    ties: int
    record: str
    division_record: str
    win_pct: float
    division_pct: float
    playoff_pct: float
    first_seed_pct: float
    last_place_pct: float
    magic_division: Optional[int]
    magic_playoffs: Optional[int]
    magic_first_seed: Optional[int]
    magic_last: Optional[int]
    # Mathematical status (magic numbers are None once clinched/eliminated)
    clinched_division: bool = False
    clinched_playoffs: bool = False
    clinched_first_seed: bool = False
    eliminated_division: bool = False
    eliminated_playoffs: bool = False


class SimulationResultsResponse(BaseModel):
    """Full simulation results response."""
    league_name: str
    platform: str
    league_id: str
    season: int
    sport: str
    current_week: int
    total_weeks: int
    n_simulations: int
    teams: List[TeamResult]
    clinch_scenarios: List[str]
    elimination_scenarios: List[str]
    # Week the clinch/elimination scenarios describe
    scenario_week: Optional[int] = None
    # Category wins per matchup for "each category" leagues (1 otherwise);
    # records and magic numbers are then in category wins
    categories_per_matchup: int = 1
    # Caveats about how well the simulation models this league
    notes: List[str] = []
    cached: bool = False
    cached_at: Optional[datetime] = None


# ============== Error Schemas ==============

class ErrorResponse(BaseModel):
    """API error response."""
    detail: str
    code: Optional[str] = None
