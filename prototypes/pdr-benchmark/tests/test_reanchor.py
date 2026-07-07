"""Re-anchoring and georef-inverse tests."""
import numpy as np
from pyproj import CRS

from pdr_bench.mapmatch.georef import GeoRef
from pdr_bench.pdr.reanchor import reanchored_track


def test_georef_inverse_roundtrip():
    phi = 0.4
    r = np.array([[np.cos(phi), -np.sin(phi)], [np.sin(phi), np.cos(phi)]])
    gr = GeoRef(r=r, t=np.array([500.0, -300.0]), utm=CRS.from_epsg(32630), residual_m=0.0)
    ne = np.random.default_rng(0).normal(size=(20, 2)) * 50
    assert np.allclose(gr.utm_to_ne(gr.ne_to_utm(ne)), ne, atol=1e-6)


def test_reanchor_bounds_heading_drift():
    # Straight 100 m north walk; gyro heading drifts linearly to ~34 deg by the end.
    n = 100
    step_t = np.arange(n) * 0.5
    step_len = np.ones(n)
    raw_heading = 0.006 * np.arange(n)          # accumulating drift
    truth = np.column_stack([np.arange(1, n + 1), np.zeros(n)]).astype(float)
    gnss_t, gnss_ne = step_t.copy(), truth.copy()  # perfect fixes along the true line

    anchored = reanchored_track(step_t, step_len, raw_heading, gnss_t, gnss_ne,
                                interval=5.0, course_win=2.0)
    none = reanchored_track(step_t, step_len, raw_heading, gnss_t, gnss_ne,
                            interval=np.inf, course_win=2.0)
    err_anchored = np.hypot(*(anchored - truth).T).max()
    err_none = np.hypot(*(none - truth).T).max()
    assert err_anchored < 2.0            # bounded by intra-segment drift
    assert err_none > 10.0               # unanchored heading drift runs away
