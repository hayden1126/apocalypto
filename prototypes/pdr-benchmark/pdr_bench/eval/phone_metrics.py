"""Metrics for the self-collected phone-walk experiment (step 2).

These score PDR without a foot-mounted reference, working around the fact that the
phone GPS is both the scoring reference and the re-anchor source:
  - loop_closure_error needs no GPS at all: a closed walk's true start->end
    displacement is zero, so the open-loop end-vs-start gap is accumulated drift.
  - heldout_reanchor_rmse scores a cadence-re-anchored track only at the mid-cadence
    times, which never pin position or set course, so re-anchoring is not scored
    against the same fixes that anchored it.
  - checkpoint_errors compares PDR at surveyed-marker times to GPS-free surveyed coords.
"""
import numpy as np

from pdr_bench.eval.geo import interp_ne
from pdr_bench.pdr.reanchor import reanchored_track


def loop_closure_error(track: np.ndarray) -> float:
    """Distance (m) between the open-loop end and start; true loop displacement is 0."""
    return float(np.hypot(*(track[-1] - track[0])))


def heldout_reanchor_rmse(step_t: np.ndarray,
    step_len: np.ndarray,
    raw_heading: np.ndarray,
    gnss_t: np.ndarray,
    gnss_ne: np.ndarray,
    interval: float,
) -> float:
    """RMSE (m) of a cadence-re-anchored track at the held-out mid-cadence times.

    Anchors land at multiples of `interval`; evaluation is at the midpoints, which are
    never used to pin position or estimate course, so the residual is honest drift.
    Returns NaN for a non-finite interval (open-loop: nothing is held out)."""
    if not np.isfinite(interval):
        return float("nan")
    track = reanchored_track(step_t, step_len, raw_heading, gnss_t, gnss_ne, interval)
    te = np.arange(step_t[0] + interval / 2.0, step_t[-1], interval)
    if te.size == 0:
        return float("nan")
    pred = interp_ne(step_t, track, te)
    truth = interp_ne(gnss_t, gnss_ne, te)
    return float(np.sqrt(np.mean(np.hypot(*(pred - truth).T) ** 2)))


def checkpoint_errors(step_t: np.ndarray,
    track: np.ndarray,
    marker_t: np.ndarray,
    marker_ne: np.ndarray,
) -> np.ndarray:
    """Per-marker distance (m) between the PDR position at each marker time and its
    surveyed coordinate (both local North-East metres)."""
    pred = interp_ne(step_t, track, marker_t)
    return np.hypot(*(pred - marker_ne).T)
