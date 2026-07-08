"""Run the PDR + map-matching benchmark on a self-collected phone walk.

Usage: python -m pdr_bench.run_phone <export_dir> [--name N] [--k K] [--no-map]
Writes out/<name>_metrics.json and out/<name>_overlay.png.

The phone GPS is the reference, so phone_georef supplies the (trivial) NE->UTM map in
place of load_gnss_pvt + georeference. With --k omitted, Weinberg k is GPS-calibrated
(optimistic: it forces total distance to match GPS); pass a fixed k from a measured
calibration segment for the honest number. Metrics are named *_vs_gps to flag that the
reference is the phone's own ~3-10 m GPS, not an independent truth.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from pdr_bench.eval.geo import path_length
from pdr_bench.eval.metrics import trajectory_metrics
from pdr_bench.eval.phone_metrics import checkpoint_errors
from pdr_bench.io.phone import load_checkpoints, load_phone, phone_georef
from pdr_bench.mapmatch.graph import walk_graph
from pdr_bench.mapmatch.match import match_track
from pdr_bench.pdr.pipeline import run_pdr
from pdr_bench.run import decimate, route_edge_overlap
from pdr_bench.viz.plot import plot_overlay


def process_phone(export_dir: str,
    name: str = "phone",
    k: float | None = None,
    do_map: bool = True,
    checkpoint_csv: str | None = None,
    obs_noise: float = 25.0,
    outdir: str = "out",
) -> dict:
    """Full pipeline for one phone walk; returns a metrics dict and writes artefacts."""
    s = load_phone(export_dir, name=name)
    r = run_pdr(s, use_mag=False, k=k)
    out = {"name": name, "gt_path_length_m": round(s.gt_path_length, 1),
           "n_steps": r.n_steps, "weinberg_k": round(r.k, 4),
           "k_source": "fixed" if k is not None else "gps_calibrated",
           "gps_median_acc_m": round(float(np.median(s.meta["gps_horizontal_acc_m"])), 1),
           "pdr_vs_gps": r.metrics}

    if checkpoint_csv:
        mt, mne, labels = load_checkpoints(s, checkpoint_csv)
        in_range = (mt >= r.t[0]) & (mt <= r.t[-1])
        if in_range.any():
            ce = checkpoint_errors(r.t, r.ne, mt[in_range], mne[in_range])  # GPS-free M4
            out["checkpoint_vs_survey"] = {
                "labels": [lab for lab, ok in zip(labels, in_range) if ok],
                "errors_m": [round(float(x), 1) for x in ce],
                "p95_m": round(float(np.percentile(ce, 95)), 1),
                "n_dropped_out_of_range": int((~in_range).sum())}
        else:
            out["checkpoint_vs_survey"] = "skipped: no markers within the PDR track span"

    graph, matched_utm = None, None
    if do_map:
        gr = phone_georef(s)
        pdr_utm, gt_utm = gr.ne_to_utm(r.ne), gr.ne_to_utm(r.gt_ne)
        pl = path_length(gt_utm)
        try:
            ll = gr.ne_to_lonlat(s.gt_ne)
            b = 0.0018
            bbox = (ll[:, 0].min() - b, ll[:, 1].min() - b,
                    ll[:, 0].max() + b, ll[:, 1].max() + b)
            graph = walk_graph(bbox, gr.utm, f"data/osm_cache/{name}.graphml")
        except ValueError as e:
            out["map_matching"] = f"skipped: no OSM walk graph ({e})"
        if graph is not None:
            idx = decimate(pdr_utm, 3.0)
            mr = match_track(graph, pdr_utm[idx], obs_noise=obs_noise)
            matched_utm = mr.snapped
            gtm = match_track(graph, gt_utm[idx], obs_noise=8.0)
            # the matcher can drop observations when coverage is thin (frac_matched < 1),
            # so matched_utm may be shorter than idx; only score when it stays 1:1, else the
            # per-point vs-GPS comparison would misalign (route_edge_overlap is set-based, safe).
            if len(matched_utm) == len(idx):
                out["matched_vs_gps"] = trajectory_metrics(matched_utm, gt_utm[idx], pl)
            else:
                out["matched_vs_gps"] = (f"skipped: sparse match "
                                         f"({len(matched_utm)}/{len(idx)} obs matched)")
            out["route_edge_overlap"] = round(route_edge_overlap(gtm.nodes, mr.nodes), 3)
        pdr_plot, gt_plot = pdr_utm, gt_utm
    else:
        pdr_plot, gt_plot = r.ne[:, ::-1], r.gt_ne[:, ::-1]  # NE -> (E,N) for plotting

    Path(outdir).mkdir(exist_ok=True)
    json.dump(out, open(f"{outdir}/{name}_metrics.json", "w"), indent=2)
    plot_overlay(graph, gt_plot, pdr_plot, matched_utm,
        f"{name} (phone walk)", f"{outdir}/{name}_overlay.png")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir")
    ap.add_argument("--name", default="phone")
    ap.add_argument("--k", type=float, default=None,
        help="fixed Weinberg k (from a measured calibration leg); default GPS-calibrated")
    ap.add_argument("--no-map", action="store_true")
    ap.add_argument("--checkpoints", default=None,
        help="surveyed-checkpoint csv (label,lat,lon or label,n,e); scores GPS-free M4 error")
    a = ap.parse_args()
    out = process_phone(a.export_dir, a.name, a.k, do_map=not a.no_map,
                        checkpoint_csv=a.checkpoints)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
