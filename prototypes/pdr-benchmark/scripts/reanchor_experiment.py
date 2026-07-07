"""Measure PDR residual drift vs GNSS re-anchor interval across the outdoor tracks.

Answers: how often must a trusted GNSS fix arrive to hold street-level accuracy?
Writes out/reanchor_curve.png and prints a table (rmse in metres vs gt).
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from pdr_bench.eval.geo import interp_ne  # noqa: E402
from pdr_bench.io.geoloc import OUTDOOR_TRACKS, TRACK_INFO, load_track  # noqa: E402
from pdr_bench.mapmatch.georef import georeference, load_gnss_pvt  # noqa: E402
from pdr_bench.pdr.pipeline import run_pdr  # noqa: E402
from pdr_bench.pdr.reanchor import reanchored_track  # noqa: E402

ROOT = "data/geoloc/Geoloc_ds022023"
INTERVALS = [np.inf, 120.0, 60.0, 30.0, 15.0]


def _rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.hypot(*(a - b).T) ** 2)))


def main() -> None:
    fig, ax = plt.subplots(figsize=(8, 5.5))
    header = f"{'track':10s} {'raw_PDR':>8s} " + " ".join(
        f"{'inf' if np.isinf(i) else int(i):>7}" for i in INTERVALS) + f" {'GNSS':>7s}"
    print(header)
    print("-" * len(header))
    for tid in OUTDOOR_TRACKS:
        s = load_track(ROOT, tid)
        tow, lat, lon = load_gnss_pvt(f"{ROOT}/{TRACK_INFO[tid][0]}/raw_measurement/gnss.ubx")
        gr = georeference(s.gt_t, s.gt_ne, tow, lat, lon)
        gnss_ne = gr.lonlat_to_ne(lat, lon)
        r = run_pdr(s, use_mag=False)
        gt = r.gt_ne[1:]                                   # aligned to step_t
        gnss_floor = _rmse(interp_ne(tow, gnss_ne, r.step_t), gt)
        vals = []
        for iv in INTERVALS:
            track = reanchored_track(r.step_t, r.step_len, r.raw_heading,
                                     tow, gnss_ne, interval=iv)
            vals.append(_rmse(track, gt))
        print(f"{tid:10s} {r.metrics['rmse_m']:8.1f} "
              + " ".join(f"{v:7.1f}" for v in vals) + f" {gnss_floor:7.1f}")
        finite = [iv for iv in INTERVALS if np.isfinite(iv)]
        ax.plot(finite, vals[1:], "o-", label=f"{tid} ({int(s.gt_path_length)} m)")
    ax.axhline(10, color="0.6", ls="--", lw=1, label="10 m (street scale)")
    ax.set_xlabel("GNSS re-anchor interval (s)")
    ax.set_ylabel("residual RMSE vs ground truth (m)")
    ax.set_title("PDR residual drift vs GNSS re-anchor interval")
    ax.invert_xaxis()
    ax.legend(fontsize=8)
    fig.savefig("out/reanchor_curve.png", dpi=110, bbox_inches="tight")
    print("\nwrote out/reanchor_curve.png")


if __name__ == "__main__":
    main()
