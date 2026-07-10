"""Adapter tests for phone sensor-logger exports (Sensor Logger format).

Deterministic-core: synthetic per-sensor CSVs pin the two risky conversions
(gravity reconstruction, GPS -> local NE) and the phone-session contract (no
foot-mounted strides). Sensor Logger `time` is Unix-epoch nanoseconds, so the
timestamp test also guards the integer-domain rebasing that keeps sub-ms precision.
The cross-platform frame tests pin the iOS/Android sign-convention normalization.
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


def _make_export(tmp_path, *, imu_offset_s=0.0, lat=None, lon=None,
                 platform="ios", standardisation=False,
                 grav_z=-9.81, write_metadata=True, total_accel=None):
    """Build a minimal well-formed Sensor Logger export dir; return its path.

    The base physical motion is defined in the iOS export convention (gravity -z when
    held flat). platform="android" or standardisation=True writes the same motion in the
    Android convention (Accelerometer and Gravity negated on all three axes; Gyroscope
    unchanged). total_accel in {None, "consistent", "corrupt"} controls the Android-only
    TotalAcceleration.csv. write_metadata=False omits Metadata.csv (legacy export).
    """
    d = tmp_path / "export"
    d.mkdir(parents=True)
    n, fs, ng2 = 200, 100.0, 100
    imu_t0 = EPOCH_NS + int(imu_offset_s * 1e9)
    android_frame = (platform == "android") or standardisation
    sign = -1.0 if android_frame else 1.0
    # linear accel ~0 (at rest); raw specific force is dominated by gravity on z
    _write_sensor(d / "Accelerometer.csv", imu_t0, fs, n,
                  {"x": np.zeros(n), "y": np.zeros(n), "z": np.zeros(n)})
    # gravity on a different (50 Hz) grid to exercise the resample-onto-accel_t path
    _write_sensor(d / "Gravity.csv", imu_t0, 50.0, ng2,
                  {"x": np.zeros(ng2), "y": np.zeros(ng2),
                   "z": np.full(ng2, sign * grav_z)})
    _write_sensor(d / "Gyroscope.csv", imu_t0, fs, n,
                  {"x": np.zeros(n), "y": np.zeros(n), "z": np.full(n, 0.1)})
    _write_sensor(d / "Magnetometer.csv", imu_t0, fs, n,
                  {"x": np.full(n, 22.0), "y": np.zeros(n), "z": np.full(n, -40.0)})
    if total_accel is not None:
        # Android raw accel incl. gravity, in the export's own convention
        tot_z = sign * grav_z if total_accel == "consistent" else 0.0
        _write_sensor(d / "TotalAcceleration.csv", imu_t0, fs, n,
                      {"x": np.zeros(n), "y": np.zeros(n), "z": np.full(n, tot_z)})
    if write_metadata:
        pd.DataFrame({"platform": [platform],
                      "standardisation": [str(standardisation).lower()],
                      "appVersion": ["1.60.1"]}).to_csv(d / "Metadata.csv", index=False)
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
    # iOS reads gravity as -z when flat, so reconstructed specific force is -9.81 on z.
    s = load_phone(_make_export(tmp_path))
    assert np.allclose(s.accel[:, 2], -9.81, atol=1e-6)
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


# --- cross-platform frame normalization (Android P30 <-> iOS) ---

def test_android_frame_is_normalized_to_ios(tmp_path):
    # Android reads Accelerometer + Gravity with the opposite sign on all three axes;
    # the loader flips them so reconstructed specific force matches the iOS -9.81 z.
    s = load_phone(_make_export(tmp_path, platform="android", total_accel="consistent"))
    assert np.allclose(s.accel[:, 2], -9.81, atol=1e-6)
    assert s.meta["frame"] == "android"
    assert s.meta["frame_flipped"] is True
    assert s.meta["platform"] == "android"


def test_ios_and_android_load_identically(tmp_path):
    # the same physical motion in the two export conventions must load to identical arrays
    ios = load_phone(_make_export(tmp_path / "a", platform="ios"))
    andr = load_phone(_make_export(tmp_path / "b", platform="android",
                                   total_accel="consistent"))
    assert np.allclose(ios.accel, andr.accel, atol=1e-9)
    assert np.allclose(ios.gyro, andr.gyro, atol=1e-9)   # gyro shares one convention


def test_fallback_detection_via_total_acceleration(tmp_path):
    # no Metadata.csv, but the Android-only TotalAcceleration.csv marks the frame
    s = load_phone(_make_export(tmp_path, platform="android", write_metadata=False,
                                total_accel="consistent"))
    assert s.meta["frame"] == "android"
    assert np.allclose(s.accel[:, 2], -9.81, atol=1e-6)


def test_standardised_ios_treated_as_android_frame(tmp_path):
    # an iOS export with the in-app "Standardise Units & Frames" toggle ON is already in
    # the Android convention, so it must be flipped too
    s = load_phone(_make_export(tmp_path, platform="ios", standardisation=True))
    assert s.meta["frame"] == "android"
    assert s.meta["frame_flipped"] is True
    assert np.allclose(s.accel[:, 2], -9.81, atol=1e-6)


def test_corrupt_total_acceleration_rejected(tmp_path):
    # TotalAcceleration that disagrees with Accelerometer + Gravity signals bad semantics
    with pytest.raises(ValueError, match="TotalAcceleration|disagree"):
        load_phone(_make_export(tmp_path, platform="android", total_accel="corrupt"))


def test_legacy_layout_defaults_to_ios_frame(tmp_path):
    # no Metadata, no TotalAcceleration -> iOS frame, no flip (back-compat)
    s = load_phone(_make_export(tmp_path, platform="ios", write_metadata=False))
    assert s.meta["frame"] == "ios"
    assert s.meta["frame_flipped"] is False
    assert np.allclose(s.accel[:, 2], -9.81, atol=1e-6)


def test_unknown_platform_rejected(tmp_path):
    with pytest.raises(ValueError, match="platform"):
        load_phone(_make_export(tmp_path, platform="symbian"))


def test_imu_rate_hz_reported(tmp_path):
    s = load_phone(_make_export(tmp_path))
    assert abs(s.meta["imu_rate_hz"] - 100.0) < 1.0
