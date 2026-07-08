"""Heading (yaw) estimation via an AHRS attitude filter.

The magnetometer stream (magnetic.csv) is already the normalized Earth field, so it
is used as-is; the dataset's Ainv/Bias belong to the raw ADC domain and must not be
re-applied here. Gyro bias from the static phase is removed before integration; with
use_mag=False the estimate is gyro+accel only (isolates gyro drift), which lets the
harness measure whether the magnetometer actually helps.
"""
import numpy as np
from ahrs.common.orientation import ecompass
from ahrs.filters import Madgwick

from pdr_bench.pdr.mag_gate import magnetic_gate, magnetic_reference

MARG_GAIN = 0.041   # ahrs Madgwick's default MARG beta (gain_marg)


def _yaw_from_quat(q: np.ndarray) -> np.ndarray:
    """Rotation about vertical (rad) from [w,x,y,z] quaternions (ENU, CCW from East)."""
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    return np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def estimate_yaw(accel: np.ndarray,
    gyro: np.ndarray,
    mag: np.ndarray,
    fs: float,
    gyro_bias: np.ndarray,
    use_mag: bool = True,
    mag_gate_tol: tuple[float, float] | None = None,
    static_seconds: float = 35.0,
) -> np.ndarray:
    """Per-sample compass heading (rad from North, CW toward East) on a uniform grid.

    The AHRS filter reports yaw in an ENU frame (CCW from East); negating it converts
    the rotational sense to a compass bearing. The remaining absolute offset (frame +
    magnetic declination) is fixed downstream by start-pose alignment. With mag_gate_tol
    = (mag_tol, dip_tol_rad), the magnetometer is fused only where the field passes the
    disturbance gate (gated MARG); otherwise use_mag selects batch MARG or gyro+accel."""
    gyr = gyro - gyro_bias
    if mag_gate_tol is not None:
        return _gated_yaw(accel, gyr, mag, fs, mag_gate_tol, static_seconds)
    if use_mag:
        f = Madgwick(gyr=gyr, acc=accel, mag=mag, frequency=fs)
    else:
        f = Madgwick(gyr=gyr, acc=accel, frequency=fs)
    return -_yaw_from_quat(f.Q)


def _gated_yaw(accel: np.ndarray,
    gyr: np.ndarray,
    mag: np.ndarray,
    fs: float,
    mag_gate_tol: tuple[float, float],
    static_seconds: float,
) -> np.ndarray:
    """Per-sample MARG/IMU switch: fuse mag only where the field passes the gate.

    Matches batch MARG (ecompass init + MARG_GAIN) when every sample is accepted, so it
    reduces exactly to naive MARG in the clean-field limit."""
    mag_tol, dip_tol = mag_gate_tol
    n = len(gyr)
    static = np.arange(n) < int(static_seconds * fs)
    m_ref, dip_ref = magnetic_reference(mag, accel, static)
    accept = magnetic_gate(mag, accel, m_ref, dip_ref, mag_tol, dip_tol)
    f = Madgwick(frequency=fs, gain=MARG_GAIN)
    q = np.zeros((n, 4))
    q[0] = ecompass(accel[0], mag[0], frame="NED", representation="quaternion")
    for t in range(1, n):
        if accept[t]:
            q[t] = f.updateMARG(q[t - 1], gyr[t], accel[t], mag[t])
        else:
            q[t] = f.updateIMU(q[t - 1], gyr[t], accel[t])
    return -_yaw_from_quat(q)
