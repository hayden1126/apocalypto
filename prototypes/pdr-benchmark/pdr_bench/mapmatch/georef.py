"""Georeference the local North-East frame to absolute coordinates via GNSS.

The ground truth and PDR tracks live in a local NE metre frame with an unknown
origin. NAV-PVT fixes in gnss.ubx give absolute lat/lon on the same GPS time base,
so a rigid (rotation + translation) fit maps local NE onto UTM, and from there to
lat/lon for OSM. The fit residual doubles as an independent GNSS-vs-GT cross-check.
"""
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer
from pyubx2 import UBXReader


def load_gnss_pvt(ubx_path: str | Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract (tow_s, lat_deg, lon_deg) from NAV-PVT messages with a 3D fix."""
    tow, lat, lon = [], [], []
    with open(ubx_path, "rb") as fh:
        for _, msg in UBXReader(fh):
            if msg is not None and msg.identity == "NAV-PVT" and msg.fixType >= 3:
                tow.append(msg.iTOW / 1000.0)
                lat.append(msg.lat)
                lon.append(msg.lon)
    return np.array(tow), np.array(lat), np.array(lon)


def utm_crs_for(lat: float,
    lon: float,
) -> CRS:
    """UTM CRS covering a lon/lat (WGS84)."""
    zone = int((lon + 180) // 6) + 1
    epsg = (32600 if lat >= 0 else 32700) + zone
    return CRS.from_epsg(epsg)


def _kabsch_2d(a: np.ndarray,
    b: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Rigid (rotation R, translation t) minimizing ||R@a + t - b|| for 2D point sets."""
    ca, cb = a.mean(0), b.mean(0)
    h = (a - ca).T @ (b - cb)
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    r = vt.T @ np.diag([1.0, d]) @ u.T
    return r, cb - r @ ca


@dataclass
class GeoRef:
    """Rigid map from local NE metres to UTM, plus the CRS and fit residual."""
    r: np.ndarray            # (2,2) rotation on (E, N)
    t: np.ndarray            # (2,) translation
    utm: CRS
    residual_m: float

    def ne_to_utm(self, ne: np.ndarray) -> np.ndarray:
        """Map (N,2) local [North, East] metres to (N,2) UTM [easting, northing]."""
        return ne[:, ::-1] @ self.r.T + self.t       # (East, North) -> UTM

    def ne_to_lonlat(self, ne: np.ndarray) -> np.ndarray:
        """Map (N,2) local [North, East] metres to (N,2) [lon, lat] degrees."""
        utm_en = self.ne_to_utm(ne)
        tf = Transformer.from_crs(self.utm, CRS.from_epsg(4326), always_xy=True)
        lon, lat = tf.transform(utm_en[:, 0], utm_en[:, 1])
        return np.column_stack([lon, lat])


def georeference(gt_t: np.ndarray,
    gt_ne: np.ndarray,
    gnss_tow: np.ndarray,
    gnss_lat: np.ndarray,
    gnss_lon: np.ndarray,
) -> GeoRef:
    """Fit the local-NE -> UTM transform from time-matched GT and GNSS samples."""
    utm = utm_crs_for(float(gnss_lat.mean()), float(gnss_lon.mean()))
    tf = Transformer.from_crs(CRS.from_epsg(4326), utm, always_xy=True)
    ge, gn = tf.transform(gnss_lon, gnss_lat)
    gnss_en = np.column_stack([ge, gn])
    # GT as (East, North), interpolated onto the GNSS timestamps that overlap it
    m = (gnss_tow >= gt_t[0]) & (gnss_tow <= gt_t[-1])
    gt_e = np.interp(gnss_tow[m], gt_t, gt_ne[:, 1])
    gt_n = np.interp(gnss_tow[m], gt_t, gt_ne[:, 0])
    gt_en = np.column_stack([gt_e, gt_n])
    r, t = _kabsch_2d(gt_en, gnss_en[m])
    resid = np.hypot(*(gt_en @ r.T + t - gnss_en[m]).T)
    return GeoRef(r=r, t=t, utm=utm, residual_m=float(np.sqrt(np.mean(resid ** 2))))
