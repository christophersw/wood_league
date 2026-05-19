"""
Title: test_lc0_draw_rate.py — Unit tests for per-network draw-rate sampler
Description:
    Tests for measure_draw_rate() in lc0_draw_rate.py. The lc0 engine is
    mocked to keep these tests fast and deterministic — no binary required.
Changelog:
    2026-05-19: Initial creation (issue #159).
"""
import chess.engine

from local_worker.analysis.lc0_draw_rate import DrawRateResult, measure_draw_rate


class _FakeScore:
    """Fake engine score returning a fixed WDL."""

    def __init__(self, wdl: tuple[int, int, int]) -> None:
        """Init with fixed WDL permille triple."""
        self._w = wdl

    def pov(self, _color: chess.Color) -> "_FakeScore":
        """Return self (already in the requested perspective for mocking)."""
        return self

    def wdl(self, *args: object, **kwargs: object) -> chess.engine.Wdl:
        """Return fixed WDL."""
        return chess.engine.Wdl(*self._w)


class _FakeEngine:
    """Deterministic fake engine; always returns the same WDL (400, 350, 250).

    Because the startpos WDL is always identical, the sampler will detect
    determinism after one repeat and then sweep CURATED_OPENING_FENS.
    """

    def __init__(self) -> None:
        """Init call counter."""
        self.calls = 0

    def analyse(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        **kwargs: object,
    ) -> dict:
        """Return fake analysis info dict."""
        self.calls += 1
        return {"score": _FakeScore((400, 350, 250))}


def test_sampler_returns_draw_rate_result() -> None:
    """measure_draw_rate returns a valid DrawRateResult."""
    eng = _FakeEngine()
    res = measure_draw_rate(eng, network="t-test", sem_target=0.005,
                            max_samples=8, nodes=1)
    assert isinstance(res, DrawRateResult)


def test_sampler_draw_rate_in_range() -> None:
    """draw_rate_reference is clamped to (0, 1)."""
    eng = _FakeEngine()
    res = measure_draw_rate(eng, network="t-test", sem_target=0.005,
                            max_samples=8, nodes=1)
    assert 0.0 < res.draw_rate_reference < 1.0


def test_sampler_respects_max_samples() -> None:
    """n_samples does not exceed max_samples."""
    eng = _FakeEngine()
    res = measure_draw_rate(eng, network="t-test", sem_target=0.005,
                            max_samples=8, nodes=1)
    assert res.n_samples <= 8


def test_sampler_preserves_network_name() -> None:
    """network field echoes back the caller-supplied name."""
    eng = _FakeEngine()
    res = measure_draw_rate(eng, network="t-test", sem_target=0.005,
                            max_samples=8, nodes=1)
    assert res.network == "t-test"


def test_sampler_stops_on_sem_or_cap() -> None:
    """Canonical test from the plan: all four postconditions together."""
    eng = _FakeEngine()
    res = measure_draw_rate(eng, network="t-test", sem_target=0.005,
                            max_samples=8, nodes=1)
    assert isinstance(res, DrawRateResult)
    assert 0.0 < res.draw_rate_reference < 1.0
    assert res.n_samples <= 8
    assert res.network == "t-test"


def test_sampler_correct_draw_fraction() -> None:
    """With WDL (400, 350, 250) draw fraction is 350/1000 = 0.35."""
    eng = _FakeEngine()
    res = measure_draw_rate(eng, network="t-test", sem_target=0.0,
                            max_samples=100, nodes=1)
    # All samples are 350/1000 = 0.35; mean = 0.35; clamped = 0.35
    assert abs(res.draw_rate_reference - 0.35) < 1e-6
