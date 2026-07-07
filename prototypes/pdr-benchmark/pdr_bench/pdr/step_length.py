"""Weinberg step-length model with distance calibration."""
import numpy as np

from pdr_bench.pdr.steps import Steps


def weinberg_base(steps: Steps) -> np.ndarray:
    """Per-step (a_max - a_min)^(1/4); step length is k times this."""
    return np.power(np.clip(steps.a_max - steps.a_min, 0.0, None), 0.25)


def calibrate_k(steps: Steps,
    known_distance: float,
) -> float:
    """Weinberg k so the estimated total distance equals a known calibration distance."""
    total_base = weinberg_base(steps).sum()
    if total_base == 0:
        raise ValueError("degenerate accel extrema; cannot calibrate k")
    return known_distance / total_base


def weinberg_lengths(steps: Steps,
    k: float,
) -> np.ndarray:
    """Per-step length (m) from the Weinberg model with gain k."""
    return k * weinberg_base(steps)
