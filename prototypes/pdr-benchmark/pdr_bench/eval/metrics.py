"""Trajectory accuracy metrics against a time-aligned reference."""
import numpy as np

from pdr_bench.eval.geo import decompose_error


def trajectory_metrics(track: np.ndarray,
    ref: np.ndarray,
    path_length: float,
) -> dict:
    """Positional error metrics for a track vs a time-aligned reference (both (N,2) NE).

    Returns RMSE/mean/median/max positioning error, CEP50/CEP95, cross-track
    mean/P95, and final/max drift as a fraction of path length. Standard PDR and
    navigation metrics (RMSE, CEP, cross-track, drift-%-of-distance)."""
    radial = np.hypot(*(track - ref).T)
    cross, _ = decompose_error(track, ref)
    abs_cross = np.abs(cross)
    return {
        "n": int(len(track)),
        "path_length_m": float(path_length),
        "rmse_m": float(np.sqrt(np.mean(radial ** 2))),
        "mean_err_m": float(radial.mean()),
        "median_err_m": float(np.median(radial)),
        "max_err_m": float(radial.max()),
        "cep50_m": float(np.percentile(radial, 50)),
        "cep95_m": float(np.percentile(radial, 95)),
        "cross_track_mean_m": float(abs_cross.mean()),
        "cross_track_p95_m": float(np.percentile(abs_cross, 95)),
        "final_drift_pct": float(100.0 * radial[-1] / path_length),
        "max_drift_pct": float(100.0 * radial.max() / path_length),
    }
