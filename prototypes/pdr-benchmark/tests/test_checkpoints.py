"""Tests for surveyed-checkpoint ingestion (load_checkpoints).

Synthetic Sensor Logger exports (reusing the phone-adapter fixtures) pin the two
risky contracts: marker times must land on the loader's rebased-seconds clock via
the SAME t0, and surveyed lat/lon must convert to NE through the loader's own
georef (no second transformer). Label-join multiplicity (a checkpoint crossed on
several loops) and the order-join fallback are covered too.
"""
import numpy as np
import pandas as pd
import pytest

from pdr_bench.io.phone import load_checkpoints, load_phone
from tests.test_phone import EPOCH_NS, _make_export

SEC_NS = 1_000_000_000


def _write_annotation(export_dir, times_ns, texts):
    pd.DataFrame({"time": np.asarray(times_ns, np.int64),
                  "seconds_elapsed": np.zeros(len(texts)),
                  "text": texts}).to_csv(export_dir / "Annotation.csv", index=False)


def test_load_checkpoints_uses_loader_t0(tmp_path):
    # Marker time keyed to the 2nd GPS fix's epoch ns must rebase to gt_t[1] exactly.
    d = _make_export(tmp_path)                 # GPS 1 Hz from EPOCH_NS; IMU also at EPOCH_NS
    s = load_phone(d)
    _write_annotation(d, [EPOCH_NS + SEC_NS], ["cp1"])
    pd.DataFrame({"label": ["cp1"], "lat": [48.0], "lon": [-1.5]}).to_csv(
        tmp_path / "cp.csv", index=False)
    mt, mne, labels = load_checkpoints(s, tmp_path / "cp.csv")
    assert labels == ["cp1"]
    assert np.isclose(mt[0], s.gt_t[1], atol=1e-6)      # == 1.0 s, not raw epoch ns


def test_load_checkpoints_frame_conversion(tmp_path):
    # Surveyed lat/lon convert to NE through the loader's georef: origin fix -> [0,0],
    # 0.0001 deg north -> ~11.1 m North with negligible East.
    d = _make_export(tmp_path)
    s = load_phone(d)
    _write_annotation(d, [EPOCH_NS + SEC_NS, EPOCH_NS + 2 * SEC_NS], ["origin", "north"])
    pd.DataFrame({"label": ["origin", "north"], "lat": [48.0, 48.0001],
                  "lon": [-1.5, -1.5]}).to_csv(tmp_path / "cp.csv", index=False)
    mt, mne, labels = load_checkpoints(s, tmp_path / "cp.csv")
    by = {lab: mne[i] for i, lab in enumerate(labels)}
    assert np.allclose(by["origin"], 0.0, atol=1e-3)
    assert np.isclose(by["north"][0], 11.1, atol=0.5)
    assert abs(by["north"][1]) < 0.5


def test_ne_schema_used_directly(tmp_path):
    # A label,n,e checkpoint csv is used verbatim (no lat/lon conversion).
    d = _make_export(tmp_path)
    s = load_phone(d)
    _write_annotation(d, [EPOCH_NS + SEC_NS], ["cp1"])
    pd.DataFrame({"label": ["cp1"], "n": [12.5], "e": [-3.0]}).to_csv(
        tmp_path / "cp.csv", index=False)
    _, mne, _ = load_checkpoints(s, tmp_path / "cp.csv")
    assert np.allclose(mne[0], [12.5, -3.0])


def test_label_join_drops_unmatched_and_keeps_repeats(tmp_path):
    # start/end bookends fail to match a checkpoint and drop out; a checkpoint crossed
    # twice yields two markers (both carrying its surveyed coord).
    d = _make_export(tmp_path)
    s = load_phone(d)
    _write_annotation(d, [EPOCH_NS, EPOCH_NS + SEC_NS, EPOCH_NS + 2 * SEC_NS,
                          EPOCH_NS + 3 * SEC_NS],
                      ["start", "cp1", "cp1", "end"])
    pd.DataFrame({"label": ["cp1"], "n": [5.0], "e": [0.0]}).to_csv(
        tmp_path / "cp.csv", index=False)
    mt, mne, labels = load_checkpoints(s, tmp_path / "cp.csv")
    assert labels == ["cp1", "cp1"]
    assert np.allclose(mt, [1.0, 2.0])
    assert np.allclose(mne, [[5.0, 0.0], [5.0, 0.0]])


def test_order_join_zips_inner_markers(tmp_path):
    # order fallback: drop 1 leading + 1 trailing bookend, zip the rest in file order.
    d = _make_export(tmp_path)
    s = load_phone(d)
    _write_annotation(d, [EPOCH_NS, EPOCH_NS + SEC_NS, EPOCH_NS + 2 * SEC_NS,
                          EPOCH_NS + 3 * SEC_NS],
                      ["", "", "", ""])          # unlabeled: label join impossible
    pd.DataFrame({"label": ["a", "b"], "n": [1.0, 2.0], "e": [0.0, 0.0]}).to_csv(
        tmp_path / "cp.csv", index=False)
    mt, mne, labels = load_checkpoints(s, tmp_path / "cp.csv", join="order", n_bookends=2)
    assert labels == ["a", "b"]
    assert np.allclose(mt, [1.0, 2.0])


def test_empty_annotation_skips(tmp_path):
    # 0-byte Annotation.csv (the real shakedown case) -> empty arrays, no raise.
    d = _make_export(tmp_path)
    s = load_phone(d)
    (d / "Annotation.csv").write_text("")
    pd.DataFrame({"label": ["cp1"], "lat": [48.0], "lon": [-1.5]}).to_csv(
        tmp_path / "cp.csv", index=False)
    mt, mne, labels = load_checkpoints(s, tmp_path / "cp.csv")
    assert mt.size == 0 and mne.shape == (0, 2) and labels == []


def test_missing_annotation_skips(tmp_path):
    d = _make_export(tmp_path)               # _make_export writes no Annotation.csv
    s = load_phone(d)
    pd.DataFrame({"label": ["cp1"], "lat": [48.0], "lon": [-1.5]}).to_csv(
        tmp_path / "cp.csv", index=False)
    mt, mne, labels = load_checkpoints(s, tmp_path / "cp.csv")
    assert mt.size == 0 and labels == []
