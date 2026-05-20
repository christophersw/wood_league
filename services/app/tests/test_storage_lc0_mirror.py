"""
Title: test_storage_lc0_mirror.py — SQLAlchemy round-trip tests for Lc0 calibration columns
Description:
    Verifies that the SQLAlchemy ORM mirror models (Lc0GameAnalysis and
    Lc0MoveAnalysis in app/storage/models.py) correctly persist the WDL
    calibration columns introduced in issue #159 (D3+D4).

    Covered columns on Lc0GameAnalysis:
        draw_rate_reference, wdl_calibration_elo, contempt

    Covered columns on Lc0MoveAnalysis:
        wdl_win_adj, wdl_draw_adj, wdl_loss_adj, wdl_mu, delta_mu,
        delta_d, base_severity, draw_character

    Also asserts that ``classification`` does not exist as an attribute on
    the SQLAlchemy Lc0MoveAnalysis model (the column was removed in D3).

    Uses an in-memory SQLite engine — no external Postgres dependency.

Changelog:
    2026-05-19 (#159/D4): Initial round-trip test for SQLAlchemy mirror model.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.storage.models import Base, Game, Lc0GameAnalysis, Lc0MoveAnalysis


@pytest.fixture(scope="module")
def engine():
    """Create an in-memory SQLite engine with all tables.

    Parameters:
        None

    Returns:
        sqlalchemy.engine.Engine: A freshly created engine with schema applied.
    """
    eng = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture(scope="module")
def session_factory(engine):
    """Return a sessionmaker bound to the in-memory engine.

    Parameters:
        engine: The SQLAlchemy engine fixture.

    Returns:
        sessionmaker: A configured session factory.
    """
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture()
def session(session_factory):
    """Open a test session and roll it back after each test.

    Parameters:
        session_factory: The sessionmaker fixture.

    Yields:
        sqlalchemy.orm.Session: An active test database session.

    Side effects:
        Rolls back any changes made during the test so each test starts clean.
    """
    sess: Session = session_factory()
    yield sess
    sess.rollback()
    sess.close()


def _make_game(sess: Session, suffix: str = "a") -> Game:
    """Insert a minimal Game row and return it.

    Parameters:
        sess (Session): The active SQLAlchemy session.
        suffix (str): Short suffix appended to the game ID to avoid PK conflicts.

    Returns:
        Game: The flushed (but not yet committed) Game ORM object.
    """
    game = Game(
        id=f"test-d4-{suffix}",
        played_at=datetime(2024, 1, 1),
        time_control="600",
        pgn="1. e4 e5 *",
    )
    sess.add(game)
    sess.flush()
    return game


class TestLc0GameAnalysisCalibrationColumns:
    """Round-trip tests for the three WDL calibration columns on Lc0GameAnalysis."""

    def test_calibration_columns_persist(self, session: Session) -> None:
        """draw_rate_reference, wdl_calibration_elo, contempt survive a commit/query cycle.

        Parameters:
            session (Session): Injected test session.

        Returns:
            None — asserts via pytest.
        """
        game = _make_game(session, "b")
        analysis = Lc0GameAnalysis(
            game_id=game.id,
            engine_nodes=25000,
            network_name="test-net",
            draw_rate_reference=0.58,
            wdl_calibration_elo=900,
            contempt=-400,
        )
        session.add(analysis)
        session.commit()

        row = session.query(Lc0GameAnalysis).filter_by(game_id=game.id).one()
        assert row.draw_rate_reference == pytest.approx(0.58)
        assert row.wdl_calibration_elo == 900
        assert row.contempt == -400

    def test_calibration_columns_nullable(self, session: Session) -> None:
        """Calibration columns default to NULL when not provided.

        Parameters:
            session (Session): Injected test session.

        Returns:
            None — asserts via pytest.
        """
        game = _make_game(session, "c")
        analysis = Lc0GameAnalysis(game_id=game.id, engine_nodes=1000)
        session.add(analysis)
        session.commit()

        row = session.query(Lc0GameAnalysis).filter_by(game_id=game.id).one()
        assert row.draw_rate_reference is None
        assert row.wdl_calibration_elo is None
        assert row.contempt is None


class TestLc0MoveAnalysisCalibrationColumns:
    """Round-trip tests for the WDL calibration columns on Lc0MoveAnalysis."""

    def _insert_analysis(self, session: Session, suffix: str) -> Lc0GameAnalysis:
        """Insert a parent game + Lc0GameAnalysis for FK use.

        Parameters:
            session (Session): The active SQLAlchemy session.
            suffix (str): Short suffix for game ID uniqueness.

        Returns:
            Lc0GameAnalysis: The flushed parent analysis object.
        """
        game = _make_game(session, suffix)
        analysis = Lc0GameAnalysis(game_id=game.id, engine_nodes=10000)
        session.add(analysis)
        session.flush()
        return analysis

    def test_wdl_calibration_fields_persist(self, session: Session) -> None:
        """All nine calibration move-level columns survive a commit/query cycle.

        Parameters:
            session (Session): Injected test session.

        Returns:
            None — asserts via pytest.
        """
        analysis = self._insert_analysis(session, "d")
        move = Lc0MoveAnalysis(
            analysis_id=analysis.id,
            ply=1,
            san="e4",
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
            wdl_win=500,
            wdl_draw=300,
            wdl_loss=200,
            cp_equiv=10.0,
            best_move="e4",
            wdl_win_adj=480,
            wdl_draw_adj=260,
            wdl_loss_adj=260,
            wdl_mu=0.1,
            delta_mu=0.02,
            delta_d=-0.05,
            base_severity="Excellent",
            draw_character=None,
        )
        session.add(move)
        session.commit()

        row = session.query(Lc0MoveAnalysis).filter_by(analysis_id=analysis.id, ply=1).one()
        assert row.wdl_win_adj == 480
        assert row.wdl_draw_adj == 260
        assert row.wdl_loss_adj == 260
        assert row.wdl_mu == pytest.approx(0.1)
        assert row.delta_mu == pytest.approx(0.02)
        assert row.delta_d == pytest.approx(-0.05)
        assert row.base_severity == "Excellent"
        assert row.draw_character is None

    def test_draw_character_persists_when_set(self, session: Session) -> None:
        """draw_character stores a non-None string value correctly.

        Parameters:
            session (Session): Injected test session.

        Returns:
            None — asserts via pytest.
        """
        analysis = self._insert_analysis(session, "e")
        move = Lc0MoveAnalysis(
            analysis_id=analysis.id,
            ply=2,
            san="e5",
            fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
            wdl_win=400,
            wdl_draw=400,
            wdl_loss=200,
            best_move="e5",
            base_severity="Good",
            draw_character="DrawFavor",
        )
        session.add(move)
        session.commit()

        row = session.query(Lc0MoveAnalysis).filter_by(analysis_id=analysis.id, ply=2).one()
        assert row.draw_character == "DrawFavor"

    def test_calibration_fields_nullable(self, session: Session) -> None:
        """wdl_*_adj, wdl_mu, delta_mu, delta_d may all be NULL.

        Parameters:
            session (Session): Injected test session.

        Returns:
            None — asserts via pytest.
        """
        analysis = self._insert_analysis(session, "f")
        move = Lc0MoveAnalysis(
            analysis_id=analysis.id,
            ply=3,
            san="Nf3",
            fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
            wdl_win=333,
            wdl_draw=333,
            wdl_loss=334,
            best_move="Nf3",
            wdl_win_adj=None,
            wdl_draw_adj=None,
            wdl_loss_adj=None,
            wdl_mu=None,
            delta_mu=None,
            delta_d=None,
            base_severity="Inaccuracy",
            draw_character=None,
        )
        session.add(move)
        session.commit()

        row = session.query(Lc0MoveAnalysis).filter_by(analysis_id=analysis.id, ply=3).one()
        assert row.wdl_win_adj is None
        assert row.wdl_draw_adj is None
        assert row.wdl_loss_adj is None
        assert row.wdl_mu is None
        assert row.delta_mu is None
        assert row.delta_d is None


class TestClassificationColumnRemoved:
    """Verify that the old classification column is not present on Lc0MoveAnalysis."""

    def test_classification_not_on_sqlalchemy_model(self) -> None:
        """Lc0MoveAnalysis must not have a ``classification`` mapped attribute.

        Guards against accidental resurrection of the removed column.

        Returns:
            None — asserts via pytest.
        """
        assert not hasattr(
            Lc0MoveAnalysis, "classification"
        ), (
            "Lc0MoveAnalysis.classification should not exist — "
            "it was replaced by base_severity + draw_character in #159/D3"
        )
