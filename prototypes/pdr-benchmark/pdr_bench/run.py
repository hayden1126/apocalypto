"""Run the PDR + map-matching benchmark on one GEOLOC track.

Usage: python -m pdr_bench.run --track TEST_05 [--data <root>] [--no-map]
Writes out/<track>_metrics.json and out/<track>_overlay.png.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from pdr_bench.eval.geo import path_length
from pdr_bench.eval.metrics import trajectory_metrics
from pdr_bench.io.geoloc import TRACK_INFO, load_track
from pdr_bench.mapmatch.georef import georeference, load_gnss_pvt
from pdr_bench.mapmatch.graph import walk_graph
from pdr_bench.mapmatch.match import match_track
from pdr_bench.pdr.pipeline import run_pdr
from pdr_bench.viz.plot import plot_overlay


def decimate(track: np.ndarray,
    min_spacing: float = 3.0,
) -> np.ndarray:
    """Indices of points kept so consecutive spacing is at least min_spacing metres."""
    keep = [0]
    last = track[0]
    for i in range(1, len(track)):
        if np.hypot(*(track[i] - last)) >= min_spacing:
            keep.append(i)
            last = track[i]
    return np.array(keep)


def route_edge_overlap(gt_nodes: list,
    pdr_nodes: list,
) -> float:
    """Fraction of the ground-truth matched route's edges also in the PDR route."""
    def edges(nodes):
        return {frozenset((a, b)) for a, b in zip(nodes[:-1], nodes[1:])}
    gt_e, pdr_e = edges(gt_nodes), edges(pdr_nodes)
    return len(gt_e & pdr_e) / len(gt_e) if gt_e else 0.0


def process(root: str,
    track: str,
    do_map: bool = True,
    obs_noise: float = 25.0,
    outdir: str = "out",
) -> dict:
    """Full pipeline for one track; returns a metrics dict and writes artefacts."""
    s = load_track(root, track)
    r = run_pdr(s, use_mag=False)
    out = {"track": track, "environment": s.meta["environment"],
           "gt_path_length_m": round(s.gt_path_length, 1),
           "n_steps": r.n_steps, "pdr_vs_gt": r.metrics}

    graph, matched_utm = None, None
    rel = TRACK_INFO[track][0]
    if do_map:
        tow, lat, lon = load_gnss_pvt(f"{root}/{rel}/raw_measurement/gnss.ubx")
        gr = georeference(s.gt_t, s.gt_ne, tow, lat, lon)
        out["georef_residual_m"] = round(gr.residual_m, 2)
        pdr_utm, gt_utm = gr.ne_to_utm(r.ne), gr.ne_to_utm(r.gt_ne)
        pl = path_length(gt_utm)
        try:
            ll = gr.ne_to_lonlat(s.gt_ne)
            b = 0.0018
            bbox = (ll[:, 0].min() - b, ll[:, 1].min() - b,
                    ll[:, 0].max() + b, ll[:, 1].max() + b)
            graph = walk_graph(bbox, gr.utm, f"data/osm_cache/{track}.graphml")
        except ValueError as e:
            out["map_matching"] = f"skipped: no OSM walk graph ({e})"
        if graph is not None:
            idx = decimate(pdr_utm, 3.0)
            mr = match_track(graph, pdr_utm[idx], obs_noise=obs_noise)
            matched_utm = mr.snapped
            gtm = match_track(graph, gt_utm[idx], obs_noise=8.0)
            out["matched_vs_gt"] = trajectory_metrics(matched_utm, gt_utm[idx], pl)
            out["gt_selfmatch_floor"] = trajectory_metrics(gtm.snapped, gt_utm[idx], pl)
            out["route_edge_overlap"] = round(route_edge_overlap(gtm.nodes, mr.nodes), 3)
        pdr_plot, gt_plot = pdr_utm, gt_utm
    else:
        pdr_plot, gt_plot = r.ne[:, ::-1], r.gt_ne[:, ::-1]  # NE -> (E,N) for plotting

    Path(outdir).mkdir(exist_ok=True)
    json.dump(out, open(f"{outdir}/{track}_metrics.json", "w"), indent=2)
    plot_overlay(graph, gt_plot, pdr_plot, matched_utm,
        f"{track}: {s.meta['environment']}", f"{outdir}/{track}_overlay.png")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", default="TEST_05", choices=list(TRACK_INFO))
    ap.add_argument("--data", default="data/geoloc/Geoloc_ds022023")
    ap.add_argument("--no-map", action="store_true")
    a = ap.parse_args()
    out = process(a.data, a.track, do_map=not a.no_map)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
