"""Overlay plot of ground truth, raw PDR, and map-matched tracks on the walk graph."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def plot_overlay(graph,
    gt_utm: np.ndarray,
    pdr_utm: np.ndarray,
    matched_utm: np.ndarray | None,
    title: str,
    path: str,
) -> None:
    """Save a UTM overlay (graph light grey, gt green, PDR blue, matched orange)."""
    fig, ax = plt.subplots(figsize=(9, 9))
    if graph is not None:
        for u, v, d in graph.edges(data=True):
            geom = d.get("geometry")
            if geom is not None:
                ax.plot(*geom.xy, color="0.82", lw=0.8, zorder=1)
            else:
                ax.plot([graph.nodes[u]["x"], graph.nodes[v]["x"]],
                        [graph.nodes[u]["y"], graph.nodes[v]["y"]],
                        color="0.82", lw=0.8, zorder=1)
    ax.plot(gt_utm[:, 0], gt_utm[:, 1], color="green", lw=2.2, label="ground truth", zorder=4)
    ax.plot(pdr_utm[:, 0], pdr_utm[:, 1], color="tab:blue", lw=1.4, label="PDR (gyro-only)", zorder=3)
    if matched_utm is not None:
        ax.plot(matched_utm[:, 0], matched_utm[:, 1], color="tab:orange", lw=1.4,
                label="map-matched", zorder=3)
    ax.plot(gt_utm[0, 0], gt_utm[0, 1], "ko", ms=9, label="start", zorder=5)
    ax.set_aspect("equal")
    ax.set_xlabel("easting (m)")
    ax.set_ylabel("northing (m)")
    ax.set_title(title)
    ax.legend(loc="best", fontsize=9)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)
