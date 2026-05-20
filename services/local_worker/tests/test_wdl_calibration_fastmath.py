import math
import numpy as np
from local_worker.analysis.wdl_calibration import (
    fast_log2, fast_exp2, fast_exp, fast_log, fast_logistic,
)

def test_fast_log2_matches_reference_points():
    assert fast_log2(np.float32(1.0)) == 0.0
    for x in (0.5, 2.0, 8.0, 0.1, 1234.5):
        approx = fast_log2(np.float32(x))
        assert abs(approx - math.log2(x)) < 0.01, x

def test_fast_logistic_saturates():
    assert fast_logistic(np.float32(21.0)) == 1.0
    assert fast_logistic(np.float32(-21.0)) == 0.0
    assert abs(fast_logistic(np.float32(0.0)) - 0.5) < 0.01

def test_fast_log_is_ln():
    for x in (0.2, 1.0, 3.3, 50.0):
        assert abs(fast_log(np.float32(x)) - math.log(x)) < 0.02, x

def test_fast_exp2_matches_reference_incl_negative():
    for x in (-3.5, -1.5, -0.5, 0.0, 0.5, 2.0, 7.25):
        approx = float(fast_exp2(np.float32(x)))
        assert abs(approx - 2.0 ** x) < 0.02 * max(1.0, 2.0 ** x), (x, approx)

def test_fast_exp_matches_reference_incl_negative():
    for x in (-4.0, -1.2, -0.3, 0.0, 1.7, 5.0):
        approx = float(fast_exp(np.float32(x)))
        assert abs(approx - math.exp(x)) < 0.02 * max(1.0, math.exp(x)), (x, approx)
