"""End-to-end PDR: resample -> steps -> heading -> step length -> dead reckon.

run_pdr is the full pipeline (detected steps, Weinberg length, estimated heading).
heading_only_reference isolates heading error by feeding the ground-truth stride
instants and lengths, so the two together attribute error to heading vs step model.
"""
from dataclasses import dataclass

import numpy as np

from pdr_bench.eval.geo import interp_ne, path_length
from pdr_bench.eval.metrics import trajectory_metrics
from pdr_bench.io.session import ImuSession
from pdr_bench.pdr.heading import estimate_yaw
from pdr_bench.pdr.integrate import align_start_pose, dead_reckon
from pdr_bench.pdr.preprocess import common_grid, estimate_gyro_bias, resample
from pdr_bench.pdr.step_length import calibrate_k, weinberg_lengths
from pdr_bench.pdr.steps import detect_steps


@dataclass
class PdrResult:
    """A dead-reckoned track aligned to ground truth, with error metrics."""
    label: str
    t: np.ndarray          # (M,) position times, s
    ne: np.ndarray         # (M, 2) PDR track, start-pose aligned
    gt_ne: np.ndarray      # (M, 2) ground truth at the same times
    metrics: dict
    k: float
    heading_offset: float
    n_steps: int
    step_t: np.ndarray = None       # (Ns,) per-step times, s
    step_len: np.ndarray = None     # (Ns,) per-step lengths, m
    raw_heading: np.ndarray = None  # (Ns,) per-step compass heading, pre-alignment


def _walked_path_length(session: ImuSession,
    t0: float,
    t1: float,
) -> float:
    """Ground-truth path length over the walked time span."""
    m = (session.gt_t >= t0) & (session.gt_t <= t1)
    return path_length(session.gt_ne[m])


def run_pdr(session: ImuSession,
    fs: float = 100.0,
    use_mag: bool = True,
    k: float | None = None,
    mag_gate_tol: tuple[float, float] | None = None,
) -> PdrResult:
    """Full PDR pipeline; k is Weinberg gain (calibrated to gt distance if None).

    mag_gate_tol = (mag_tol, dip_tol_rad) selects gated MARG heading (see estimate_yaw)."""
    grid = common_grid(session, fs)
    accel = resample(session.accel_t, session.accel, grid)
    gyro = resample(session.gyro_t, session.gyro, grid)
    mag = resample(session.mag_t, session.mag, grid)
    gyro_bias = estimate_gyro_bias(session)

    accel_mag = np.hypot(np.hypot(accel[:, 0], accel[:, 1]), accel[:, 2])
    steps = detect_steps(grid, accel_mag, fs)
    yaw = estimate_yaw(accel, gyro, mag, fs, gyro_bias, use_mag, mag_gate_tol)
    step_yaw = yaw[steps.idx]

    if k is None:
        k = calibrate_k(steps, session.gt_path_length)
    lengths = weinberg_lengths(steps, k)

    dt0 = steps.t[1] - steps.t[0]
    t_pos = np.concatenate([[steps.t[0] - dt0], steps.t])
    gt_pos = interp_ne(session.gt_t, session.gt_ne, t_pos)
    pdr = dead_reckon(lengths, step_yaw, start=tuple(gt_pos[0]))
    aligned, offset = align_start_pose(pdr, gt_pos)

    pl = _walked_path_length(session, t_pos[0], t_pos[-1])
    label = f"PDR ({'gyro+mag' if use_mag else 'gyro-only'})"
    return PdrResult(label=label, t=t_pos, ne=aligned, gt_ne=gt_pos,
                     metrics=trajectory_metrics(aligned, gt_pos, pl),
                     k=k, heading_offset=offset, n_steps=len(steps.idx),
                     step_t=steps.t, step_len=lengths, raw_heading=step_yaw)


def heading_only_reference(session: ImuSession,
    fs: float = 100.0,
    use_mag: bool = True,
    mag_gate_tol: tuple[float, float] | None = None,
) -> PdrResult:
    """Integrate ground-truth stride instants + lengths with estimated heading.

    Removes step-detection and step-length error, leaving heading error alone.
    mag_gate_tol = (mag_tol, dip_tol_rad) selects gated MARG heading (see estimate_yaw)."""
    if session.stride_len.size == 0:
        raise ValueError("heading_only_reference needs foot-mounted strides; "
                         "unavailable for phone sessions")
    grid = common_grid(session, fs)
    accel = resample(session.accel_t, session.accel, grid)
    gyro = resample(session.gyro_t, session.gyro, grid)
    mag = resample(session.mag_t, session.mag, grid)
    gyro_bias = estimate_gyro_bias(session)
    yaw = np.unwrap(estimate_yaw(accel, gyro, mag, fs, gyro_bias, use_mag, mag_gate_tol))

    # drop the leading zero-length stride, then sample heading at each stride instant
    valid = session.stride_len > 0
    st, sl = session.stride_t[valid], session.stride_len[valid]
    stride_yaw = np.interp(st, grid, yaw)

    dt0 = st[1] - st[0]
    t_pos = np.concatenate([[st[0] - dt0], st])
    gt_pos = interp_ne(session.gt_t, session.gt_ne, t_pos)
    track = dead_reckon(sl, stride_yaw, start=tuple(gt_pos[0]))
    aligned, offset = align_start_pose(track, gt_pos)

    pl = _walked_path_length(session, t_pos[0], t_pos[-1])
    label = f"heading-only ({'gyro+mag' if use_mag else 'gyro-only'})"
    return PdrResult(label=label, t=t_pos, ne=aligned, gt_ne=gt_pos,
                     metrics=trajectory_metrics(aligned, gt_pos, pl),
                     k=1.0, heading_offset=offset, n_steps=len(st))
