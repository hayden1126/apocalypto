"""Map-match a georeferenced PDR track to the OSM walking graph (leuven HMM matcher)."""
from dataclasses import dataclass

import networkx as nx
import numpy as np
from leuvenmapmatching.map.inmem import InMemMap
from leuvenmapmatching.matcher.distance import DistanceMatcher


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
    """Snapped track and the matched node route."""
    snapped: np.ndarray       # (M, 2) UTM (easting, northing), one per observation
    nodes: list               # matched node id sequence (the route)
    frac_matched: float       # fraction of observations that received a match


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
    return MatchResult(snapped=snapped,
        nodes=matcher.path_pred_onlynodes,
        frac_matched=len(best) / len(path) if path else 0.0)
