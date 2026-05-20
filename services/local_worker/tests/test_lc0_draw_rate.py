"""
Title: test_lc0_draw_rate.py — Unit tests for per-network draw-rate sampler
Description:
    Tests for measure_draw_rate() in lc0_draw_rate.py. The lc0 engine is
    mocked to keep these tests fast and deterministic — no binary required.
Changelog:
    2026-05-19: Initial creation (issue #159).
    2026-05-19: Add combined-sample-set test (#159 FIX 2).
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


class _NondeterministicThenDeterministicEngine:
    """Engine that returns varying values for the first N calls, then a fixed value.

    Simulates nondeterministic multi-threaded search (startpos varies) before
    search becomes deterministic (two consecutive identical results trigger the
    curated-FEN phase).  Used to test that the combined sample set (both
    nondeterministic and deterministic phase samples) is reflected in
    DrawRateResult.n_samples and the mean.
    """

    def __init__(self, varying_wdls: list[tuple[int, int, int]],
                 fixed_wdl: tuple[int, int, int]) -> None:
        """Initialise with a sequence of varying WDLs followed by a fixed one.

        Args:
            varying_wdls: WDL permille triples returned for the first N calls.
            fixed_wdl: WDL permille triple returned for all subsequent calls
                (triggers determinism detection on repeat).
        """
        self._varying = list(varying_wdls)
        self._fixed = fixed_wdl
        self.calls = 0

    def analyse(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        **kwargs: object,
    ) -> dict:
        """Return WDL from the varying sequence, then fixed."""
        self.calls += 1
        if self._varying:
            wdl = self._varying.pop(0)
        else:
            wdl = self._fixed
        return {"score": _FakeScore(wdl)}


def test_n_samples_reflects_combined_nondeterministic_and_deterministic() -> None:
    """n_samples counts ALL positions: nondeterministic-phase + curated-FEN phase.

    The engine returns 3 varying startpos values (nondeterministic), then
    a fixed value that repeats (triggering deterministic detection).  The
    n_samples on the returned DrawRateResult must equal the total number of
    engine calls, not just the deterministic-phase count.
    """
    # 3 varying startpos samples → nondeterministic phase
    # fixed WDL repeated → triggers determinism after one more call
    # Then curated FENs are swept
    varying: list[tuple[int, int, int]] = [
        (500, 300, 200),  # call 1: startpos (first)
        (480, 310, 210),  # call 2: startpos (prev=0.3, nxt=0.31, not equal)
        (460, 330, 210),  # call 3: startpos (prev=0.31, nxt=0.33, not equal)
        (440, 340, 220),  # call 4: startpos (prev=0.33, nxt=0.34, not equal)
    ]
    fixed: tuple[int, int, int] = (400, 350, 250)  # draws=0.35, repeat triggers det.
    eng = _NondeterministicThenDeterministicEngine(varying, fixed)
    # sem_target=0.0 forces exhaustion of max_samples
    res = measure_draw_rate(eng, network="t-nd-test", sem_target=0.0,
                            max_samples=10, nodes=1)
    # The engine is called for:
    #   - first: 1 call
    #   - nondeterministic loop: calls until determinism detected
    #   - deterministic sweep: remaining curated FENs up to max_samples
    # All calls must be counted in n_samples
    assert res.n_samples == eng.calls, (
        f"n_samples={res.n_samples} != engine.calls={eng.calls}; "
        "combined sample set not accumulated correctly"
    )
    assert res.n_samples > 0
