from __future__ import annotations

import math
from typing import Any, List, Tuple


def plot_path(
    ax: Any,
    points: List[Tuple[float, float]],
    *,
    color: str,
    linewidth: float,
    linestyle: str = "-",
    zorder: float = 2.0,
) -> None:
    ax.plot(
        [point[0] for point in points],
        [point[1] for point in points],
        color=color,
        linewidth=linewidth,
        linestyle=linestyle,
        solid_capstyle="round",
        solid_joinstyle="round",
        zorder=zorder,
    )


def arrow_label_position(
    start: Tuple[float, float],
    end: Tuple[float, float],
    *,
    distance: float,
) -> Tuple[float, float]:
    mx = (float(start[0]) + float(end[0])) / 2.0
    my = (float(start[1]) + float(end[1])) / 2.0
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    norm = math.hypot(dx, dy) or 1.0
    return (mx - dy / norm * distance, my + dx / norm * distance)


def draw_magnetic_marker(
    ax: Any,
    center: Tuple[float, float],
    *,
    marker: str,
    size: float,
    color: str,
    linewidth: float,
    circle_cls: Any,
) -> None:
    px, py = float(center[0]), float(center[1])
    radius = max(float(size) * 0.45, 0.06)
    if marker == "out_of_page":
        ax.add_patch(
            circle_cls((px, py), radius, edgecolor=color, facecolor="none", linewidth=max(0.8, linewidth * 0.8), zorder=2.5)
        )
        ax.add_patch(circle_cls((px, py), max(radius * 0.24, 0.03), edgecolor="none", facecolor=color, zorder=2.6))
        return
    if marker == "into_page":
        ax.add_patch(
            circle_cls((px, py), radius, edgecolor=color, facecolor="none", linewidth=max(0.8, linewidth * 0.8), zorder=2.5)
        )
        arm = radius * 0.58
        plot_path(
            ax,
            [(px - arm, py - arm), (px + arm, py + arm)],
            color=color,
            linewidth=max(0.8, linewidth * 0.85),
            zorder=2.6,
        )
        plot_path(
            ax,
            [(px - arm, py + arm), (px + arm, py - arm)],
            color=color,
            linewidth=max(0.8, linewidth * 0.85),
            zorder=2.6,
        )
        return
    ax.text(px, py, marker or "x", fontsize=max(size * 1.8, 10.0), color=color, ha="center", va="center", zorder=2.6)
