"""The headline chart: each model's error as a dot, with its 95% interval as a line.

Colors come from the portfolio's chart palette. The baseline is a neutral gray, since
it is the reference. The model is the first series color. Each row is also named on
the axis, so color is never the only way to tell them apart.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to files only, so it works on servers with no screen

import matplotlib.pyplot as plt  # noqa: E402

from .metrics import Estimate  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES_1 = "#2a78d6"


def plot_mae(rows: list[tuple[str, Estimate, str]], n_test: int, path: Path) -> Path:
    """Save a dot-and-interval chart of MAE, one row per (label, estimate, color).

    The x axis starts at zero, so the length of each gap is honest.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 3.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    top = max(r[1].ci_high for r in rows)
    for i, (_label, est, color) in enumerate(reversed(rows)):
        ax.hlines(i, est.ci_low, est.ci_high, color=color, linewidth=2)
        ax.plot(est.value, i, "o", color=color, markersize=9, markeredgecolor=SURFACE)
        ax.annotate(
            f"{est.value:.2f}  ({est.ci_low:.2f} to {est.ci_high:.2f})",
            (est.ci_high, i),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            color=INK_SECONDARY,
            fontsize=9,
        )

    ax.set_yticks(range(len(rows)), [r[0] for r in reversed(rows)], color=INK, fontsize=10)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlim(0, top * 1.35)
    ax.set_xlabel(
        f"Mean absolute error on {n_test} test rows (lower is better)",
        color=INK_SECONDARY,
        fontsize=9,
    )
    ax.set_title(
        "Error of each model, with 95% bootstrap interval",
        loc="left",
        color=INK,
        fontsize=11,
    )
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(axis="x", colors=MUTED, labelsize=9)
    ax.tick_params(axis="y", length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)

    fig.tight_layout()
    # No "Software" stamp, so the file only changes when the chart does.
    fig.savefig(path, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)
    return path
