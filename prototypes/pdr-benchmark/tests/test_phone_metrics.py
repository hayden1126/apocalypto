"""Tests for the phone-walk metrics (loop closure, held-out re-anchor, checkpoints)."""
import numpy as np

from pdr_bench.eval.phone_metrics import (checkpoint_errors, heldout_reanchor_rmse,
                                          loop_closure_error)
from pdr_bench.pdr.integrate import dead_reckon


def test_loop_closure_zero_for_closed_square():
    # N, E, S, W legs of equal length return to the start.
    headings = np.repeat([0, np.pi / 2, np.pi, 3 * np.pi / 2], 10)
    ne = dead_reckon(np.ones(40), headings)
    assert loop_closure_error(ne) < 1e-9


def test_loop_closure_measures_endpoint_gap():
    track = np.array([[0.0, 0.0], [3.0, 4.0]])
    assert np.isclose(loop_closure_error(track), 5.0)


def test_heldout_rmse_tighter_cadence_bounds_drift():
    # Straight 100 m north walk; gyro heading drifts; perfect GPS along the true line.
    n = 100
    step_t = np.arange(n) * 0.5
    step_len = np.ones(n)
    raw_heading = 0.006 * np.arange(n)
    truth = np.column_stack([np.arange(1, n + 1), np.zeros(n)]).astype(float)
    gnss_t, gnss_ne = step_t.copy(), truth.copy()
    tight = heldout_reanchor_rmse(step_t, step_len, raw_heading, gnss_t, gnss_ne, 5.0)
    loose = heldout_reanchor_rmse(step_t, step_len, raw_heading, gnss_t, gnss_ne, 40.0)
    assert tight < 2.0                 # tight cadence holds drift at street scale
    assert loose > tight               # looser cadence lets more drift accumulate


def test_heldout_rmse_nan_without_reanchor():
    step_t = np.arange(10).astype(float)
    truth = np.column_stack([np.arange(10), np.zeros(10)]).astype(float)
    rmse = heldout_reanchor_rmse(step_t, np.ones(10), np.zeros(10),
                                 step_t.copy(), truth, np.inf)
    assert np.isnan(rmse)              # inf interval = open-loop, nothing held out


def test_checkpoint_errors_measure_offset():
    step_t = np.arange(11).astype(float)
    track = np.column_stack([np.arange(11), np.zeros(11)]).astype(float)  # north 0..10
    marker_t = np.array([5.0])
    on_track = checkpoint_errors(step_t, track, marker_t, np.array([[5.0, 0.0]]))
    offset = checkpoint_errors(step_t, track, marker_t, np.array([[5.0, 3.0]]))
    assert on_track[0] < 1e-9
    assert np.isclose(offset[0], 3.0)
