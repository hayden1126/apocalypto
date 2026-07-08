"""Map-match a georeferenced PDR track to the OSM walking graph (leuven HMM matcher)."""
from dataclasses import dataclass

import networkx as nx
import numpy as np
from leuvenmapmatching.map.inmem import InMemMap
from leuvenmapmatching.matcher.distance import DistanceMatcher

from pdr_bench.mapmatch.georef import GeoRef


def build_map(graph: nx.MultiDiGraph) -> InMemMap:
    """Build a leuven InMemMap (projected metres) from a UTM osmnx graph."""
    m = InMemMap("geoloc", use_latlon=False, use_rtree=True, index_edges=True)
    for nid, d in graph.nodes(data=True):
        m.add_node(int(nid), (d["x"], d["y"]))       # (easting, northing)
    for u, v, _ in graph.edges(keys=True):
        m.add_edge(int(u), int(v))
    m.purge()
    return m


@dataclass
class MatchResult:
    """Snapped track, matched node route, and the matched-edge endpoints per observation."""
    snapped: np.ndarray       # (M, 2) UTM (easting, northing), one per observation
    nodes: list               # matched node id sequence (the route)
    frac_matched: float       # fraction of observations that received a match
    edge_p1: np.ndarray       # (M, 2) UTM start of the matched edge; NaN for node-only matches
    edge_p2: np.ndarray       # (M, 2) UTM end of the matched edge; NaN for node-only matches


def match_track(graph: nx.MultiDiGraph,
    track_utm: np.ndarray,
    max_dist: float = 200.0,
    obs_noise: float = 30.0,
    non_emitting: bool = True,
) -> MatchResult:
    """Snap a UTM track (easting, northing) onto the graph; return snapped points."""
    matcher = DistanceMatcher(build_map(graph),
        max_dist=max_dist, obs_noise=obs_noise,
        min_prob_norm=0.001, non_emitting_states=non_emitting)
    path = [(float(x), float(y)) for x, y in track_utm]
    matcher.match(path)
    best = matcher.lattice_best
    snapped = np.array([(m.edge_m.pi[0], m.edge_m.pi[1]) for m in best])
    edge_p1 = np.full((len(best), 2), np.nan)
    edge_p2 = np.full((len(best), 2), np.nan)
    for j, m in enumerate(best):
        if m.edge_m.p2 is not None:          # p2 is None => matched to a node, not an edge
            edge_p1[j] = m.edge_m.p1
            edge_p2[j] = m.edge_m.p2
    return MatchResult(snapped=snapped,
        nodes=matcher.path_pred_onlynodes,
        frac_matched=len(best) / len(path) if path else 0.0,
        edge_p1=edge_p1, edge_p2=edge_p2)


def matched_edge_bearings(mr: MatchResult,
    gr: GeoRef,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-observation matched-edge compass bearing (rad, undirected) in the local NE
    frame, plus a validity mask (False for node-only or degenerate edges)."""
    p1, p2 = gr.utm_to_ne(mr.edge_p1), gr.utm_to_ne(mr.edge_p2)   # UTM -> [North, East]
    d = p2 - p1
    seg = np.hypot(d[:, 0], d[:, 1])
    valid = np.isfinite(seg) & (seg > 1e-6)
    bear = np.full(len(seg), np.nan)
    bear[valid] = np.arctan2(d[valid, 1], d[valid, 0])           # bearing(dn, de): N-CW-to-E
    return bear, valid
