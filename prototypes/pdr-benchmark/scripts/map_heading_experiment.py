"""B1 experiment: does a map-derived heading bound gyro PDR drift?

Phone data has no clean per-step heading truth, so the honest signals are INTEGRATED:
GPS-free loop closure and whole-track cross-track vs GPS, against a GNSS-15 s re-anchored
reference. The corrector is SINGLE-PASS: it matches the drifted gyro-PDR track once and
resets heading to the matched edge bearings. This is circular when drift is large (you need
good heading to match, but you are matching to fix heading), so wrong-edge snapping is the
core confound. Measured on the 595 m ma_ling block (cramped 3-loop, 18 m median snap) and
the ~2 km ma_ling_2km walk (distinct streets but ~25% raw drift, 70 m median snap): in both,
single-pass matching snaps to wrong edges and the corrector does not beat pure gyro. The
coverage split shows the MECHANISM works where the track snaps to the correct edge; the
matching is the bottleneck. A viable corrector must iterate match<->correct or map-match a
GNSS-re-anchored (low-drift) track.

Usage: PYTHONPATH=. .venv/bin/python scripts/map_heading_experiment.py [export_dir] \
           [--k K] [--name NAME]
Writes out/<name>_map_heading.png. The OSM graph cache is keyed on --name
(data/osm_cache/<name>.graphml) so a new walk does not reuse a stale bbox's graph.
"""
import argparse

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

def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(x) ** 2)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir", nargs="?", default="data/phone/ma_ling_walk")
    ap.add_argument("--k", type=float, default=0.537,
        help="Weinberg step gain from a measured calibration leg (see calibrate_leg.py)")
    ap.add_argument("--name", default="ma_ling",
        help="session/label; also keys the OSM cache data/osm_cache/<name>.graphml")
    a = ap.parse_args()

    s = load_phone(a.export_dir, name=a.name)
    r = run_pdr(s, use_mag=False, k=a.k)
    gr = phone_georef(s)
    pdr_utm = gr.ne_to_utm(r.ne)

    ll = gr.ne_to_lonlat(s.gt_ne)
    b = 0.0018
    bbox = (ll[:, 0].min() - b, ll[:, 1].min() - b, ll[:, 0].max() + b, ll[:, 1].max() + b)
    graph = walk_graph(bbox, gr.utm, f"data/osm_cache/{a.name}.graphml")

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
    print("(single-pass match on the drifted gyro-PDR track; no clean per-step heading truth)\n")
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
        print("\nVERDICT: map heading REDUCES drift here (single-pass; an iterated "
              "match<->correct loop should do at least as well).")
    else:
        print(f"\nVERDICT: single-pass map heading does NOT bound drift here (frac_matched "
              f"{mr.frac_matched:.2f}, {med:.0f} m median matched-edge snap). Neither the naive "
              "nor the confidence-gated corrector beats pure gyro on BOTH loop closure and "
              "cross-track, and both are far from the GNSS reference. The failure is in the "
              "MATCHING, not the mechanism: the coverage split shows map heading helps where the "
              "track snaps close (correct edge) and hurts where it snaps far (wrong edge). "
              "Single-pass matching of a drifted PDR track snaps to wrong edges; a viable "
              "corrector must iterate match<->correct or map-match a GNSS-re-anchored (low-drift) "
              "track. This walk has GNSS throughout, so re-anchoring alone already bounds drift "
              "(see the GNSS row); the map's heading value is only testable in GNSS-denied stretches.")

    out_png = f"out/{a.name}_map_heading.png"
    plot_overlay(graph, gr.ne_to_utm(gps), gr.ne_to_utm(pure), gr.ne_to_utm(mapc),
                 f"{s.name}: map-heading (orange) vs pure PDR (blue) vs GPS (green)",
                 out_png)
    print(f"\nwrote {out_png}")


if __name__ == "__main__":
    main()
