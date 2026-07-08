"""Adapter tests for phone sensor-logger exports (Sensor Logger format).

Deterministic-core: synthetic per-sensor CSVs pin the two risky conversions
(gravity reconstruction, GPS -> local NE) and the phone-session contract (no
foot-mounted strides). Sensor Logger `time` is Unix-epoch nanoseconds, so the
timestamp test also guards the integer-domain rebasing that keeps sub-ms precision.
"""
import numpy as np
import pandas as pd
import pytest

from pdr_bench.io.phone import load_phone, phone_georef
from pdr_bench.pdr.pipeline import heading_only_reference

EPOCH_NS = 1_700_000_000_000_000_000   # a fixed Unix epoch in ns (~2023-11-14)


def _write_sensor(path, t0_ns, fs, n, cols):
    """Write a Sensor Logger sensor csv with `time` (ns), seconds_elapsed, + cols."""
    time_ns = t0_ns + (np.arange(n) / fs * 1e9).astype(np.int64)
    df = pd.DataFrame({"time": time_ns,
                       "seconds_elapsed": (time_ns - time_ns[0]) * 1e-9,
                       **cols})
    df.to_csv(path, index=False)


def _make_export(tmp_path, *, imu_offset_s=0.0, lat=None, lon=None):
    """Build a minimal well-formed Sensor Logger export dir; return its path."""
    d = tmp_path / "export"
    d.mkdir()
    n, fs = 200, 100.0
    imu_t0 = EPOCH_NS + int(imu_offset_s * 1e9)
    # linear accel ~0 (at rest) + gravity +9.81 z -> raw specific force ~9.81 on z
    _write_sensor(d / "Accelerometer.csv", imu_t0, fs, n,
                  {"x": np.zeros(n), "y": np.zeros(n), "z": np.zeros(n)})
    # gravity on a different (50 Hz) grid to exercise the resample-onto-accel_t path
    _write_sensor(d / "Gravity.csv", imu_t0, 50.0, n // 2,
                  {"x": np.zeros(n // 2), "y": np.zeros(n // 2),
                   "z": np.full(n // 2, 9.81)})
    _write_sensor(d / "Gyroscope.csv", imu_t0, fs, n,
                  {"x": np.zeros(n), "y": np.zeros(n), "z": np.full(n, 0.1)})
    _write_sensor(d / "Magnetometer.csv", imu_t0, fs, n,
                  {"x": np.full(n, 22.0), "y": np.zeros(n), "z": np.full(n, -40.0)})
    ng = 5
    lat = np.full(ng, 48.0) if lat is None else lat
    lon = np.full(ng, -1.5) if lon is None else lon
    # GPS at 1 Hz, starting at EPOCH_NS (i.e. possibly before the IMU)
    _write_sensor(d / "Location.csv", EPOCH_NS, 1.0, ng,
                  {"latitude": lat, "longitude": lon, "altitude": np.zeros(ng),
                   "horizontalAccuracy": np.full(ng, 4.0),
                   "verticalAccuracy": np.full(ng, 6.0),
                   "bearing": np.zeros(ng), "speed": np.zeros(ng)})
    return d


def test_gravity_reconstruction(tmp_path):
    # Sensor Logger's Accelerometer excludes gravity; raw accel = linear + Gravity.
    s = load_phone(_make_export(tmp_path))
    assert np.allclose(s.accel[:, 2], 9.81, atol=1e-6)
    assert np.allclose(s.accel[:, :2], 0.0, atol=1e-6)
    assert 9.0 < s.meta["accel_median_norm_m_s2"] < 10.5


def test_units_passthrough(tmp_path):
    s = load_phone(_make_export(tmp_path))
    assert np.allclose(s.gyro[:, 2], 0.1)          # rad/s unchanged
    assert np.allclose(s.mag[:, 0], 22.0)          # uT unchanged
    assert np.allclose(s.mag_ainv, np.eye(3))      # no per-device calibration
    assert np.allclose(s.mag_bias, 0.0)


def test_timestamps_rebased_to_shared_origin(tmp_path):
    # GPS starts 0.5 s before the IMU; both land on one clock with the min at 0.
    s = load_phone(_make_export(tmp_path, imu_offset_s=0.5))
    assert np.isclose(s.gt_t[0], 0.0, atol=1e-9)       # GPS is earliest -> 0
    assert np.isclose(s.accel_t[0], 0.5, atol=1e-9)    # IMU offset preserved exactly
    assert np.isclose(s.gyro_t[0], 0.5, atol=1e-9)


def test_ne_frame_roundtrip_and_north_sign(tmp_path):
    lat = np.array([48.0, 48.0001, 48.0002, 48.0003, 48.0004])   # moving north
    lon = np.full(5, -1.5)
    s = load_phone(_make_export(tmp_path, lat=lat, lon=lon))
    assert np.allclose(s.gt_ne[0], 0.0, atol=1e-6)               # origin at first fix
    assert np.all(np.diff(s.gt_ne[:, 0]) > 0)                    # North increases
    # due-north travel is mostly North; only small UTM meridian-convergence East drift
    assert np.abs(s.gt_ne[:, 1]).max() < 0.05 * s.gt_ne[:, 0].max()
    ll = phone_georef(s).ne_to_lonlat(s.gt_ne)
    assert np.allclose(ll[:, 0], lon, atol=1e-6)                 # lon recovered
    assert np.allclose(ll[:, 1], lat, atol=1e-6)                 # lat recovered


def test_phone_session_has_no_strides(tmp_path):
    s = load_phone(_make_export(tmp_path))
    assert s.stride_t.size == 0 and s.stride_len.size == 0
    with pytest.raises(ValueError, match="strides"):
        heading_only_reference(s)


def test_zero_gravity_stream_is_rejected(tmp_path):
    # A broken (all-zero) gravity stream reconstructs to ~0 specific force; reject it.
    d = _make_export(tmp_path)
    g = pd.read_csv(d / "Gravity.csv")
    g[["x", "y", "z"]] = 0.0
    g.to_csv(d / "Gravity.csv", index=False)
    with pytest.raises(ValueError, match="9.81|magnitude"):
        load_phone(d)
