"""
Pydantic schemas for API request/response validation.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field


# ============== Auth Schemas ==============

class UserRegister(BaseModel):
    """User registration request."""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)


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

    class Config:
        from_attributes = True


# ============== League Schemas ==============

class LeagueValidateRequest(BaseModel):
    """League validation request."""
    platform: str = Field(..., pattern="^(espn|yahoo|sleeper|fantrax)$")
    league_id: str = Field(..., min_length=1, max_length=50)
    season: Optional[int] = None  # Defaults to current season
    sport: str = Field(default="basketball", pattern="^(basketball|football|baseball)$")


class LeagueValidateResponse(BaseModel):
    """League validation response."""
    valid: bool
    league_name: Optional[str] = None
    playoff_spots: Optional[int] = None
    num_divisions: Optional[int] = None
    sport: Optional[str] = None
    error: Optional[str] = None


class SavedLeagueCreate(BaseModel):
    """Create a saved league."""
    platform: str = Field(..., pattern="^(espn|yahoo|sleeper|fantrax)$")
    league_id: str = Field(..., min_length=1, max_length=50)
    season: int
    sport: str = Field(default="basketball", pattern="^(basketball|football|baseball)$")
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

    class Config:
        from_attributes = True


# ============== Simulation Schemas ==============

class SimulationRunRequest(BaseModel):
    """Start a simulation request."""
    platform: str = Field(..., pattern="^(espn|yahoo|sleeper|fantrax)$")
    league_id: str = Field(..., min_length=1, max_length=50)
    season: Optional[int] = None
    sport: str = Field(default="basketball", pattern="^(basketball|football|baseball)$")
    n_simulations: int = Field(default=10000, ge=100, le=100000)
    quick_mode: bool = False  # If true, use 1000 simulations for faster results


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
    cached: bool = False
    cached_at: Optional[datetime] = None


# ============== Error Schemas ==============

class ErrorResponse(BaseModel):
    """API error response."""
    detail: str
    code: Optional[str] = None
