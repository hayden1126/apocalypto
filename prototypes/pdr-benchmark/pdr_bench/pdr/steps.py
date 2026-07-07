"""Step detection from accelerometer magnitude."""
from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks


@dataclass
class Steps:
    """Detected steps on a uniform grid."""
    idx: np.ndarray      # (Ns,) indices into the grid
    t: np.ndarray        # (Ns,) step times, s
    a_max: np.ndarray    # (Ns,) per-step max of accel magnitude (raw)
    a_min: np.ndarray    # (Ns,) per-step min of accel magnitude (raw)


def _bandpass(x: np.ndarray,
    fs: float,
    fmin: float,
    fmax: float,
) -> np.ndarray:
    """Zero-phase band-pass to isolate the walking cadence band."""
    b, a = butter(2, [fmin, fmax], btype="band", fs=fs)
    return filtfilt(b, a, x)


def detect_steps(t_grid: np.ndarray,
    accel_mag: np.ndarray,
    fs: float,
    fmin: float = 0.6,
    fmax: float = 3.0,
    min_step_s: float = 0.3,
) -> Steps:
    """Detect steps as peaks of the band-passed accel magnitude.

    Adaptive height (fraction of the signal's std) plus a refractory min-distance
    reject noise and double-counts. Per-step accel extrema are taken from the raw
    magnitude over the window ending at each peak, for Weinberg step length.
    """
    filt = _bandpass(accel_mag, fs, fmin, fmax)
    height = 0.3 * np.std(filt)
    distance = max(1, int(min_step_s * fs))
    idx, _ = find_peaks(filt, height=height, distance=distance)
    a_max = np.empty(len(idx))
    a_min = np.empty(len(idx))
    prev = 0
    for i, p in enumerate(idx):
        seg = accel_mag[prev:p + 1] if p > prev else accel_mag[p:p + 1]
        a_max[i] = seg.max()
        a_min[i] = seg.min()
        prev = p
    return Steps(idx=idx, t=t_grid[idx], a_max=a_max, a_min=a_min)
