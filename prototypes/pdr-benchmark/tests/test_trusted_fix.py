"""Tests for the trusted-fix mask (mechanism 1 speed/innovation gate, mechanism 2
cold-start lock, loose accuracy backstop). Isolate each filter by disabling the
others (lock_disp_m huge -> no trim; max_speed_mps huge -> no speed gate;
acc_backstop_m=None -> no backstop)."""
import numpy as np

from pdr_bench.eval.phone_metrics import loop_closure_error
from pdr_bench.pdr.reanchor import reanchored_track
from pdr_bench.pdr.trusted_fix import trusted_fix_mask


def test_rejects_speed_jump_outlier():
    # 10 fixes north at 1 m/s; fix 5 teleports 800 m (the ma_ling 808 m spike analogue).
    t = np.arange(10).astype(float)
    ne = np.column_stack([np.arange(10.0), np.zeros(10)])
    ne[5] = [800.0, 0.0]
    keep = trusted_fix_mask(t, ne, max_speed_mps=5.0, acc_backstop_m=None, lock_disp_m=1e9)
    assert not keep[5]
    assert keep[[0, 1, 2, 3, 4, 6, 7, 8, 9]].all()     # neighbours survive (vs last accepted)


def test_trims_cold_start_scatter():
    # 5 scattered pre-lock fixes, then 10 tight stationary fixes: lock latches at fix 5.
    rng = np.random.default_rng(0)
    scatter = rng.normal(scale=30.0, size=(5, 2))
    stable = rng.normal(scale=0.5, size=(10, 2))
    ne = np.vstack([scatter, stable])
    t = np.arange(15).astype(float)
    keep = trusted_fix_mask(t, ne, max_speed_mps=1e9, acc_backstop_m=None,
                            lock_window=5, lock_disp_m=5.0)
    assert not keep[:5].any()
    assert keep[5:].all()


def test_keeps_pessimistic_reported_accuracy():
    # spatially clean fixes with iOS's ~7x pessimistic 14 m reports must survive.
    t = np.arange(10).astype(float)
    ne = np.column_stack([np.arange(10.0), np.zeros(10)])
    keep = trusted_fix_mask(t, ne, np.full(10, 14.0), acc_backstop_m=50.0, lock_disp_m=1e9)
    assert keep.all()


def test_backstop_rejects_absurd_reported():
    # the 807 m self-reported fix is dropped by the loose backstop even if spatially odd.
    t = np.arange(10).astype(float)
    ne = np.column_stack([np.arange(10.0), np.zeros(10)])
    acc = np.full(10, 14.0)
    acc[3] = 807.0
    keep = trusted_fix_mask(t, ne, acc, acc_backstop_m=50.0, lock_disp_m=1e9,
                            max_speed_mps=1e9)
    assert not keep[3]
    assert keep[[0, 1, 2, 4, 5, 6, 7, 8, 9]].all()


def test_never_starves_below_min_fixes():
    # every fix looks like a 100 m/s jump; relaxation must still hand back >= min_fixes.
    t = np.arange(4).astype(float)
    ne = np.column_stack([np.arange(4.0) * 100.0, np.zeros(4)])
    keep = trusted_fix_mask(t, ne, max_speed_mps=5.0, acc_backstop_m=None,
                            lock_disp_m=1e9, min_fixes=2)
    assert keep.sum() >= 2


def test_innovation_gate_rejects_pdr_inconsistent_fix():
    # opt-in innovation gate: a fix far from the PDR-predicted position is rejected.
    t = np.arange(10).astype(float)
    ne = np.column_stack([np.arange(10.0), np.zeros(10)])
    pdr_ne = ne.copy()
    ne[6] = [6.0, 40.0]                       # 40 m off the PDR track
    keep = trusted_fix_mask(t, ne, pdr_t=t, pdr_ne=pdr_ne, use_innovation=True,
                            max_speed_mps=1e9, acc_backstop_m=None, lock_disp_m=1e9,
                            innovation_floor_m=15.0)
    assert not keep[6]


def test_masking_leaves_loop_closure_invariant():
    # the blast-radius keystone: loop closure depends only on step_len/heading, so any
    # trusted-fix subset (single start anchor) yields the same end-vs-start gap.
    n = 60
    step_t = np.arange(n) * 0.5
    step_len = np.ones(n)
    raw_heading = np.linspace(0.0, 2.0 * np.pi, n)
    gnss_t = np.arange(n) * 0.5
    gnss_ne = np.column_stack([np.cumsum(np.cos(raw_heading)), np.cumsum(np.sin(raw_heading))])
    full = reanchored_track(step_t, step_len, raw_heading, gnss_t, gnss_ne, np.inf)
    sub = reanchored_track(step_t, step_len, raw_heading, gnss_t[::3], gnss_ne[::3], np.inf)
    assert np.isclose(loop_closure_error(full), loop_closure_error(sub), atol=1e-6)
