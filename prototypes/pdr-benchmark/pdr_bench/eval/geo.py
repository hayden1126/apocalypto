"""Planar geometry helpers in a local North-East metre frame.

Convention: positions are (N, 2) arrays of [North, East] in metres. A heading is a
compass bearing measured from North, positive clockwise toward East, so a step of
length L at heading theta advances [L*cos(theta), L*sin(theta)].
"""
import numpy as np


def rotate_ne(points: np.ndarray,
    phi: float,
) -> np.ndarray:
    """Rotate NE points clockwise by phi radians (i.e. add phi to their bearing)."""
    c, s = np.cos(phi), np.sin(phi)
    r = np.array([[c, -s], [s, c]])
    return points @ r.T


def bearing(dn: float,
    de: float,
) -> float:
    """Compass bearing (rad from North, CW toward East) of a NE displacement."""
    return float(np.arctan2(de, dn))


def initial_heading(ne: np.ndarray,
    min_dist: float = 5.0,
) -> float:
    """Bearing from the first point to the first point at least min_dist away."""
    d = ne - ne[0]
    dist = np.hypot(d[:, 0], d[:, 1])
    idx = np.argmax(dist >= min_dist)
    if dist[idx] < min_dist:          # never travels min_dist: use the farthest point
        idx = int(np.argmax(dist))
    return bearing(d[idx, 0], d[idx, 1])


def interp_ne(t_src: np.ndarray,
    ne_src: np.ndarray,
    t_query: np.ndarray,
) -> np.ndarray:
    """Linearly interpolate an NE track onto query times (clamped to source range)."""
    n = np.interp(t_query, t_src, ne_src[:, 0])
    e = np.interp(t_query, t_src, ne_src[:, 1])
    return np.column_stack([n, e])


def path_length(ne: np.ndarray) -> float:
    """Total polyline length in metres."""
    return float(np.hypot(*np.diff(ne, axis=0).T).sum())


def decompose_error(track: np.ndarray,
    ref: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Split per-point error (track - ref) into (cross_track, along_track) using the
    local reference direction. Both arrays are signed metres, one per point."""
    err = track - ref
    d = np.gradient(ref, axis=0)
    norm = np.hypot(d[:, 0], d[:, 1])
    norm[norm == 0] = 1.0
    tang = d / norm[:, None]                       # unit along-track (ref direction)
    along = err[:, 0] * tang[:, 0] + err[:, 1] * tang[:, 1]
    cross = err[:, 0] * (-tang[:, 1]) + err[:, 1] * tang[:, 0]
    return cross, along
