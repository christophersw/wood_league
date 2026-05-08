from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Game(Base):
    __tablename__ = "games"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True, index=True)
    played_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    time_control: Mapped[str] = mapped_column(String(32))
    white_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    black_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    white_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    black_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_pgn: Mapped[str | None] = mapped_column(String(16), nullable=True)
    winner_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    eco_code: Mapped[str] = mapped_column(String(8), default="")
    opening_name: Mapped[str] = mapped_column(String(120), default="")
    lichess_opening: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pgn: Mapped[str] = mapped_column(Text, default="")

    participants: Mapped[list["GameParticipant"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    analysis_jobs: Mapped[list["AnalysisJob"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )


class GameParticipant(Base):
    __tablename__ = "game_participants"
    __table_args__ = (UniqueConstraint("game_id", "player_id", name="uq_game_participant"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    color: Mapped[str] = mapped_column(String(8))
    opponent_username: Mapped[str] = mapped_column(String(120))
    player_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opponent_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[str] = mapped_column(String(32))
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    blunder_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mistake_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inaccuracy_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acpl: Mapped[float | None] = mapped_column(Float, nullable=True)

    game: Mapped[Game] = relationship(back_populates="participants")
    player: Mapped[Player] = relationship()


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    engine: Mapped[str] = mapped_column(String(16), default="stockfish", index=True)
    depth: Mapped[int] = mapped_column(Integer, default=20)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    runpod_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    game: Mapped[Game] = relationship(back_populates="analysis_jobs")


class SystemEvent(Base):
    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)  # e.g., "ingest", "stockfish", "lc0"
    status: Mapped[str] = mapped_column(String(16), index=True)  # "started", "completed", "failed"
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON payload for event-specific data
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
