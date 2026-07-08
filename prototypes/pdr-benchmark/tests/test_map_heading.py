"""Tests for the map-derived heading corrector (B1): edge-bearing extraction,
undirected-bearing resolution, and heading-drift bounding by a map bearing."""
import numpy as np
from pyproj import CRS

from pdr_bench.mapmatch.georef import GeoRef
from pdr_bench.mapmatch.match import MatchResult, matched_edge_bearings
from pdr_bench.pdr.integrate import dead_reckon
from pdr_bench.pdr.reanchor import map_reanchored_track, resolve180


def _trivial_georef():
    # r=I, t=0 -> utm_to_ne just flips (E,N) -> (N,E), so bearings are exact.
    return GeoRef(r=np.eye(2), t=np.zeros(2), utm=CRS.from_epsg(32650), residual_m=0.0)


def test_matched_edge_bearings():
    gr = _trivial_georef()
    edge_p1 = np.array([[0.0, 0.0], [0.0, 0.0], [np.nan, np.nan]])   # UTM (E, N)
    edge_p2 = np.array([[0.0, 10.0], [10.0, 0.0], [np.nan, np.nan]])  # due N, due E, node-only
    mr = MatchResult(snapped=np.zeros((3, 2)), nodes=[], frac_matched=1.0,
                     edge_p1=edge_p1, edge_p2=edge_p2)
    bear, valid = matched_edge_bearings(mr, gr)
    assert valid.tolist() == [True, True, False]
    assert np.isclose(bear[0], 0.0)             # North
    assert np.isclose(bear[1], np.pi / 2)       # East
    assert np.isnan(bear[2])


def test_resolve180_orients_to_travel():
    assert np.isclose(resolve180(np.pi, 0.05), 0.0)      # south-pointing edge, travelling north
    assert np.isclose(resolve180(0.0, 0.05), 0.0)        # already aligned
    assert np.isclose(resolve180(np.pi / 2, np.pi / 2), np.pi / 2)


def test_map_reanchored_bounds_heading_drift():
    # straight 100 m north walk; gyro heading drifts; the map says "North" the whole way.
    n = 100
    step_t = np.arange(n) * 0.5
    step_len = np.ones(n)
    raw_heading = 0.006 * np.arange(n)                    # accumulating drift
    truth = np.column_stack([np.arange(1, n + 1), np.zeros(n)]).astype(float)
    anchor_t = step_t.copy()
    map_bearing = np.zeros(n)                             # matched edge bearing = North

    corrected = map_reanchored_track(step_t, step_len, raw_heading, anchor_t,
                                     map_bearing, start_pos=np.array([0.0, 0.0]))
    pure = dead_reckon(step_len, raw_heading, start=(0.0, 0.0))[1:]
    err_corrected = np.hypot(*(corrected - truth).T).max()
    err_pure = np.hypot(*(pure - truth).T).max()
    assert err_corrected < 2.0                           # map bearing bounds the drift
    assert err_pure > 10.0                               # uncorrected gyro drift runs away


def test_map_reanchored_follows_a_turn():
    # north for 50 steps, then the matched edge turns to East; corrected track must follow.
    n = 100
    step_t = np.arange(n) * 0.5
    step_len = np.ones(n)
    raw_heading = np.zeros(n)                             # gyro dead straight (no turn sensed)
    anchor_t = step_t.copy()
    map_bearing = np.where(np.arange(n) < 50, 0.0, np.pi / 2)   # map: N then E
    track = map_reanchored_track(step_t, step_len, raw_heading, anchor_t,
                                 map_bearing, start_pos=np.array([0.0, 0.0]))
    # after the turn the track should gain easting while northing plateaus
    assert track[-1, 1] > 40.0                            # moved East in the second half
    assert track[49, 0] > 40.0                            # went North in the first half
    assert abs(track[-1, 0] - track[49, 0]) < 5.0         # North plateaus after the turn
