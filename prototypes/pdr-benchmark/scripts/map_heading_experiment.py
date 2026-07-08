"""B1 experiment: does a map-derived heading bound gyro PDR drift on the 595 m walk?

PRELIMINARY / venue-caveated. The ma_ling block is a cramped 3-loop, short-edge case,
and phone data has no clean per-step heading truth, so the honest signals are INTEGRATED:
GPS-free loop closure (does map-heading kill the ~39 m precession over 3 loops?) and
whole-track cross-track vs GPS. The decisive test needs the 2-3 km walk's distinct-street
geometry. Single-pass match on the drifted gyro-PDR track means wrong-edge snapping on
later loops is a known confound (a real system would iterate match<->correct).

Usage: PYTHONPATH=. .venv/bin/python scripts/map_heading_experiment.py [export_dir]
Writes out/map_heading.png.
"""
import sys

import matplotlib

matplotlib.use("Agg")
import numpy as np  # noqa: E402

from pdr_bench.eval.geo import decompose_error, interp_ne  # noqa: E402
from pdr_bench.eval.phone_metrics import loop_closure_error  # noqa: E402
from pdr_bench.io.phone import load_phone, phone_georef  # noqa: E402
from pdr_bench.mapmatch.graph import walk_graph  # noqa: E402
from pdr_bench.mapmatch.match import match_track, matched_edge_bearings  # noqa: E402
from pdr_bench.pdr.pipeline import run_pdr  # noqa: E402
from pdr_bench.pdr.reanchor import map_reanchored_track, reanchored_track  # noqa: E402
from pdr_bench.pdr.trusted_fix import trusted_fix_mask  # noqa: E402
from pdr_bench.run import decimate  # noqa: E402
from pdr_bench.viz.plot import plot_overlay  # noqa: E402

K = 0.537


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(x) ** 2)))


def main() -> None:
    export = sys.argv[1] if len(sys.argv) > 1 else "data/phone/ma_ling_walk"
    s = load_phone(export, name="ma_ling")
    r = run_pdr(s, use_mag=False, k=K)
    gr = phone_georef(s)
    pdr_utm = gr.ne_to_utm(r.ne)

    ll = gr.ne_to_lonlat(s.gt_ne)
    b = 0.0018
    bbox = (ll[:, 0].min() - b, ll[:, 1].min() - b, ll[:, 0].max() + b, ll[:, 1].max() + b)
    graph = walk_graph(bbox, gr.utm, "data/osm_cache/ma_ling.graphml")

    idx = decimate(pdr_utm, 3.0)
    mr = match_track(graph, pdr_utm[idx], obs_noise=25.0)
    bear, valid = matched_edge_bearings(mr, gr)
    m = min(len(idx), len(bear))                       # align (frac_matched<1 would desync)
    idx, bear, valid = idx[:m], bear[:m], valid[:m]
    snap_ne = gr.utm_to_ne(mr.snapped[:m])
    snapdist = np.hypot(*(snap_ne - r.ne[idx]).T)      # matched-edge fit quality per obs
    anchor_t, map_bearing = r.t[idx][valid], bear[valid]
    GATE_M = 8.0                                        # trust only tight (confident) matches
    g = valid & (snapdist < GATE_M)

    # trusted GPS: the start anchor + the GNSS-reanchored reference (the "with GPS" bound)
    keep = trusted_fix_mask(s.gt_t, s.gt_ne, s.meta["gps_horizontal_acc_m"])
    gt_t, gt_ne = s.gt_t[keep], s.gt_ne[keep]
    start_pos = interp_ne(gt_t, gt_ne, np.array([r.step_t[0]]))[0]

    pure = reanchored_track(r.step_t, r.step_len, r.raw_heading, gt_t, gt_ne, np.inf)
    mapc = map_reanchored_track(r.step_t, r.step_len, r.raw_heading, anchor_t, map_bearing,
                                start_pos)
    mapg = (map_reanchored_track(r.step_t, r.step_len, r.raw_heading, r.t[idx][g], bear[g],
                                 start_pos) if g.sum() >= 2 else pure)
    gnss15 = reanchored_track(r.step_t, r.step_len, r.raw_heading, gt_t, gt_ne, 15.0)

    gps = interp_ne(s.gt_t, s.gt_ne, r.step_t)         # GPS reference at step times

    def xt(track):
        cross, _ = decompose_error(track, gps)
        return _rms(cross)

    def rmse(track):
        return _rms(np.hypot(*(track - gps).T))

    print(f"map-heading experiment on {s.name}: {len(idx)} matched pts, "
          f"{int(valid.sum())} valid edge bearings, {int(g.sum())} tight (<{GATE_M:g} m), "
          f"frac_matched {mr.frac_matched:.2f}")
    print("(PRELIMINARY, venue-caveated: cramped 3-loop block, no clean heading truth)\n")
    print(f"{'track':<24}{'loop_closure_m':>16}{'xtrack_rmse_m':>15}{'rmse_vs_gps_m':>15}")
    print("-" * 70)
    for name, tr in [("pure PDR (gyro)", pure), ("map-heading (all)", mapc),
                     (f"map-heading (<{GATE_M:g} m gate)", mapg), ("GNSS 15 s (ref)", gnss15)]:
        print(f"{name:<24}{loop_closure_error(tr):>16.1f}{xt(tr):>15.1f}{rmse(tr):>15.1f}")

    # coverage/degradation split: bucket steps by matched-edge snap distance (map-fit quality)
    vt, vd = r.t[idx][valid], snapdist[valid]
    step_fit = np.array([vd[np.argmin(np.abs(vt - t))] for t in r.step_t])
    med = float(np.median(vd))
    cross_map, _ = decompose_error(mapc, gps)
    cross_pure, _ = decompose_error(pure, gps)
    low, high = step_fit <= med, step_fit > med
    print(f"\ncoverage split by matched-edge snap distance (median {med:.1f} m):")
    print(f"  well-fit steps (<= {med:.1f} m): pure xtrack {_rms(cross_pure[low]):.1f} m "
          f"-> map {_rms(cross_map[low]):.1f} m")
    print(f"  poorly-fit steps (> {med:.1f} m): pure xtrack {_rms(cross_pure[high]):.1f} m "
          f"-> map {_rms(cross_map[high]):.1f} m")

    lc_pure, xt_pure = loop_closure_error(pure), xt(pure)

    def beats(tr):     # robustly better than pure gyro on BOTH integrated metrics
        return loop_closure_error(tr) < 0.9 * lc_pure and xt(tr) < 0.9 * xt_pure

    if beats(mapc) or beats(mapg):
        print("\nVERDICT: map heading REDUCES drift here (preliminary; verify on the 2-3 km walk)")
    else:
        print("\nVERDICT: map heading does NOT robustly bound drift on this cramped block. "
              "Neither the naive nor the confidence-gated corrector beats pure gyro on BOTH "
              "loop closure and cross-track (the gate trades a cross-track gain for a worse "
              f"loop closure), and both are far from the GNSS reference. Root cause: {med:.0f} m "
              "median matched-edge snap distance, i.e. wrong-edge snapping of the drifted track "
              "in this short-edge 3-loop venue. Consistent with pushback #2, but confounded by "
              "venue + single-pass matching: re-run on the 2-3 km walk before concluding.")

    plot_overlay(graph, gr.ne_to_utm(gps), gr.ne_to_utm(pure), gr.ne_to_utm(mapc),
                 f"{s.name}: map-heading (orange) vs pure PDR (blue) vs GPS (green)",
                 "out/map_heading.png")
    print("\nwrote out/map_heading.png")


if __name__ == "__main__":
    main()
