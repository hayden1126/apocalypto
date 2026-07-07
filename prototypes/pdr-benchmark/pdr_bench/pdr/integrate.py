"""Dead-reckoning integration and start-pose alignment."""
import numpy as np

from pdr_bench.eval.geo import initial_heading, rotate_ne


def dead_reckon(step_len: np.ndarray,
    step_heading: np.ndarray,
    start: tuple[float, float] = (0.0, 0.0),
) -> np.ndarray:
    """Integrate per-step (length, heading) into an NE track, prepending the start.

    Heading is a compass bearing from North; a step advances
    [L*cos(theta), L*sin(theta)] in [North, East]."""
    dn = step_len * np.cos(step_heading)
    de = step_len * np.sin(step_heading)
    ne = np.column_stack([dn, de]).cumsum(axis=0)
    return np.vstack([start, np.asarray(start) + ne])


def align_start_pose(pdr_ne: np.ndarray,
    ref_ne: np.ndarray,
    min_dist: float = 8.0,
) -> tuple[np.ndarray, float]:
    """Rotate the PDR track about its start so its initial heading matches the
    reference's. Uses only the known start pose (position + initial heading), which
    a real system would have; everything after stays open-loop. Returns (track, offset)."""
    offset = initial_heading(ref_ne, min_dist) - initial_heading(pdr_ne, min_dist)
    rotated = rotate_ne(pdr_ne - pdr_ne[0], offset) + pdr_ne[0]
    return rotated, offset
