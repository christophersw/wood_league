"""
Title: models.py — SQLAlchemy ORM models for shared storage
Description:
    Defines canonical database models for storing chess games, players, analysis
    results, and worker heartbeats. This is the superset of models from
    stockfish_pipeline and dispatchers services. Includes all models from both
    services: Game (with slug), GameAnalysis, MoveAnalysis, OpeningBook,
    AnalysisJob (with full fields), WorkerHeartbeat, and SystemEvent.

Changelog:
    2026-05-07: Merged superset from stockfish_pipeline and dispatchers into shared library
    2026-05-05 (#1): Add pv_san_1/2/3 columns for full PV continuation storage
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


class Player(Base):
    """Represents a chess player tracked in the system."""

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))


class User(Base):
    """Represents an authenticated application user."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Game(Base):
    """Represents a single chess game with metadata and PGN.

    Superset of stockfish_pipeline and dispatchers Game models.
    Includes the `slug` field from dispatchers and all relationships
    from stockfish_pipeline (analysis, analysis_jobs, participants).
    """

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

    analysis: Mapped["GameAnalysis | None"] = relationship(
        back_populates="game", uselist=False
    )
    participants: Mapped[list["GameParticipant"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    analysis_jobs: Mapped[list["AnalysisJob"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )


class GameParticipant(Base):
    """Represents a player's participation in a specific game."""

    __tablename__ = "game_participants"
    __table_args__ = (
        UniqueConstraint("game_id", "player_id", name="uq_game_participant"),
    )

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


class GameAnalysis(Base):
    """Stores aggregate engine analysis results for a game."""

    __tablename__ = "game_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(
        ForeignKey("games.id"), unique=True, index=True
    )
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    engine_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_cp: Mapped[float] = mapped_column(Float, default=0.0)
    white_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    black_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    white_acpl: Mapped[float | None] = mapped_column(Float, nullable=True)
    black_acpl: Mapped[float | None] = mapped_column(Float, nullable=True)
    white_blunders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    white_mistakes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    white_inaccuracies: Mapped[int | None] = mapped_column(Integer, nullable=True)
    black_blunders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    black_mistakes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    black_inaccuracies: Mapped[int | None] = mapped_column(Integer, nullable=True)

    game: Mapped[Game] = relationship(back_populates="analysis")
    moves: Mapped[list["MoveAnalysis"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class MoveAnalysis(Base):
    """Stores per-move engine evaluation data for a game analysis."""

    __tablename__ = "move_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("game_analysis.id"), index=True)
    ply: Mapped[int] = mapped_column(Integer)
    san: Mapped[str] = mapped_column(String(32))
    fen: Mapped[str] = mapped_column(Text)
    cp_eval: Mapped[float] = mapped_column(Float)
    cpl: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_move: Mapped[str] = mapped_column(String(32), default="")
    arrow_uci: Mapped[str] = mapped_column(String(8), default="")
    arrow_uci_2: Mapped[str | None] = mapped_column(String(8), nullable=True)
    arrow_uci_3: Mapped[str | None] = mapped_column(String(8), nullable=True)
    arrow_score_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    arrow_score_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    arrow_score_3: Mapped[float | None] = mapped_column(Float, nullable=True)
    pv_san_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    pv_san_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    pv_san_3: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification: Mapped[str | None] = mapped_column(String(16), nullable=True)

    analysis: Mapped[GameAnalysis] = relationship(back_populates="moves")


class OpeningBook(Base):
    """Stores chess opening book entries indexed by EPD position string."""

    __tablename__ = "opening_book"

    id: Mapped[int] = mapped_column(primary_key=True)
    eco: Mapped[str] = mapped_column(String(8), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    pgn: Mapped[str] = mapped_column(Text)
    epd: Mapped[str] = mapped_column(String(100), unique=True, index=True)


class AnalysisJob(Base):
    """Represents a queued or completed engine analysis job for a game.

    Superset of stockfish_pipeline and dispatchers AnalysisJob models.
    Includes full lifecycle fields: started_at, completed_at, worker_id,
    error_message, retry_count, duration_seconds from stockfish_pipeline.
    """

    __tablename__ = "analysis_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    engine: Mapped[str] = mapped_column(String(16), default="stockfish", index=True)
    depth: Mapped[int] = mapped_column(Integer, default=20)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    runpod_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    game: Mapped[Game] = relationship(back_populates="analysis_jobs")


class WorkerHeartbeat(Base):
    """Tracks liveness and status of engine worker processes."""

    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(16), default="idle")
    current_game_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    jobs_completed: Mapped[int] = mapped_column(Integer, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    cpu_model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    cpu_cores: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stockfish_binary: Mapped[str | None] = mapped_column(String(512), nullable=True)


class SystemEvent(Base):
    """Records system-level events such as ingestion and analysis runs."""

    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
