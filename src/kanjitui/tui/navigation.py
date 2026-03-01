from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StripCell:
    cp: int | None
    is_current: bool


@dataclass(frozen=True)
class GridPosition:
    index: int
    row: int
    col: int


def build_strip(ordered_cps: list[int], pos: int, radius: int = 10) -> list[StripCell]:
    if radius < 0:
        raise ValueError("radius must be >= 0")

    cells: list[StripCell] = []
    for offset in range(-radius, radius + 1):
        idx = pos + offset
        if 0 <= idx < len(ordered_cps):
            cells.append(StripCell(cp=ordered_cps[idx], is_current=(offset == 0)))
        else:
            cells.append(StripCell(cp=None, is_current=(offset == 0)))
    return cells


def move_grid_index(index: int, total: int, cols: int, key: str) -> int:
    if total <= 0:
        return 0
    if cols <= 0:
        cols = 1

    idx = max(0, min(index, total - 1))
    row = idx // cols
    col = idx % cols
    max_row = (total - 1) // cols

    if key == "left":
        if col > 0:
            idx -= 1
    elif key == "right":
        if idx + 1 < total and col + 1 < cols:
            idx += 1
    elif key == "up":
        if row > 0:
            idx -= cols
    elif key == "down":
        if row < max_row and idx + cols < total:
            idx += cols

    return idx


def grid_position(index: int, cols: int) -> GridPosition:
    if cols <= 0:
        cols = 1
    row = max(index, 0) // cols
    col = max(index, 0) % cols
    return GridPosition(index=max(index, 0), row=row, col=col)
