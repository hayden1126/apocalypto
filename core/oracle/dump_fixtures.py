#!/usr/bin/env python3
"""Dump numerical-oracle fixtures from the Python PDR prototype for the Rust port.

Run under the prototype venv so `pdr_bench` imports:
    cd prototypes/pdr-benchmark && PYTHONPATH=. .venv/bin/python ../../core/oracle/dump_fixtures.py

Writes JSON fixtures into core/oracle/fixtures/ (path is relative to this file, not cwd).
"""
import json
from pathlib import Path

import numpy as np

from pdr_bench.eval.geo import interp_ne
from pdr_bench.pdr.trusted_fix import trusted_fix_mask

OUT = Path(__file__).resolve().parent / "fixtures"
OUT.mkdir(exist_ok=True)


def dump(name, obj):
    (OUT / f"{name}.json").write_text(json.dumps(obj, indent=2))
    print("wrote", OUT / f"{name}.json")


def dump_interp_ne():
    t_src = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    ne_src = np.array([[0.0, 0.0], [1.0, 2.0], [4.0, 1.0], [9.0, -1.0], [16.0, 3.0]])
    t_query = np.array([-1.0, 0.0, 0.5, 1.5, 2.25, 4.0, 5.0])  # includes both clamp ends
    expected = interp_ne(t_src, ne_src, t_query)
    dump("interp_ne", {
        "t_src": t_src.tolist(),
        "ne_src": ne_src.tolist(),
        "t_query": t_query.tolist(),
        "expected": expected.tolist(),
    })


def dump_trusted_fix_mask():
    # A well-margined realistic track: 6 scattered cold-start fixes (~40 m), then 50 fixes
    # walking north at 1 m/s; an unambiguous 900 m teleport at index 30; an absurd 300 m
    # self-reported accuracy at index 40. Features are wide of every threshold, so the
    # boolean mask is stable across float implementations.
    rng = np.random.default_rng(7)
    cold = rng.normal(scale=40.0, size=(6, 2))
    walk = np.column_stack([np.arange(50.0), np.zeros(50)]) + rng.normal(scale=0.3, size=(50, 2))
    gnss_ne = np.vstack([cold, walk])
    gnss_t = np.arange(len(gnss_ne)).astype(float)
    gnss_ne[30] = [900.0, 0.0]
    acc = np.full(len(gnss_ne), 14.0)
    acc[40] = 300.0
    params = {"max_speed_mps": 5.0, "lock_window": 5, "lock_disp_m": 5.0, "acc_backstop_m": 50.0}
    mask = trusted_fix_mask(
        gnss_t, gnss_ne, acc,
        max_speed_mps=params["max_speed_mps"],
        lock_window=params["lock_window"],
        lock_disp_m=params["lock_disp_m"],
        acc_backstop_m=params["acc_backstop_m"],
    )
    dump("trusted_fix_mask", {
        "gnss_t": gnss_t.tolist(),
        "gnss_ne": gnss_ne.tolist(),
        "reported_acc_m": acc.tolist(),
        "params": params,
        "expected_mask": [bool(b) for b in mask],
    })


if __name__ == "__main__":
    dump_interp_ne()
    dump_trusted_fix_mask()
