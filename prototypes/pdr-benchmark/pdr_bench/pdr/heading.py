"""Heading (yaw) estimation via an AHRS attitude filter.

The magnetometer stream (magnetic.csv) is already the normalized Earth field, so it
is used as-is; the dataset's Ainv/Bias belong to the raw ADC domain and must not be
re-applied here. Gyro bias from the static phase is removed before integration; with
use_mag=False the estimate is gyro+accel only (isolates gyro drift), which lets the
harness measure whether the magnetometer actually helps.
"""
import numpy as np
from ahrs.filters import Madgwick


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
) -> np.ndarray:
    """Per-sample compass heading (rad from North, CW toward East) on a uniform grid.

    The AHRS filter reports yaw in an ENU frame (CCW from East); negating it converts
    the rotational sense to a compass bearing. The remaining absolute offset (frame +
    magnetic declination) is fixed downstream by start-pose alignment."""
    gyr = gyro - gyro_bias
    if use_mag:
        f = Madgwick(gyr=gyr, acc=accel, mag=mag, frequency=fs)
    else:
        f = Madgwick(gyr=gyr, acc=accel, frequency=fs)
    return -_yaw_from_quat(f.Q)
