"""
Title: draw_rate_fens.py — curated opening positions for draw-rate calibration
Description:
    Small fixed set of post-opening FENs used when repeated start-position
    sampling is deterministic (single-thread search). Mainline, roughly
    balanced positions so the measured draw rate reflects the network's
    inherent drawishness rather than opening sharpness.
Changelog:
    2026-05-19: Initial creation (issue #159).
    2026-05-19: Replace startpos at index 0 with QGD tabiya — startpos is
                already sampled in the nondeterministic phase (issue #159 B1).
"""

CURATED_OPENING_FENS: tuple[str, ...] = (
    # QGD tabiya (1.d4 d5 2.c4 e6 3.Nc3 Nf6 4.Bg5 Be7 5.e3 O-O 6.Nf3 Nbd7)
    # — mainline post-opening, roughly balanced; startpos excluded here because
    # the nondeterministic phase already samples it.
    "r1bq1rk1/pppnbppp/4pn2/3p2B1/2PP4/2N1PN2/PP3PPP/R2QKB1R w KQ - 2 7",
    "rnbqkb1r/pppp1ppp/5n2/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
    "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 3 3",
    "rnbqkb1r/pp2pppp/3p1n2/2pP4/4P3/8/PPP2PPP/RNBQKBNR w KQkq - 0 4",
    "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
    "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2",
)
