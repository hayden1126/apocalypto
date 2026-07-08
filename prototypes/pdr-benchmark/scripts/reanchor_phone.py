"""Phone-walk re-anchor sweep + loop closure, without circular GPS scoring.

The phone GPS is both the scoring reference and the re-anchor source, so a track
re-anchored to GPS must not be scored against the same fixes. Two honest reads:
  - loop closure (GPS-free): open-loop end vs start of a closed walk (true = 0).
  - held-out re-anchor cadence curve: anchor at each interval, score only at the
    mid-cadence times that never pinned the track. Residuals ride a ~3-10 m GPS
    floor, so treat only errors well above it as real (the ~20-30 m kill threshold
    clears it). See STATUS.md / the step-2 plan for the coupling.

Usage: PYTHONPATH=. .venv/bin/python scripts/reanchor_phone.py <export_dir> [--name N] [--k K]
Writes out/<name>_reanchor_curve.png.
"""
import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from pdr_bench.eval.phone_metrics import heldout_reanchor_rmse, loop_closure_error  # noqa: E402
from pdr_bench.io.phone import load_phone  # noqa: E402
from pdr_bench.pdr.pipeline import run_pdr  # noqa: E402
from pdr_bench.pdr.reanchor import reanchored_track  # noqa: E402

INTERVALS = [np.inf, 300.0, 120.0, 60.0, 30.0, 15.0]
TRUSTED_ACC_M = 8.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir")
    ap.add_argument("--name", default="phone")
    ap.add_argument("--k", type=float, default=None,
        help="fixed Weinberg k (from a measured calibration leg); default GPS-calibrated")
    a = ap.parse_args()

    s = load_phone(a.export_dir, name=a.name)
    r = run_pdr(s, use_mag=False, k=a.k)

    # gate to trusted GPS fixes (mimics the "trusted fix" premise)
    acc = s.meta["gps_horizontal_acc_m"]
    keep = acc < TRUSTED_ACC_M
    gnss_t, gnss_ne = s.gt_t[keep], s.gt_ne[keep]
    print(f"{a.name}: {int(keep.sum())}/{len(acc)} GPS fixes trusted "
          f"(<{TRUSTED_ACC_M:g} m); Weinberg k={r.k:.3f} "
          f"({'fixed' if a.k is not None else 'gps-calibrated'})")

    # loop closure (GPS-free): open-loop end vs start of a closed walk
    open_track = reanchored_track(r.step_t, r.step_len, r.raw_heading,
                                  gnss_t, gnss_ne, np.inf)
    closure = loop_closure_error(open_track)
    print(f"loop closure (open-loop end vs start): {closure:.1f} m "
          f"({100 * closure / s.gt_path_length:.1f}% of {s.gt_path_length:.0f} m walk)")

    # held-out re-anchor cadence curve
    print(f"\n{'interval_s':>10} {'heldout_rmse_m':>14}")
    print("-" * 26)
    finite, vals = [], []
    for iv in INTERVALS:
        rmse = heldout_reanchor_rmse(r.step_t, r.step_len, r.raw_heading,
                                     gnss_t, gnss_ne, iv)
        print(f"{'inf' if np.isinf(iv) else int(iv):>10} {rmse:14.1f}")
        if np.isfinite(iv):
            finite.append(iv)
            vals.append(rmse)

    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.plot(finite, vals, "o-", label=f"{a.name} ({int(s.gt_path_length)} m)")
    ax.axhline(TRUSTED_ACC_M, color="0.6", ls="--", lw=1,
               label=f"{TRUSTED_ACC_M:g} m (GPS floor)")
    ax.axhline(25, color="0.4", ls=":", lw=1, label="25 m (street-width kill line)")
    ax.set_xlabel("GNSS re-anchor interval (s)")
    ax.set_ylabel("held-out residual RMSE vs GPS (m)")
    ax.set_title("Phone PDR held-out drift vs GNSS re-anchor interval")
    ax.invert_xaxis()
    ax.legend(fontsize=8)
    fig.savefig(f"out/{a.name}_reanchor_curve.png", dpi=110, bbox_inches="tight")
    print(f"\nwrote out/{a.name}_reanchor_curve.png")


if __name__ == "__main__":
    main()
