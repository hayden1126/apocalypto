"""Does a magnetic-disturbance gate rescue the magnetometer for GPS-denied heading?

Step 1 found naive MARG fusion HURT heading (the magnetometer is disturbed by steel and
rebar). This tests whether gating (fuse mag only where the field passes a magnitude + dip
check, else fall back to gyro+accel) turns it into a net positive, on the case that matters:
the fully GPS-denied interior, where no trusted GNSS fix is available to re-anchor.

Three variants, all open-loop (no re-anchor): gyro-only, naive MARG, gated MARG. Metrics
are heading-isolated (via ground-truth strides, so step-length error is removed) and full
open-loop position. Disturbed tracks TEST_01/03 include indoor office/stairs (real magnetic
disturbance); the clean outdoor tracks are the control (gating must not HURT there).

Usage: PYTHONPATH=. .venv/bin/python scripts/mag_gate_experiment.py
Writes out/mag_gate.png.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from pdr_bench.io.geoloc import load_track  # noqa: E402
from pdr_bench.pdr.mag_gate import magnetic_gate, magnetic_reference  # noqa: E402
from pdr_bench.pdr.pipeline import heading_only_reference, run_pdr  # noqa: E402
from pdr_bench.pdr.preprocess import common_grid, resample  # noqa: E402

ROOT = "data/geoloc/Geoloc_ds022023"
DISTURBED = ["TEST_01", "TEST_03"]          # outdoor + indoor office/stairs
CONTROL = ["TEST_02", "TEST_04", "TEST_05", "TEST_06"]   # clean outdoor
MAG_TOLS = [0.05, 0.10, 0.20]
DIP_TOLS_DEG = [5.0, 10.0, 20.0]
REP = (0.10, np.radians(10.0))              # representative threshold for the tables/plot


def gate_acceptance(session, mag_tol, dip_tol, fs=100.0):
    """Fraction of resampled samples the gate accepts."""
    grid = common_grid(session, fs)
    accel = resample(session.accel_t, session.accel, grid)
    mag = resample(session.mag_t, session.mag, grid)
    static = np.arange(len(grid)) < int(35.0 * fs)
    m_ref, dip_ref = magnetic_reference(mag, accel, static)
    return float(magnetic_gate(mag, accel, m_ref, dip_ref, mag_tol, dip_tol).mean())


def heading_rmse(session, **kw):
    return heading_only_reference(session, **kw).metrics["rmse_m"]


def position_rmse(session, **kw):
    return run_pdr(session, **kw).metrics["rmse_m"]


def main():
    tracks = DISTURBED + CONTROL
    rows, best_gated_head = {}, {}
    for tid in tracks:
        s = load_track(ROOT, tid)
        gyro_h = heading_rmse(s, use_mag=False)
        naive_h = heading_rmse(s, use_mag=True)
        rep_h = heading_rmse(s, mag_gate_tol=REP)
        # heading sweep (the decisive metric): min over the threshold grid
        sweep = {(mt, dd): heading_rmse(s, mag_gate_tol=(mt, np.radians(dd)))
                 for mt in MAG_TOLS for dd in DIP_TOLS_DEG}
        best_key = min(sweep, key=sweep.get)
        best_gated_head[tid] = (sweep[best_key], best_key)
        rows[tid] = {
            "accept": gate_acceptance(s, *REP),
            "h_gyro": gyro_h, "h_naive": naive_h, "h_rep": rep_h, "h_best": sweep[best_key],
            "p_gyro": position_rmse(s, use_mag=False),
            "p_naive": position_rmse(s, use_mag=True),
            "p_rep": position_rmse(s, mag_gate_tol=REP),
            "sweep": sweep,
        }
        print(f"processed {tid}")

    # --- main table (heading-isolated + position RMSE, m; rep threshold 0.10 / 10deg) ---
    hdr = (f"\n{'track':9s} {'accept%':>7s} | {'H_gyro':>7s} {'H_naive':>7s} {'H_gate':>7s} "
           f"{'H_best':>7s} | {'P_gyro':>7s} {'P_naive':>7s} {'P_gate':>7s}")
    print(hdr)
    print("-" * len(hdr))
    for tid in tracks:
        r = rows[tid]
        tag = "D" if tid in DISTURBED else " "
        print(f"{tid:7s}{tag}  {100 * r['accept']:6.0f}  | {r['h_gyro']:7.1f} {r['h_naive']:7.1f} "
              f"{r['h_rep']:7.1f} {r['h_best']:7.1f} | {r['p_gyro']:7.1f} {r['p_naive']:7.1f} "
              f"{r['p_rep']:7.1f}")
    print("(H = heading-isolated RMSE, P = open-loop position RMSE; D = disturbed track)")

    # --- heading sweep on the disturbed tracks (does the verdict hinge on threshold?) ---
    print("\nGated heading RMSE (m) sweep on disturbed tracks [rows mag_tol, cols dip_tol deg]:")
    for tid in DISTURBED:
        print(f"  {tid} (gyro-only baseline {rows[tid]['h_gyro']:.1f}):")
        print("       " + " ".join(f"{d:>6.0f}" for d in DIP_TOLS_DEG))
        for mt in MAG_TOLS:
            print(f"  {mt:4.2f} " + " ".join(f"{rows[tid]['sweep'][(mt, dd)]:6.1f}"
                                             for dd in DIP_TOLS_DEG))

    # --- plot: heading RMSE per track for the three variants ---
    fig, ax = plt.subplots(figsize=(9, 5.5))
    x = np.arange(len(tracks))
    w = 0.27
    ax.bar(x - w, [rows[t]["h_gyro"] for t in tracks], w, label="gyro-only")
    ax.bar(x, [rows[t]["h_naive"] for t in tracks], w, label="naive MARG")
    ax.bar(x + w, [rows[t]["h_rep"] for t in tracks], w, label="gated MARG (0.10/10°)")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{t}\n{'disturbed' if t in DISTURBED else 'clean'}" for t in tracks],
                       fontsize=8)
    ax.set_ylabel("heading-isolated RMSE vs ground truth (m)")
    ax.set_title("Gated magnetometer vs gyro-only and naive MARG (open-loop heading)")
    ax.legend()
    fig.savefig("out/mag_gate.png", dpi=110, bbox_inches="tight")
    print("\nwrote out/mag_gate.png")

    # --- verdict ---
    helps_dist = all(best_gated_head[t][0] < rows[t]["h_gyro"] for t in DISTURBED)
    hurts_ctrl = any(rows[t]["h_rep"] > rows[t]["h_gyro"] * 1.10 for t in CONTROL)
    degenerate = any(rows[t]["accept"] < 0.05 for t in DISTURBED)
    print("\nVERDICT:")
    if helps_dist and not hurts_ctrl and not degenerate:
        print("  Gating HELPS: gated beats gyro-only on disturbed tracks without hurting the")
        print("  control, at a non-trivial acceptance rate. Mag+gating worth carrying forward.")
    else:
        why = []
        if not helps_dist:
            why.append("gated does not beat gyro-only on the disturbed tracks")
        if hurts_ctrl:
            why.append("gating hurts a clean control track")
        if degenerate:
            why.append("acceptance ~0 (gating is just gyro-only in disguise)")
        print("  Gating does NOT clearly help here: " + "; ".join(why) + ".")
        print("  The GPS-denied case likely needs ZUPT or accept-drift, not the magnetometer.")


if __name__ == "__main__":
    main()
