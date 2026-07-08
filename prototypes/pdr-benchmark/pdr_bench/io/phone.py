"""Loader for phone sensor-logger exports (Sensor Logger by Kelvin Choi).

Export layout: one CSV per sensor (Accelerometer, Gravity, Gyroscope, Magnetometer,
Location), each with `time` (Unix epoch nanoseconds) on one shared device clock.
Two differences from GEOLOC drive this adapter:
  - Sensor Logger's Accelerometer stream excludes gravity, so raw specific force is
    reconstructed as Accelerometer + Gravity (the harness needs the ~+9.81 up-axis
    signal for Madgwick's tilt reference and the Weinberg amplitude).
  - The phone GPS track is the only absolute source, so it serves as gt_ne; there is
    no foot-mounted per-stride ground truth (stride arrays are empty).
`time` is ~1.7e18 ns, past float64's exact-integer range, so timestamps are rebased
to a common origin in the integer domain before converting to seconds.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import CRS, Transformer

from pdr_bench.io.session import ImuSession
from pdr_bench.mapmatch.georef import GeoRef, utm_crs_for
from pdr_bench.pdr.preprocess import resample


def _read_xyz(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read a Sensor Logger x/y/z sensor csv -> (time_ns int64, (N,3) float)."""
    df = pd.read_csv(path)
    return df["time"].to_numpy(np.int64), df[["x", "y", "z"]].to_numpy(float)


def load_phone(export_dir: str | Path,
    name: str = "phone",
) -> ImuSession:
    """Load a Sensor Logger export directory into an ImuSession."""
    d = Path(export_dir)
    a_tn, accel_lin = _read_xyz(d / "Accelerometer.csv")
    grav_tn, grav = _read_xyz(d / "Gravity.csv")
    g_tn, gyro = _read_xyz(d / "Gyroscope.csv")
    m_tn, mag = _read_xyz(d / "Magnetometer.csv")
    loc = pd.read_csv(d / "Location.csv")
    loc_tn = loc["time"].to_numpy(np.int64)

    # rebase all streams to a common origin in integer ns, then convert to seconds
    t0 = min(a_tn[0], grav_tn[0], g_tn[0], m_tn[0], loc_tn[0])
    a_t, grav_t, g_t, m_t, gt_t = ((tn - t0) * 1e-9
                                   for tn in (a_tn, grav_tn, g_tn, m_tn, loc_tn))

    # reconstruct raw specific force: Sensor Logger's Accelerometer excludes gravity
    accel = accel_lin + resample(grav_t, grav, a_t)
    norm = float(np.median(np.hypot(np.hypot(accel[:, 0], accel[:, 1]), accel[:, 2])))
    if not 6.0 < norm < 14.0:
        raise ValueError(f"reconstructed accel median magnitude {norm:.2f} m/s^2 is "
                         "not ~9.81; check the Accelerometer + Gravity reconstruction")

    # phone GPS -> local North-East metres (origin = first fix)
    lat, lon = loc["latitude"].to_numpy(float), loc["longitude"].to_numpy(float)
    utm = utm_crs_for(float(lat.mean()), float(lon.mean()))
    tf = Transformer.from_crs(CRS.from_epsg(4326), utm, always_xy=True)
    e, n = (np.asarray(v) for v in tf.transform(lon, lat))
    e0, n0 = float(e[0]), float(n[0])
    gt_ne = np.column_stack([n - n0, e - e0])

    return ImuSession(
        name=name,
        accel_t=a_t, accel=accel,
        gyro_t=g_t, gyro=gyro,
        mag_t=m_t, mag=mag,
        mag_ainv=np.eye(3), mag_bias=np.zeros(3),
        gt_t=gt_t, gt_ne=gt_ne,
        stride_t=np.zeros(0), stride_len=np.zeros(0),
        meta={"utm_epsg": utm.to_epsg(),
              "ne_origin_en": (e0, n0),
              "gps_horizontal_acc_m": loc["horizontalAccuracy"].to_numpy(float),
              "accel_median_norm_m_s2": norm,
              "export_dir": str(d)},
    )


def phone_georef(session: ImuSession) -> GeoRef:
    """Trivial georef: local NE (origin = first GPS fix) maps to absolute UTM.

    The phone GPS IS the reference, so there is nothing to fit; georeference() would
    fit GPS onto itself (residual 0 by construction). r=I, t=UTM origin makes every
    GeoRef method reproduce the original UTM / lon-lat for the OSM bbox and matcher."""
    e0, n0 = session.meta["ne_origin_en"]
    return GeoRef(r=np.eye(2), t=np.array([e0, n0]),
                  utm=CRS.from_epsg(session.meta["utm_epsg"]), residual_m=0.0)
