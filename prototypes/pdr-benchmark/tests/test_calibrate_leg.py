"""Unit tests for the calibration-leg windowing in scripts/calibrate_leg.py.

The leg is the first sustained walking run, terminated by the deliberate stop (a large
inter-step gap). These check the boundary logic on synthetic step times without needing
a real export."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

_spec = importlib.util.spec_from_file_location(
    "calibrate_leg", Path(__file__).resolve().parent.parent / "scripts" / "calibrate_leg.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_first_walking_run = _mod._first_walking_run


def test_run_ends_at_the_pause():
    # 13 steps at 0.6 s cadence, then a 3 s stop, then more walking.
    leg = np.arange(13) * 0.6
    rest = leg[-1] + 3.0 + np.arange(1, 8) * 0.6
    step_t = np.concatenate([leg, rest])
    start, end = _first_walking_run(step_t, pause_s=1.2, min_run=5)
    assert (start, end) == (0, 12)          # 13 footfalls, indices 0..12


def test_skips_spurious_pre_onset_step():
    # one isolated twitch during the static, a 5 s gap, then the real 8-step run.
    step_t = np.concatenate([[0.0], 5.0 + np.arange(8) * 0.6])
    start, end = _first_walking_run(step_t, pause_s=1.2, min_run=5)
    assert start == 1 and end == 8          # the isolated step 0 is not the leg


def test_raises_when_no_sustained_run():
    # every gap exceeds the pause threshold: no run reaches min_run.
    step_t = np.arange(5) * 2.0
    with pytest.raises(ValueError):
        _first_walking_run(step_t, pause_s=1.2, min_run=5)
