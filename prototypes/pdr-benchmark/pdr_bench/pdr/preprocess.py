"""Resampling and bias estimation shared by the PDR stages."""
import numpy as np

from pdr_bench.io.session import ImuSession


def resample(t_src: np.ndarray,
    x_src: np.ndarray,
    t_grid: np.ndarray,
) -> np.ndarray:
    """Linearly interpolate a (N,) or (N, k) stream onto a common time grid."""
    if x_src.ndim == 1:
        return np.interp(t_grid, t_src, x_src)
    return np.column_stack([np.interp(t_grid, t_src, x_src[:, j])
                            for j in range(x_src.shape[1])])


def common_grid(session: ImuSession,
    fs: float = 100.0,
) -> np.ndarray:
    """Uniform time grid (s) over the span where accel, gyro and mag all overlap."""
    t0 = max(session.accel_t[0], session.gyro_t[0], session.mag_t[0])
    t1 = min(session.accel_t[-1], session.gyro_t[-1], session.mag_t[-1])
    return np.arange(t0, t1, 1.0 / fs)


def estimate_gyro_bias(session: ImuSession,
    static_seconds: float = 35.0,
) -> np.ndarray:
    """Mean gyro (rad/s, per axis) over the opening static phase."""
    mask = session.gyro_t < session.gyro_t[0] + static_seconds
    return session.gyro[mask].mean(axis=0)
