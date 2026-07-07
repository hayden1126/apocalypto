"""Heading-convention regression tests and a dataset-level PDR sanity guard.

These pin the yaw sign fix: the AHRS reports ENU yaw (CCW from East) and the pipeline
must convert it to a compass heading, or the whole trajectory mirrors and RMSE explodes.
"""
from pathlib import Path

import numpy as np
import pytest

from pdr_bench.pdr.heading import estimate_yaw

DATA = Path(__file__).resolve().parent.parent / "data/geoloc/Geoloc_ds022023"


def test_estimate_yaw_is_compass_sense():
    # Device held flat, rotating at +0.3 rad/s about vertical (CCW / left turn).
    # A left turn must DECREASE the compass heading (compass grows clockwise).
    fs, omega, n = 100.0, 0.3, 400
    gyro = np.tile([0.0, 0.0, omega], (n, 1))
    accel = np.tile([0.0, 0.0, 9.81], (n, 1))
    mag = np.zeros((n, 3))
    heading = np.unwrap(estimate_yaw(accel, gyro, mag, fs, np.zeros(3), use_mag=False))
    delta = heading[-1] - heading[0]
    assert np.isclose(delta, -omega * (n - 1) / fs, atol=0.15)


@pytest.mark.skipif(not DATA.exists(), reason="GEOLOC dataset not present")
def test_gyro_pdr_drift_is_sane():
    # Guards against the mirror/sign regression: gyro-only PDR on the clean campus
    # loop must stay in the few-percent regime, not tens of metres.
    from pdr_bench.io.geoloc import load_track
    from pdr_bench.pdr.pipeline import run_pdr
    r = run_pdr(load_track(DATA, "TEST_02"), use_mag=False)
    assert r.metrics["rmse_m"] < 12.0
    assert r.metrics["final_drift_pct"] < 8.0
