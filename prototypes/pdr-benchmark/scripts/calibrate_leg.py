"""Derive the honest Weinberg step-length gain k from a measured calibration leg.

The protocol walks a known distance (e.g. a hydrant->lamppost leg read off satellite
imagery) as the FIRST thing after the opening static, ending with a brief deliberate
stop, so the leg is the first sustained run of detected steps, terminated by a pause
(a large inter-step gap). k is then

    k = known_distance / sum_over_leg_steps (a_max - a_min)^(1/4)

reusing the same weinberg_base / calibrate_k primitives the pipeline uses (pdr/step_length.py).
Never GPS-calibrate k for the headline: GPS path inflation (jitter + outliers) biases it high
(the 595 m shakedown: honest 0.537 vs GPS-calibrated 0.679, a 1.27x inflation).

Usage: PYTHONPATH=. .venv/bin/python scripts/calibrate_leg.py <export_dir> \
           --distance 15.9 [--steps 13] [--pause-s 1.2] [--min-run 5]
"""
import argparse

import numpy as np

from pdr_bench.io.phone import load_phone
from pdr_bench.pdr.preprocess import common_grid, resample
from pdr_bench.pdr.step_length import calibrate_k, weinberg_base
from pdr_bench.pdr.steps import Steps, detect_steps


def _first_walking_run(step_t: np.ndarray, pause_s: float, min_run: int) -> tuple[int, int]:
    """Return (start, end) inclusive step indices of the first sustained walking run.

    A run is a maximal block of consecutive steps whose inter-step gaps are all
    < pause_s; the first such run with >= min_run steps is the calibration leg,
    and the gap that ends it is the deliberate stop."""
    gaps = np.diff(step_t)
    walking = gaps < pause_s          # gaps[i] links step i -> i+1
    start = None
    for i in range(len(walking)):
        if walking[i]:
            if start is None:
                start = i             # step i begins a run
        else:
            if start is not None and (i - start + 1) >= min_run:
                return start, i       # run is steps[start .. i] (gap i ends it)
            start = None
    # run extends to the end (no terminating pause found)
    if start is not None and (len(step_t) - start) >= min_run:
        return start, len(step_t) - 1
    raise ValueError("no sustained walking run found; loosen --pause-s or --min-run")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir")
    ap.add_argument("--distance", type=float, required=True,
        help="measured calibration-leg distance, m")
    ap.add_argument("--steps", type=int, default=None,
        help="expected footfall count for the leg (asserted against the detection)")
    ap.add_argument("--pause-s", type=float, default=1.2,
        help="inter-step gap (s) that counts as the deliberate stop ending the leg")
    ap.add_argument("--min-run", type=int, default=5,
        help="minimum steps for the first run to count as the calibration leg")
    ap.add_argument("--fs", type=float, default=100.0)
    a = ap.parse_args()

    s = load_phone(a.export_dir, name="cal")
    grid = common_grid(s, a.fs)
    accel = resample(s.accel_t, s.accel, grid)
    accel_mag = np.hypot(np.hypot(accel[:, 0], accel[:, 1]), accel[:, 2])
    steps = detect_steps(grid, accel_mag, a.fs)

    start, end = _first_walking_run(steps.t, a.pause_s, a.min_run)
    n_leg = end - start + 1
    leg = Steps(idx=steps.idx[start:end + 1], t=steps.t[start:end + 1],
                a_max=steps.a_max[start:end + 1], a_min=steps.a_min[start:end + 1])
    k = calibrate_k(leg, a.distance)

    gaps = np.diff(steps.t)
    pause_gap = gaps[end] if end < len(gaps) else float("nan")
    mean_step = a.distance / n_leg
    k_gps = calibrate_k(steps, s.gt_path_length)   # contrast only; never the headline

    print(f"calibration leg on {a.export_dir}")
    print(f"  detected steps total: {len(steps.t)}  (motion onset ~{steps.t[start]:.1f} s)")
    print(f"  first walking run:    steps {start}..{end}  ({n_leg} footfalls)")
    print(f"  leg spans:            {steps.t[start]:.1f} .. {steps.t[end]:.1f} s "
          f"({steps.t[end] - steps.t[start]:.1f} s), then a {pause_gap:.1f} s pause")
    print(f"  mean step length:     {mean_step:.3f} m  ({a.distance:.1f} m / {n_leg} steps)")
    print(f"  sum weinberg_base:    {weinberg_base(leg).sum():.4f}")
    print(f"  --> honest k = {k:.4f}")
    print(f"  (contrast) GPS-calibrated k over full track = {k_gps:.4f} "
          f"[inflated by GPS jitter; DO NOT use for the headline]")

    # first few inter-step gaps, so the leg boundary is auditable
    print("\n  first 20 inter-step gaps (s), leg ends at the flagged pause:")
    for i in range(min(20, len(gaps))):
        flag = "  <-- pause (leg end)" if i == end else ""
        print(f"    step {i:2d}->{i+1:2d}: {gaps[i]:.2f}{flag}")

    if a.steps is not None and n_leg != a.steps:
        print(f"\n  WARNING: detected {n_leg} footfalls but you counted {a.steps}. "
              f"Check the pause threshold (--pause-s) / step detection before trusting k.")
    elif a.steps is not None:
        print(f"\n  OK: detected footfalls ({n_leg}) match your count ({a.steps}).")


if __name__ == "__main__":
    main()
