"""Magnetic-disturbance gate for selective magnetometer fusion.

A magnetometer sample is trustworthy only where the local field still looks like Earth's.
Two signals, both referenced to the clean static opening: the field magnitude, and the dip
(the angle between the field vector and up, from accel). Ferrous disturbance (rebar,
vehicles, steel) shifts one or both. Samples that pass both gates can be fused for absolute
heading; the rest fall back to gyro + accel. A pure horizontal (declination-only) field
rotation preserves magnitude and dip and so is invisible to this gate, but real ferrous
disturbances shift magnitude and inclination together, which this catches.
"""
import numpy as np


def _dip_angles(mag: np.ndarray,
    accel: np.ndarray,
) -> np.ndarray:
    """Per-sample angle (rad) between the magnetometer vector and the accel (up) vector."""
    mn = mag / np.linalg.norm(mag, axis=1, keepdims=True)
    an = accel / np.linalg.norm(accel, axis=1, keepdims=True)
    return np.arccos(np.clip(np.sum(mn * an, axis=1), -1.0, 1.0))


def magnetic_reference(mag: np.ndarray,
    accel: np.ndarray,
    static_mask: np.ndarray,
) -> tuple[float, float]:
    """Reference field magnitude and dip angle (rad) from the static opening."""
    m_ref = float(np.median(np.linalg.norm(mag[static_mask], axis=1)))
    dip_ref = float(np.median(_dip_angles(mag[static_mask], accel[static_mask])))
    return m_ref, dip_ref


def magnetic_gate(mag: np.ndarray,
    accel: np.ndarray,
    m_ref: float,
    dip_ref: float,
    mag_tol: float,
    dip_tol: float,
) -> np.ndarray:
    """Per-sample accept mask: field magnitude near m_ref AND dip near dip_ref.

    mag_tol is a fractional magnitude tolerance; dip_tol is in radians."""
    mag_ok = np.abs(np.linalg.norm(mag, axis=1) - m_ref) <= mag_tol * m_ref
    dip_ok = np.abs(_dip_angles(mag, accel) - dip_ref) <= dip_tol
    return mag_ok & dip_ok
