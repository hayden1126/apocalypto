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
from pdr_bench.io.phone import load_phone, phone_georef
from pdr_bench.mapmatch.graph import walk_graph
from pdr_bench.mapmatch.match import match_track
from pdr_bench.pdr.pipeline import run_pdr
from pdr_bench.run import decimate, route_edge_overlap
from pdr_bench.viz.plot import plot_overlay


def process_phone(export_dir: str,
    name: str = "phone",
    k: float | None = None,
    do_map: bool = True,
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
            out["matched_vs_gps"] = trajectory_metrics(matched_utm, gt_utm[idx], pl)
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
    a = ap.parse_args()
    out = process_phone(a.export_dir, a.name, a.k, do_map=not a.no_map)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
