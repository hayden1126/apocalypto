"""Regression test on the real phone shakedown walk (dataset-gated).

Locks the step-2 shakedown numbers so a pipeline change cannot silently move them.
Tier 1 asserts the gate-invariant anchors (path length, step count, k, loop closure);
Tier 2 asserts the held-out re-anchor RMSE against a named baseline, gated exactly as
scripts/reanchor_phone.py gates. The A2 trusted-fix mask flips the gating and the
BASELINE constant in one commit. The raw walk is gitignored, so the test skips when
data/phone/ma_ling_walk is absent (mirrors the GEOLOC gate in test_pipeline.py).
"""
from pathlib import Path

import numpy as np
import pytest

from pdr_bench.eval.phone_metrics import heldout_reanchor_rmse, loop_closure_error
from pdr_bench.io.phone import load_phone
from pdr_bench.pdr.pipeline import run_pdr
from pdr_bench.pdr.reanchor import reanchored_track
from pdr_bench.pdr.trusted_fix import trusted_fix_mask

DATA = Path(__file__).resolve().parent.parent / "data/phone/ma_ling_walk"
K = 0.537                        # honest step gain from the counted 15.3 m calibration leg

# BASELINE captured 2026-07-08 on ma_ling_walk (595 m real walk, 3 loops, k=0.537).
# Held-out re-anchor RMSE (m) by cadence interval (s), gated as reanchor_phone.py gates.
#   PRE-A2  (acc < 8.0):        {30: 22.2, 15: 11.4}   (starved: 8/524 fixes trusted)
#   POST-A2 (trusted_fix_mask): {30: 14.9, 15: 4.0}    (515/524 fixes trusted)
BASELINE = {30.0: 14.9, 15.0: 4.0}    # POST-A2 (trusted_fix_mask)

pytestmark = pytest.mark.skipif(not DATA.exists(), reason="phone walk dataset not present")


def _trusted(s):
    """Gate GPS fixes exactly as scripts/reanchor_phone.py does."""
    keep = trusted_fix_mask(s.gt_t, s.gt_ne, s.meta["gps_horizontal_acc_m"])
    return s.gt_t[keep], s.gt_ne[keep]


def test_pipeline_anchors_gate_invariant():
    # GPS-free / selection-invariant quantities: these do NOT move when the gate changes.
    s = load_phone(DATA, name="ma_ling")
    r = run_pdr(s, use_mag=False, k=K)
    assert r.n_steps == 683
    assert np.isclose(r.k, K)
    assert 745.0 < s.gt_path_length < 760.0            # ~752.9 m GPS path
    gnss_t, gnss_ne = _trusted(s)
    open_track = reanchored_track(r.step_t, r.step_len, r.raw_heading,
                                  gnss_t, gnss_ne, np.inf)
    assert np.isclose(loop_closure_error(open_track), 39.0, atol=1.0)


def test_heldout_rmse_matches_baseline():
    s = load_phone(DATA, name="ma_ling")
    r = run_pdr(s, use_mag=False, k=K)
    gnss_t, gnss_ne = _trusted(s)
    for interval, expected in BASELINE.items():
        rmse = heldout_reanchor_rmse(r.step_t, r.step_len, r.raw_heading,
                                     gnss_t, gnss_ne, interval)
        assert abs(rmse - expected) < max(2.0, 0.15 * expected), \
            f"held-out RMSE at {interval:g}s = {rmse:.1f} m, expected ~{expected} m"
