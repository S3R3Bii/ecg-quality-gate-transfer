"""Authored dimensionless checks for a complete ten-second window."""

import numpy as np


def features(values):
    x = np.asarray(values, dtype=np.float64)
    if x.shape != (3600,) or not np.isfinite(x).all():
        raise ValueError("Expected 3600 finite mV samples at 360Hz")
    center = x.mean()
    variance = np.mean((x - center) ** 2)
    if not np.isfinite(variance) or variance <= 0:
        raise ValueError("Flat or invalid window is unavailable")
    high = np.mean(np.diff(x) ** 2) / variance
    baseline = np.mean((x.reshape(10, 360).mean(axis=1) - center) ** 2) / variance
    if not np.isfinite([baseline, high]).all():
        raise ValueError("Invalid feature output")
    return float(baseline), float(high)


def transformed(values, case):
    x = np.asarray(values, dtype=np.float64)
    if case == "original":
        return x
    if case == "gain_offset":
        return 2 * x + 0.5
    if case == "quantized_002mV":
        return 0.02 * np.rint(x / 0.02)
    raise ValueError("Unknown authored transformation")
