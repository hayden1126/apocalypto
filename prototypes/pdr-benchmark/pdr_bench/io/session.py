"""Common intermediate representation for one pedestrian walk recording."""
from dataclasses import dataclass, field

import numpy as np


@dataclass
class ImuSession:
    """Time-aligned raw IMU streams + ground truth for one walk.

    Sensor streams keep their own timestamps (GPS time-of-week, seconds). They are
    each ~200 Hz but not mutually synchronized, so resample before fusing them.
    Ground truth (gt_ne) is a foot-mounted trajectory in a local North-East metre
    frame; stride_t / stride_len are ground-truth flat-foot instants and lengths.
    """
    name: str
    accel_t: np.ndarray    # (Na,)  s
    accel: np.ndarray      # (Na, 3) m/s^2 specific force; rest-gravity sign is loader-specific (GEOLOC +z up, phone normalized to the iOS export frame)
    gyro_t: np.ndarray     # (Ng,)  s
    gyro: np.ndarray       # (Ng, 3) rad/s
    mag_t: np.ndarray      # (Nm,)  s
    mag: np.ndarray        # (Nm, 3) normalized field (see geoloc loader notes)
    mag_ainv: np.ndarray   # (3, 3) soft-iron + scale
    mag_bias: np.ndarray   # (3,)   hard-iron bias
    gt_t: np.ndarray       # (Ngt,) s
    gt_ne: np.ndarray      # (Ngt, 2) North, East metres
    stride_t: np.ndarray   # (Ns,)  s, ground-truth flat-foot instants
    stride_len: np.ndarray  # (Ns,) m, ground-truth stride lengths
    meta: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        """Recording length in seconds."""
        return float(self.accel_t[-1] - self.accel_t[0])

    @property
    def gt_path_length(self) -> float:
        """Total ground-truth path length in metres."""
        return float(np.hypot(*np.diff(self.gt_ne, axis=0).T).sum())
