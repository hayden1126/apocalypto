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


if __name__ == "__main__":
    dump_interp_ne()
