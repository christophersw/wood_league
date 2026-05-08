"""SQLAlchemy ORM models for Wood League Chess application.

Defines all database models: Players, Users, Games, GameParticipant, GameAnalysis, Lc0GameAnalysis, AnalysisJob, SystemEvent, and related move analysis models.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

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
    """SQLAlchemy declarative base for all ORM models."""
    pass


class Player(Base):
    """Chess.com player record with username and profile information."""
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )


class User(Base):
    """Django application user with authentication and role management."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Game(Base):
    """Chess game record from Chess.com with PGN, time control, and participant info."""
    __tablename__ = "games"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True, unique=True, index=True
    )
    played_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    time_control: Mapped[str] = mapped_column(String(32))
    white_username: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    black_username: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    white_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    black_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    result_pgn: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    winner_username: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    eco_code: Mapped[str] = mapped_column(String(8), default="")
    opening_name: Mapped[str] = mapped_column(String(120), default="")
    lichess_opening: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    pgn: Mapped[str] = mapped_column(Text, default="")

    analysis: Mapped[Optional[GameAnalysis]] = relationship(
        back_populates="game", uselist=False
    )
    lc0_analysis: Mapped[Optional[Lc0GameAnalysis]] = relationship(
        back_populates="game", uselist=False
    )
    participants: Mapped[list[GameParticipant]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    analysis_jobs: Mapped[list[AnalysisJob]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )


class GameParticipant(Base):
    """Links a Player to a Game with color, opponent, rating, and quality metrics."""
    __tablename__ = "game_participants"
    __table_args__ = (
        UniqueConstraint("game_id", "player_id", name="uq_game_participant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    color: Mapped[str] = mapped_column(String(8))
    opponent_username: Mapped[str] = mapped_column(String(120))
    player_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    opponent_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    result: Mapped[str] = mapped_column(String(32))
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    blunder_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mistake_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    inaccuracy_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    acpl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    game: Mapped[Game] = relationship(back_populates="participants")
    player: Mapped[Player] = relationship()


class GameAnalysis(Base):
    """Stockfish game analysis with accuracy, blunders, and per-move evaluations."""
    __tablename__ = "game_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(
        ForeignKey("games.id"), unique=True, index=True
    )
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    engine_depth: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    summary_cp: Mapped[float] = mapped_column(Float, default=0.0)
    white_accuracy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    black_accuracy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    white_acpl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    black_acpl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    white_blunders: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    white_mistakes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    white_inaccuracies: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    black_blunders: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    black_mistakes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    black_inaccuracies: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    game: Mapped[Game] = relationship(back_populates="analysis")
    moves: Mapped[list[MoveAnalysis]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class MoveAnalysis(Base):
    """Stockfish analysis of a single move including evaluation, alternatives, and classification."""
    __tablename__ = "move_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("game_analysis.id"), index=True)
    ply: Mapped[int] = mapped_column(Integer)
    san: Mapped[str] = mapped_column(String(32))
    fen: Mapped[str] = mapped_column(Text)
    cp_eval: Mapped[float] = mapped_column(Float)
    cpl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    best_move: Mapped[str] = mapped_column(String(32), default="")
    arrow_uci: Mapped[str] = mapped_column(String(8), default="")
    arrow_uci_2: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    arrow_uci_3: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    # Candidate eval scores (mover perspective, centipawns) for arrow tiers 1-3.
    arrow_score_1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    arrow_score_2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    arrow_score_3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    classification: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    pv_san_1: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pv_san_2: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pv_san_3: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    analysis: Mapped[GameAnalysis] = relationship(back_populates="moves")


class OpeningBook(Base):
    """Chess opening reference with ECO code, name, PGN, and EPD."""
    __tablename__ = "opening_book"

    id: Mapped[int] = mapped_column(primary_key=True)
    eco: Mapped[str] = mapped_column(String(8), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    pgn: Mapped[str] = mapped_column(Text)
    epd: Mapped[str] = mapped_column(String(100), unique=True, index=True)


class AnalysisJob(Base):
    """Queued analysis job for either Stockfish or Lc0 engine with status and worker tracking."""
    __tablename__ = "analysis_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    engine: Mapped[str] = mapped_column(String(16), default="stockfish", index=True)
    depth: Mapped[int] = mapped_column(Integer, default=20)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    worker_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    runpod_job_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    game: Mapped[Game] = relationship(back_populates="analysis_jobs")


class WorkerHeartbeat(Base):
    """Worker process heartbeat and status tracking for crash detection and monitoring."""
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(16), default="idle")
    current_game_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    jobs_completed: Mapped[int] = mapped_column(Integer, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    cpu_model: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    cpu_cores: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    memory_mb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stockfish_binary: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)


class Lc0GameAnalysis(Base):
    """Lc0 (Leela Chess Zero) WDL (Win/Draw/Loss) probability analysis of a game."""
    __tablename__ = "lc0_game_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(
        ForeignKey("games.id"), unique=True, index=True
    )
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    engine_nodes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    network_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    white_win_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    white_draw_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    white_loss_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    black_win_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    black_draw_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    black_loss_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    white_blunders: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    white_mistakes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    white_inaccuracies: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    black_blunders: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    black_mistakes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    black_inaccuracies: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    game: Mapped[Game] = relationship(back_populates="lc0_analysis")
    moves: Mapped[list[Lc0MoveAnalysis]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class Lc0MoveAnalysis(Base):
    """Lc0 analysis of a single move including WDL probabilities and equivalence scores."""
    __tablename__ = "lc0_move_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("lc0_game_analysis.id"), index=True
    )
    ply: Mapped[int] = mapped_column(Integer)
    san: Mapped[str] = mapped_column(String(32))
    fen: Mapped[str] = mapped_column(Text)
    wdl_win: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    wdl_draw: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    wdl_loss: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cp_equiv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    best_move: Mapped[str] = mapped_column(String(32), default="")
    arrow_uci: Mapped[str] = mapped_column(String(8), default="")
    arrow_uci_2: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    arrow_uci_3: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    # Candidate eval scores (mover perspective, centipawns equivalent) for arrow tiers 1-3.
    arrow_score_1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    arrow_score_2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    arrow_score_3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    move_win_delta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    classification: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    pv_san_1: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pv_san_2: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pv_san_3: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    analysis: Mapped[Lc0GameAnalysis] = relationship(back_populates="moves")


class SystemEvent(Base):
    """System-wide event log for ingest, analysis, and other background processes."""
    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(
        String(32), index=True
    )  # e.g., "ingest", "stockfish", "lc0"
    status: Mapped[str] = mapped_column(
        String(16), index=True
    )  # "started", "completed", "failed"
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    details: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON payload for event-specific data
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
