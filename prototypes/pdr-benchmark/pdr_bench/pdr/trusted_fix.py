"""Select trustworthy GNSS fixes for re-anchoring, offline and position-domain.

The re-anchor loop assumes every fix it is handed is trusted, so the honest gate lives
here. Two mechanisms plus a backstop (see PLAN.md A2):
  - Mechanism 1: an outlier / consistency gate. A causal max-walking-speed jump vs the
    last accepted fix catches gross faults (the ma_ling 808 m teleport) with no PDR and
    no raw GNSS. Optionally (opt-in) an IMU/PDR-vs-GNSS innovation gate, gated on the
    residual distribution because open-loop PDR itself drifts. Neither bounds a slow
    correlated bias (urban multipath, a slow spoof): that is the degrade-to-dead-
    reckoning case the uncertainty cone owns, not a detector.
  - Mechanism 2: cold-start trim. Receiver lock is detected from fix DISPERSION, not the
    reported accuracy (iOS reported 8.9 m at 1.2 m actual scatter), then pre-lock fixes
    are dropped.
  - Backstop: a loose reported-accuracy floor. iOS accuracy is ~7x pessimistic (14 m
    reported ~= 1-2 m actual), so it only rejects absurd self-flagged values, never the
    usable-but-pessimistic fixes the old acc < 8 m gate starved the loop on.
"""
import warnings

import numpy as np

from pdr_bench.eval.geo import interp_ne


def _lock_time(gnss_t: np.ndarray,
    gnss_ne: np.ndarray,
    lock_window: int,
    lock_disp_m: float,
    max_gap_s: float,
    max_cold_s: float,
) -> float:
    """First fix time whose forward window is tight (radius < lock_disp_m) AND contiguous.

    Falls back to gnss_t[0] (trim nothing) if no such window exists in the opening."""
    n = len(gnss_t)
    if n <= lock_window:
        return float(gnss_t[0])
    for i in range(n - lock_window + 1):
        if gnss_t[i] - gnss_t[0] > max_cold_s:
            break
        win = gnss_ne[i:i + lock_window]
        radius = float(np.hypot(*(win - win.mean(0)).T).max())
        span = float(gnss_t[i + lock_window - 1] - gnss_t[i])
        if radius < lock_disp_m and span < lock_window * max_gap_s:
            return float(gnss_t[i])
    return float(gnss_t[0])


def _speed_keep(gnss_t: np.ndarray,
    gnss_ne: np.ndarray,
    max_speed_mps: float,
    start: int,
) -> np.ndarray:
    """Causal jump gate: reject a fix implying > max_speed_mps vs the last ACCEPTED fix."""
    keep = np.ones(len(gnss_t), bool)
    j = start
    for i in range(start + 1, len(gnss_t)):
        dt = gnss_t[i] - gnss_t[j]
        if dt > 0 and np.hypot(*(gnss_ne[i] - gnss_ne[j])) / dt > max_speed_mps:
            keep[i] = False           # reject; do not advance the reference
        else:
            j = i
    return keep


def trusted_fix_mask(gnss_t: np.ndarray,
    gnss_ne: np.ndarray,
    reported_acc_m: np.ndarray | None = None,
    *,
    max_speed_mps: float = 5.0,
    lock_window: int = 8,
    lock_disp_m: float = 5.0,
    max_gap_s: float = 6.0,
    max_cold_s: float = 120.0,
    acc_backstop_m: float | None = 50.0,
    pdr_t: np.ndarray | None = None,
    pdr_ne: np.ndarray | None = None,
    use_innovation: bool = False,
    innovation_sigma: float = 5.0,
    innovation_floor_m: float = 15.0,
    min_fixes: int = 2,
) -> np.ndarray:
    """Boolean keep-mask over (gnss_t, gnss_ne) for re-anchoring. See module docstring."""
    n = len(gnss_t)
    if n == 0:
        return np.zeros(0, bool)

    t_lock = _lock_time(gnss_t, gnss_ne, lock_window, lock_disp_m, max_gap_s, max_cold_s)
    keep_cold = gnss_t >= t_lock
    # seed the speed gate at the first post-lock fix so cold-start scatter cannot poison it
    keep_speed = _speed_keep(gnss_t, gnss_ne, max_speed_mps, int(np.argmax(keep_cold)))

    if acc_backstop_m is None or reported_acc_m is None:
        keep_acc = np.ones(n, bool)
    else:
        keep_acc = np.asarray(reported_acc_m, float) < acc_backstop_m

    if use_innovation and pdr_t is not None and pdr_ne is not None:
        res = np.hypot(*(gnss_ne - interp_ne(pdr_t, pdr_ne, gnss_t)).T)
        mad = float(np.median(np.abs(res - np.median(res))))
        thr = max(float(np.median(res)) + innovation_sigma * 1.4826 * mad, innovation_floor_m)
        keep_innov = res <= thr
    else:
        keep_innov = np.ones(n, bool)

    keep = keep_cold & keep_speed & keep_acc & keep_innov
    if keep.sum() >= min_fixes:
        return keep
    # graceful degradation: never hand reanchored_track a starved track
    for dropped, relaxed in (("innovation", keep_cold & keep_speed & keep_acc),
                             ("speed", keep_cold & keep_acc),
                             ("cold-start", keep_acc),
                             ("all filters", np.ones(n, bool))):
        if relaxed.sum() >= min_fixes:
            warnings.warn(f"trusted_fix_mask: only {int(keep.sum())} fixes passed; "
                          f"relaxed past {dropped} to keep {int(relaxed.sum())}")
            return relaxed
    warnings.warn(f"trusted_fix_mask: only {n} fixes total, below min_fixes={min_fixes}")
    return np.ones(n, bool)
