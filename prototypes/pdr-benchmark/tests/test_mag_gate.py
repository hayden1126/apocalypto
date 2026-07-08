"""Tests for the magnetic-disturbance gate and its gated heading fusion."""
import numpy as np

from pdr_bench.pdr.heading import estimate_yaw
from pdr_bench.pdr.mag_gate import magnetic_gate, magnetic_reference

UP = np.array([0.0, 0.0, 9.81])


def _clean_field(n, dip_deg=60.0):
    """Unit field at a fixed dip (angle from up), constant over n samples."""
    d = np.radians(dip_deg)
    return np.tile([np.sin(d), 0.0, np.cos(d)], (n, 1)).astype(float)


def test_reference_from_static_window():
    n = 100
    accel = np.tile(UP, (n, 1))
    mag = _clean_field(n, dip_deg=60.0)
    m_ref, dip_ref = magnetic_reference(mag, accel, np.ones(n, bool))
    assert np.isclose(m_ref, 1.0, atol=1e-6)
    assert np.isclose(dip_ref, np.radians(60.0), atol=1e-6)


def test_gate_accepts_clean_rejects_disturbed():
    n = 100
    accel = np.tile(UP, (n, 1))
    mag = _clean_field(n, dip_deg=60.0)
    static = np.arange(n) < 30
    m_ref, dip_ref = magnetic_reference(mag, accel, static)
    mag[50:60] *= 1.5                                   # magnitude spike (dip unchanged)
    mag[70:80] = _clean_field(10, dip_deg=30.0)         # dip tilt (magnitude unchanged)
    accept = magnetic_gate(mag, accel, m_ref, dip_ref,
                           mag_tol=0.15, dip_tol=np.radians(10.0))
    assert accept[:50].all()
    assert not accept[50:60].any()                      # rejected on magnitude
    assert not accept[70:80].any()                      # rejected on dip
    assert accept[85:].all()


def test_stray_ferrous_field_is_rejected():
    # A stray field added by nearby ferrous metal shifts magnitude, dip AND heading.
    n = 100
    accel = np.tile(UP, (n, 1))
    mag = _clean_field(n, dip_deg=60.0)
    m_ref, dip_ref = magnetic_reference(mag, accel, np.arange(n) < 30)
    mag[40:60] += np.array([0.6, 0.6, 0.3])
    accept = magnetic_gate(mag, accel, m_ref, dip_ref,
                           mag_tol=0.15, dip_tol=np.radians(10.0))
    assert not accept[40:60].any()
    assert accept[:40].all() and accept[60:].all()


def test_gated_all_accept_matches_naive_marg():
    # A wide-open gate accepts every sample, so gated fusion must reproduce naive MARG.
    n, fs = 500, 100.0
    gyro = np.tile([0.0, 0.0, 0.2], (n, 1))
    accel = np.tile(UP, (n, 1))
    mag = _clean_field(n, dip_deg=60.0)
    naive = estimate_yaw(accel, gyro, mag, fs, np.zeros(3), use_mag=True)
    gated = estimate_yaw(accel, gyro, mag, fs, np.zeros(3),
                         mag_gate_tol=(10.0, np.radians(180.0)))
    assert np.allclose(naive, gated, atol=1e-9)


def _rotating_field(n, fs, yaw_rate, dip_deg=60.0):
    """Body-frame magnetometer for a device yawing at yaw_rate (rad/s) in a clean field."""
    theta = yaw_rate * np.arange(n) / fs                 # device yaw over time
    d = np.radians(dip_deg)
    h = np.sin(d)                                        # horizontal field magnitude
    # the measured field rotates by -theta in the body frame as the device yaws by +theta
    return np.column_stack([h * np.cos(-theta), h * np.sin(-theta), np.full(n, np.cos(d))])


def test_gated_beats_naive_under_stray_field():
    # A rotating device: the magnetometer actually drives heading. A stray ferrous field
    # mid-run pulls naive MARG off the true (gyro-driven) heading; gated rejects it.
    n, fs, rate = 6000, 100.0, 0.05
    gyro = np.tile([0.0, 0.0, rate], (n, 1))
    accel = np.tile(UP, (n, 1))
    clean = _rotating_field(n, fs, rate)
    disturbed = clean.copy()
    disturbed[4000:5000] += np.array([0.7, 0.7, 0.4])    # detectable stray field
    truth = np.unwrap(estimate_yaw(accel, gyro, clean, fs, np.zeros(3), use_mag=True))
    naive = np.unwrap(estimate_yaw(accel, gyro, disturbed, fs, np.zeros(3), use_mag=True))
    gated = np.unwrap(estimate_yaw(accel, gyro, disturbed, fs, np.zeros(3),
                                   mag_gate_tol=(0.15, np.radians(10.0))))
    err_naive = abs(naive[4900] - truth[4900])
    err_gated = abs(gated[4900] - truth[4900])
    assert err_naive > np.radians(4.0)                   # naive is genuinely corrupted
    assert err_gated < 0.25 * err_naive                  # gating removes most of it


def test_gated_all_reject_falls_back_to_gyro():
    # dip_tol < 0 rejects every sample, so gated fusion must evolve like gyro + accel only.
    n, fs = 500, 100.0
    gyro = np.tile([0.0, 0.0, 0.1], (n, 1))
    accel = np.tile(UP, (n, 1))
    mag = _clean_field(n)
    gyro_only = estimate_yaw(accel, gyro, mag, fs, np.zeros(3), use_mag=False)
    reject = estimate_yaw(accel, gyro, mag, fs, np.zeros(3), mag_gate_tol=(10.0, -1.0))
    assert np.allclose(np.diff(gyro_only), np.diff(reject), atol=1e-9)
