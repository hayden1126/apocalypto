"""Periodic absolute (GNSS) re-anchoring of a PDR track.

This is the architecture's drift-control loop: PDR supplies accurate relative motion
(step lengths + short-term heading change from the gyro), and an occasional trusted
GNSS fix re-pins absolute position and absolute heading (from GNSS course over ground).
Between anchors the track dead-reckons; at each anchor the accumulated drift is reset.
"""
import numpy as np

from pdr_bench.eval.geo import bearing


def _interp_ne(t: float,
    gt: np.ndarray,
    ne: np.ndarray,
) -> np.ndarray:
    return np.array([np.interp(t, gt, ne[:, 0]), np.interp(t, gt, ne[:, 1])])


def _gnss_course(gnss_t: np.ndarray,
    gnss_ne: np.ndarray,
    t: float,
    win: float,
) -> float:
    """Course over ground (compass bearing) from GNSS displacement over [t, t+win]."""
    a = _interp_ne(t, gnss_t, gnss_ne)
    b = _interp_ne(t + win, gnss_t, gnss_ne)
    return bearing(*(b - a))


def _integrate_with_resets(step_t: np.ndarray,
    step_len: np.ndarray,
    raw_heading: np.ndarray,
    anchors: np.ndarray,
    reset,
) -> np.ndarray:
    """Dead-reckon from raw per-step headings, resetting (position, heading offset) at
    each anchor via `reset(at, prev_pos, prev_offset, raw_unwrapped, step_t) -> (pos, offset)`."""
    raw = np.unwrap(raw_heading)
    pos, offset = reset(anchors[0], None, None, raw, step_t)
    out = np.empty((len(step_t), 2))
    nxt = 1
    for i in range(len(step_t)):
        while nxt < len(anchors) and step_t[i] >= anchors[nxt]:
            pos, offset = reset(anchors[nxt], pos, offset, raw, step_t)
            nxt += 1
        h = raw[i] + offset
        pos = pos + step_len[i] * np.array([np.cos(h), np.sin(h)])
        out[i] = pos
    return out


def reanchored_track(step_t: np.ndarray,
    step_len: np.ndarray,
    raw_heading: np.ndarray,
    gnss_t: np.ndarray,
    gnss_ne: np.ndarray,
    interval: float,
    course_win: float = 6.0,
) -> np.ndarray:
    """Dead-reckon with a GNSS re-anchor every `interval` seconds.

    At each anchor, position is reset to the GNSS fix and the heading offset is set so
    PDR heading matches GNSS course over ground; between anchors only relative PDR
    heading change is used. interval=inf reduces to a single start-pose anchor."""
    anchors = np.arange(step_t[0], step_t[-1], interval) if np.isfinite(interval) \
        else np.array([step_t[0]])

    def reset(at, prev_pos, prev_offset, raw, st):
        return (_interp_ne(at, gnss_t, gnss_ne),
                _gnss_course(gnss_t, gnss_ne, at, course_win) - np.interp(at, st, raw))

    return _integrate_with_resets(step_t, step_len, raw_heading, anchors, reset)


def _wrap(a: np.ndarray) -> np.ndarray:
    """Wrap angle(s) to [-pi, pi)."""
    return (a + np.pi) % (2 * np.pi) - np.pi


def resolve180(edge_bearing: float,
    heading: float,
) -> float:
    """Orient an undirected edge bearing to travel: pick edge_bearing or +pi nearest heading."""
    cand = np.array([edge_bearing, _wrap(edge_bearing + np.pi)])
    return float(cand[np.argmin(np.abs(_wrap(cand - heading)))])


def map_reanchored_track(step_t: np.ndarray,
    step_len: np.ndarray,
    raw_heading: np.ndarray,
    anchor_t: np.ndarray,
    map_bearing: np.ndarray,
    start_pos: np.ndarray,
) -> np.ndarray:
    """Dead-reckon from a single start position, resetting the heading offset at each
    matched anchor to the direction-resolved map edge bearing. Position is pinned only at
    start_pos (no GPS re-pin), isolating the map's HEADING contribution. anchor_t /
    map_bearing must be valid (finite) matches; filter invalid ones before calling."""
    order = np.argsort(anchor_t)
    anchor_t = np.asarray(anchor_t, float)[order]
    map_bearing = np.asarray(map_bearing, float)[order]

    def reset(at, prev_pos, prev_offset, raw, st):
        pos = np.asarray(start_pos, float) if prev_pos is None else prev_pos
        raw_at = np.interp(at, st, raw)
        cur = raw_at + (0.0 if prev_offset is None else prev_offset)
        k = int(np.argmin(np.abs(anchor_t - at)))
        return pos, resolve180(map_bearing[k], cur) - raw_at

    return _integrate_with_resets(step_t, step_len, raw_heading, anchor_t, reset)
