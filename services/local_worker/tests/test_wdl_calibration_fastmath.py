import math
import numpy as np
from local_worker.analysis.wdl_calibration import (
    fast_log2, fast_log, fast_logistic,
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
