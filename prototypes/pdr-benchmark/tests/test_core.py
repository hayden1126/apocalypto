"""Deterministic-core tests: geometry, step detection, step length, integration, metrics."""
import numpy as np

from pdr_bench.eval.geo import initial_heading, path_length, rotate_ne
from pdr_bench.eval.metrics import trajectory_metrics
from pdr_bench.pdr.integrate import align_start_pose, dead_reckon
from pdr_bench.pdr.step_length import calibrate_k, weinberg_lengths
from pdr_bench.pdr.steps import Steps, detect_steps


def test_rotate_ne_quarter_turn():
    # North unit vector rotated +90deg CW -> East.
    out = rotate_ne(np.array([[1.0, 0.0]]), np.pi / 2)
    assert np.allclose(out, [[0.0, 1.0]], atol=1e-9)


def test_dead_reckon_square_closes():
    # 4 legs x 10 unit steps at N, E, S, W -> returns to start.
    headings = np.repeat([0, np.pi / 2, np.pi, 3 * np.pi / 2], 10)
    ne = dead_reckon(np.ones(40), headings)
    assert ne.shape == (41, 2)
    assert np.allclose(ne[-1], [0.0, 0.0], atol=1e-9)
    assert np.allclose(ne[10], [10.0, 0.0], atol=1e-9)   # end of north leg
    assert np.allclose(ne[20], [10.0, 10.0], atol=1e-9)  # end of east leg


def test_dead_reckon_heading_bias_is_a_rotation():
    # A constant heading bias rotates the whole track but preserves its shape.
    headings = np.repeat([0, np.pi / 2, np.pi, 3 * np.pi / 2], 10)
    base = dead_reckon(np.ones(40), headings)
    biased = dead_reckon(np.ones(40), headings + 0.3)
    assert np.allclose(biased, rotate_ne(base, 0.3), atol=1e-9)


def test_align_start_pose_recovers_offset():
    headings = np.repeat([0, np.pi / 2, np.pi, 3 * np.pi / 2], 10)
    ref = dead_reckon(np.ones(40), headings)
    rotated = rotate_ne(ref, 0.7)                 # PDR came out rotated by 0.7 rad
    fixed, offset = align_start_pose(rotated, ref)
    assert np.isclose(offset, -0.7, atol=1e-6)
    assert np.allclose(fixed, ref, atol=1e-6)


def test_detect_steps_counts_cadence():
    # 2 Hz cadence for 10 s -> ~20 steps.
    fs = 100.0
    t = np.arange(0, 10, 1 / fs)
    accel_mag = 9.81 + 1.5 * np.sin(2 * np.pi * 2.0 * t)
    steps = detect_steps(t, accel_mag, fs)
    assert 18 <= len(steps.idx) <= 22


def test_calibrate_k_matches_known_distance():
    steps = Steps(idx=np.arange(5), t=np.arange(5.0),
                  a_max=np.full(5, 12.0), a_min=np.full(5, 8.0))
    k = calibrate_k(steps, known_distance=5.0)
    lengths = weinberg_lengths(steps, k)
    assert np.isclose(lengths.sum(), 5.0)


def test_trajectory_metrics_known_offset():
    # A track offset 3 m east of a straight north-going reference.
    ref = np.column_stack([np.linspace(0, 100, 50), np.zeros(50)])
    track = ref + np.array([0.0, 3.0])
    m = trajectory_metrics(track, ref, path_length(ref))
    assert np.isclose(m["rmse_m"], 3.0, atol=1e-6)
    assert np.isclose(m["cross_track_mean_m"], 3.0, atol=1e-6)
    assert np.isclose(m["final_drift_pct"], 3.0, atol=1e-3)
