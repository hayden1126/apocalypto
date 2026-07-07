"""Fetch and cache an OSM pedestrian walking graph, projected to a target UTM CRS."""
from pathlib import Path

import networkx as nx
import osmnx as ox
from pyproj import CRS

ox.settings.use_cache = True
# Keep tags that distinguish real footways from tag-only sidewalks / open areas.
ox.settings.useful_tags_way += ["footway", "sidewalk", "crossing", "area"]


def walk_graph(bbox_lonlat: tuple[float, float, float, float],
    utm: CRS,
    cache_path: str | Path,
) -> nx.MultiDiGraph:
    """Walking graph for a (west, south, east, north) bbox, projected to utm.

    The unprojected graph is cached to GraphML; projection is redone on load."""
    cache_path = Path(cache_path)
    if cache_path.exists():
        g = ox.io.load_graphml(cache_path)
    else:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        g = ox.graph_from_bbox(bbox_lonlat, network_type="walk")
        ox.io.save_graphml(g, cache_path)
    return ox.project_graph(g, to_crs=utm)
