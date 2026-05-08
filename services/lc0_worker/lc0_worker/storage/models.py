"""
Title: models.py — Lc0 analysis database models
Description:
    SQLAlchemy ORM models for persisting Lc0 chess engine analysis results,
    including game-level aggregates (WDL, blunder counts) and per-move evaluations
    with principal variations and classification data.

Changelog:
    2026-05-05 (#1): Add pv_san_1/2/3 columns for full PV continuation storage
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Game(Base):
    """Minimal game record — PGN source for analysis. Full game data lives in the main app."""

    __tablename__ = "games"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pgn: Mapped[str] = mapped_column(Text, default="")
    played_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    white_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    black_username: Mapped[str | None] = mapped_column(String(120), nullable=True)

    lc0_analysis: Mapped["Lc0GameAnalysis | None"] = relationship(
        back_populates="game", uselist=False
    )
    analysis_jobs: Mapped[list["AnalysisJob"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )


class AnalysisJob(Base):
    """Work queue for Lc0 analysis jobs."""

    __tablename__ = "analysis_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    engine: Mapped[str] = mapped_column(String(16), default="lc0", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    # depth column stores node budget for Lc0 (reuses same field name for queue compatibility)
    depth: Mapped[int] = mapped_column(Integer, default=25000)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    runpod_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    game: Mapped[Game] = relationship(back_populates="analysis_jobs")


class WorkerHeartbeat(Base):
    """Lc0 worker health monitoring."""

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
    lc0_binary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lc0_network: Mapped[str | None] = mapped_column(String(512), nullable=True)


class Lc0GameAnalysis(Base):
    """Lc0 WDL aggregate analysis for a game."""

    __tablename__ = "lc0_game_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(
        ForeignKey("games.id"), unique=True, index=True
    )
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    engine_nodes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    network_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    white_win_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    white_draw_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    white_loss_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    black_win_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    black_draw_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    black_loss_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    white_blunders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    white_mistakes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    white_inaccuracies: Mapped[int | None] = mapped_column(Integer, nullable=True)
    black_blunders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    black_mistakes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    black_inaccuracies: Mapped[int | None] = mapped_column(Integer, nullable=True)

    game: Mapped[Game] = relationship(back_populates="lc0_analysis")
    moves: Mapped[list["Lc0MoveAnalysis"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class Lc0MoveAnalysis(Base):
    """Per-move Lc0 WDL results."""

    __tablename__ = "lc0_move_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("lc0_game_analysis.id"), index=True
    )
    ply: Mapped[int] = mapped_column(Integer)
    san: Mapped[str] = mapped_column(String(32))
    fen: Mapped[str] = mapped_column(Text)
    # WDL permille from White's perspective (sum to 1000)
    wdl_win: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wdl_draw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wdl_loss: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cp_equiv: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_move: Mapped[str] = mapped_column(String(32), default="")
    arrow_uci: Mapped[str] = mapped_column(String(8), default="")
    arrow_uci_2: Mapped[str | None] = mapped_column(String(8), nullable=True)
    arrow_uci_3: Mapped[str | None] = mapped_column(String(8), nullable=True)
    arrow_score_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    arrow_score_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    arrow_score_3: Mapped[float | None] = mapped_column(Float, nullable=True)
    move_win_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    classification: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pv_san_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    pv_san_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    pv_san_3: Mapped[str | None] = mapped_column(Text, nullable=True)

    analysis: Mapped[Lc0GameAnalysis] = relationship(back_populates="moves")


class SystemEvent(Base):
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
