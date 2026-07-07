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
    raw = np.unwrap(raw_heading)
    anchors = np.arange(step_t[0], step_t[-1], interval) if np.isfinite(interval) \
        else np.array([step_t[0]])
    pos = _interp_ne(anchors[0], gnss_t, gnss_ne)
    offset = _gnss_course(gnss_t, gnss_ne, anchors[0], course_win) - raw[0]
    out = np.empty((len(step_t), 2))
    nxt = 1
    for i in range(len(step_t)):
        while nxt < len(anchors) and step_t[i] >= anchors[nxt]:
            at = anchors[nxt]
            pos = _interp_ne(at, gnss_t, gnss_ne)
            offset = _gnss_course(gnss_t, gnss_ne, at, course_win) - np.interp(at, step_t, raw)
            nxt += 1
        h = raw[i] + offset
        pos = pos + step_len[i] * np.array([np.cos(h), np.sin(h)])
        out[i] = pos
    return out
