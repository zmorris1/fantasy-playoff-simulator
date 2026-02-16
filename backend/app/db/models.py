"""
SQLAlchemy database models.
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, JSON, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class User(Base):
    """User account model."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    saved_leagues: Mapped[list["SavedLeague"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )
    yahoo_credential: Mapped[Optional["YahooCredential"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False
    )
    cbs_credential: Mapped[Optional["CBSCredential"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email})>"


class SavedLeague(Base):
    """Saved league configuration for a user."""

    __tablename__ = "saved_leagues"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    league_id: Mapped[str] = mapped_column(String(100), nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    sport: Mapped[str] = mapped_column(String(50), nullable=False, default="basketball")
    nickname: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="saved_leagues")

    __table_args__ = (
        Index("ix_saved_leagues_user_platform_league", "user_id", "platform", "league_id", "season", "sport"),
    )

    def __repr__(self) -> str:
        return f"<SavedLeague(id={self.id}, platform={self.platform}, league_id={self.league_id}, sport={self.sport})>"


class SimulationCache(Base):
    """Cache for simulation results with TTL."""

    __tablename__ = "simulation_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    league_id: Mapped[str] = mapped_column(String(100), nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    sport: Mapped[str] = mapped_column(String(50), nullable=False, default="basketball")
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    results_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_simulation_cache_lookup", "platform", "league_id", "season", "sport", "week"),
    )

    def __repr__(self) -> str:
        return f"<SimulationCache(platform={self.platform}, league_id={self.league_id}, sport={self.sport}, week={self.week})>"

    @property
    def is_expired(self) -> bool:
        """Check if the cache entry has expired."""
        return datetime.now(timezone.utc) > self.expires_at


class YahooCredential(Base):
    """Yahoo OAuth credentials for a user."""

    __tablename__ = "yahoo_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_type: Mapped[str] = mapped_column(String(50), default="bearer")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    yahoo_guid: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="yahoo_credential")

    def __repr__(self) -> str:
        return f"<YahooCredential(id={self.id}, user_id={self.user_id})>"

    @property
    def is_expired(self) -> bool:
        """Check if the access token has expired."""
        return datetime.now(timezone.utc) > self.expires_at


class CBSCredential(Base):
    """CBS Sports OAuth credentials for a user."""

    __tablename__ = "cbs_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_type: Mapped[str] = mapped_column(String(50), default="bearer")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cbs_user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="cbs_credential")

    def __repr__(self) -> str:
        return f"<CBSCredential(id={self.id}, user_id={self.user_id})>"

    @property
    def is_expired(self) -> bool:
        """Check if the access token has expired."""
        return datetime.now(timezone.utc) > self.expires_at


class SimulationTask(Base):
    """Background simulation task tracking."""

    __tablename__ = "simulation_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    league_id: Mapped[str] = mapped_column(String(100), nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    sport: Mapped[str] = mapped_column(String(50), nullable=False, default="basketball")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    results_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    __table_args__ = (
        Index("ix_simulation_tasks_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<SimulationTask(id={self.id}, sport={self.sport}, status={self.status})>"
