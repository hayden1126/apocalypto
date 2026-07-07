"""Loader for the GEOLOC/ULISS pedestrian inertial dataset (DOI 10.57745/ZCBIIB).

Layout per track: raw_measurement/{acceleration,rotation,magnetic}.csv (tow,nano,x,y,z),
Mag_Calib/{Ainv,Bias}.mat, ground_truth/{gt_trajectory,stride_instants}.csv.
Sensor time = tow (GPS time-of-week, s) + nano * 1e-9.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.io as sio

from pdr_bench.io.session import ImuSession

# track id -> (relative path, environment, documented length m)
TRACK_INFO = {
    "TEST_01": ("S1/TEST_01", "Bouguenais campus, outdoor + office/stairs", 251),
    "TEST_02": ("S1/TEST_02", "Bouguenais campus, outdoor", 230),
    "TEST_03": ("S1/TEST_03", "Bouguenais campus, outdoor + office/stairs", 288),
    "TEST_04": ("S2/TEST_04", "Campus woods, grass/muddy path", 374),
    "TEST_05": ("S2/TEST_05", "Nantes, ile de Nantes, urban", 563),
    "TEST_06": ("S2/TEST_06", "Saint-Herblain Atlantis, parking lot", 464),
}

# Cleanest outdoor tracks for a first pass (TEST_01/03 include indoor stairs).
OUTDOOR_TRACKS = ["TEST_02", "TEST_04", "TEST_05", "TEST_06"]


def _read_xyz(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read a tow/nano/x/y/z sensor csv -> (time_s, (N,3) array)."""
    df = pd.read_csv(path)
    t = df["tow"].to_numpy(float) + df["nano"].to_numpy(float) * 1e-9
    return t, df[["x", "y", "z"]].to_numpy(float)


def load_track(root: str | Path,
    track: str,
) -> ImuSession:
    """Load one GEOLOC track into an ImuSession."""
    if track not in TRACK_INFO:
        raise KeyError(f"unknown track {track!r}; known: {list(TRACK_INFO)}")
    rel, env, length = TRACK_INFO[track]
    d = Path(root) / rel
    raw = d / "raw_measurement"
    a_t, accel = _read_xyz(raw / "acceleration.csv")
    g_t, gyro = _read_xyz(raw / "rotation.csv")
    m_t, mag = _read_xyz(raw / "magnetic.csv")
    ainv = sio.loadmat(d / "Mag_Calib" / "Ainv.mat")["Ainv"].astype(float)
    bias = sio.loadmat(d / "Mag_Calib" / "Bias.mat")["Bias"].astype(float).ravel()
    gt = pd.read_csv(d / "ground_truth" / "gt_trajectory.csv")
    stride = pd.read_csv(d / "ground_truth" / "stride_instants.csv")
    return ImuSession(
        name=track,
        accel_t=a_t, accel=accel,
        gyro_t=g_t, gyro=gyro,
        mag_t=m_t, mag=mag,
        mag_ainv=ainv, mag_bias=bias,
        gt_t=gt["tow"].to_numpy(float),
        gt_ne=gt[["pos_x", "pos_y"]].to_numpy(float),
        stride_t=stride["stride_time"].to_numpy(float),
        stride_len=stride["length"].to_numpy(float),
        meta={"environment": env, "documented_length_m": length, "root": str(root)},
    )
