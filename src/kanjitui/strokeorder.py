from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
from xml.etree import ElementTree as ET


TOKEN_RE = re.compile(r"[MmLlHhVvCcSsQqTtZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


@dataclass(frozen=True)
class StrokeOrderData:
    ch: str
    strokes: list[list[tuple[float, float]]]
    width: float
    height: float
    source_path: Path


def _cubic_sample(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int = 18,
) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for i in range(1, max(2, steps) + 1):
        t = i / max(2, steps)
        it = 1.0 - t
        x = (
            it * it * it * p0[0]
            + 3 * it * it * t * p1[0]
            + 3 * it * t * t * p2[0]
            + t * t * t * p3[0]
        )
        y = (
            it * it * it * p0[1]
            + 3 * it * it * t * p1[1]
            + 3 * it * t * t * p2[1]
            + t * t * t * p3[1]
        )
        out.append((x, y))
    return out


def _quadratic_sample(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    steps: int = 14,
) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for i in range(1, max(2, steps) + 1):
        t = i / max(2, steps)
        it = 1.0 - t
        x = it * it * p0[0] + 2 * it * t * p1[0] + t * t * p2[0]
        y = it * it * p0[1] + 2 * it * t * p1[1] + t * t * p2[1]
        out.append((x, y))
    return out


def parse_path_points(path_d: str) -> list[tuple[float, float]]:
    tokens = TOKEN_RE.findall(path_d)
    if not tokens:
        return []

    out: list[tuple[float, float]] = []
    i = 0
    cmd: str | None = None
    prev_cmd = ""
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    last_cubic_ctrl: tuple[float, float] | None = None
    last_quad_ctrl: tuple[float, float] | None = None

    def is_cmd(tok: str) -> bool:
        return len(tok) == 1 and tok.isalpha()

    def next_num() -> float:
        nonlocal i
        value = float(tokens[i])
        i += 1
        return value

    while i < len(tokens):
        if is_cmd(tokens[i]):
            cmd = tokens[i]
            i += 1
        if cmd is None:
            break

        rel = cmd.islower()
        op = cmd.upper()

        if op == "M":
            if i + 1 >= len(tokens) or is_cmd(tokens[i]) or is_cmd(tokens[i + 1]):
                break
            x = next_num()
            y = next_num()
            if rel:
                x += cur[0]
                y += cur[1]
            cur = (x, y)
            start = cur
            out.append(cur)
            last_cubic_ctrl = None
            last_quad_ctrl = None
            cmd = "l" if rel else "L"
            prev_cmd = "M"
            continue

        if op == "Z":
            if out and out[-1] != start:
                out.append(start)
            cur = start
            last_cubic_ctrl = None
            last_quad_ctrl = None
            prev_cmd = "Z"
            continue

        if op == "L":
            while i + 1 < len(tokens) and not is_cmd(tokens[i]) and not is_cmd(tokens[i + 1]):
                x = next_num()
                y = next_num()
                if rel:
                    x += cur[0]
                    y += cur[1]
                cur = (x, y)
                out.append(cur)
            last_cubic_ctrl = None
            last_quad_ctrl = None
            prev_cmd = "L"
            continue

        if op == "H":
            while i < len(tokens) and not is_cmd(tokens[i]):
                x = next_num()
                if rel:
                    x += cur[0]
                cur = (x, cur[1])
                out.append(cur)
            last_cubic_ctrl = None
            last_quad_ctrl = None
            prev_cmd = "H"
            continue

        if op == "V":
            while i < len(tokens) and not is_cmd(tokens[i]):
                y = next_num()
                if rel:
                    y += cur[1]
                cur = (cur[0], y)
                out.append(cur)
            last_cubic_ctrl = None
            last_quad_ctrl = None
            prev_cmd = "V"
            continue

        if op == "C":
            while i + 5 < len(tokens) and not is_cmd(tokens[i]):
                x1, y1, x2, y2, x, y = (
                    next_num(),
                    next_num(),
                    next_num(),
                    next_num(),
                    next_num(),
                    next_num(),
                )
                if rel:
                    x1 += cur[0]
                    y1 += cur[1]
                    x2 += cur[0]
                    y2 += cur[1]
                    x += cur[0]
                    y += cur[1]
                seg = _cubic_sample(cur, (x1, y1), (x2, y2), (x, y))
                out.extend(seg)
                cur = (x, y)
                last_cubic_ctrl = (x2, y2)
                last_quad_ctrl = None
            prev_cmd = "C"
            continue

        if op == "S":
            while i + 3 < len(tokens) and not is_cmd(tokens[i]):
                x2, y2, x, y = next_num(), next_num(), next_num(), next_num()
                if prev_cmd in ("C", "S") and last_cubic_ctrl is not None:
                    x1 = 2 * cur[0] - last_cubic_ctrl[0]
                    y1 = 2 * cur[1] - last_cubic_ctrl[1]
                else:
                    x1, y1 = cur
                if rel:
                    x2 += cur[0]
                    y2 += cur[1]
                    x += cur[0]
                    y += cur[1]
                seg = _cubic_sample(cur, (x1, y1), (x2, y2), (x, y))
                out.extend(seg)
                cur = (x, y)
                last_cubic_ctrl = (x2, y2)
                last_quad_ctrl = None
            prev_cmd = "S"
            continue

        if op == "Q":
            while i + 3 < len(tokens) and not is_cmd(tokens[i]):
                x1, y1, x, y = next_num(), next_num(), next_num(), next_num()
                if rel:
                    x1 += cur[0]
                    y1 += cur[1]
                    x += cur[0]
                    y += cur[1]
                seg = _quadratic_sample(cur, (x1, y1), (x, y))
                out.extend(seg)
                cur = (x, y)
                last_quad_ctrl = (x1, y1)
                last_cubic_ctrl = None
            prev_cmd = "Q"
            continue

        if op == "T":
            while i + 1 < len(tokens) and not is_cmd(tokens[i]):
                x, y = next_num(), next_num()
                if prev_cmd in ("Q", "T") and last_quad_ctrl is not None:
                    x1 = 2 * cur[0] - last_quad_ctrl[0]
                    y1 = 2 * cur[1] - last_quad_ctrl[1]
                else:
                    x1, y1 = cur
                if rel:
                    x += cur[0]
                    y += cur[1]
                seg = _quadratic_sample(cur, (x1, y1), (x, y))
                out.extend(seg)
                cur = (x, y)
                last_quad_ctrl = (x1, y1)
                last_cubic_ctrl = None
            prev_cmd = "T"
            continue

        # Unsupported command; skip safely.
        prev_cmd = op

    return out


def _bresenham_line(a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
    x0, y0 = a
    x1, y1 = b
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    out: list[tuple[int, int]] = []
    while True:
        out.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
    return out


def _scale_point(
    pt: tuple[float, float],
    width: float,
    height: float,
    cols: int,
    rows: int,
) -> tuple[int, int]:
    safe_w = max(width, 1.0)
    safe_h = max(height, 1.0)
    x = int(round((pt[0] / safe_w) * (cols - 1)))
    y = int(round((pt[1] / safe_h) * (rows - 1)))
    return max(0, min(cols - 1, x)), max(0, min(rows - 1, y))


def build_tui_stroke_frames(
    data: StrokeOrderData,
    cols: int,
    rows: int,
    stroke_char: str = "#",
) -> list[list[str]]:
    if cols < 4 or rows < 4:
        return []

    stroke_cells: list[list[tuple[int, int]]] = []
    for stroke in data.strokes:
        cells: list[tuple[int, int]] = []
        if not stroke:
            stroke_cells.append(cells)
            continue
        scaled = [_scale_point(pt, data.width, data.height, cols, rows) for pt in stroke]
        if len(scaled) == 1:
            cells = [scaled[0]]
        else:
            for a, b in zip(scaled, scaled[1:]):
                cells.extend(_bresenham_line(a, b))
        stroke_cells.append(cells)

    frames: list[list[str]] = []
    done: set[tuple[int, int]] = set()

    def make_frame(extra_cells: list[tuple[int, int]] | None = None) -> list[str]:
        active = set(done)
        if extra_cells:
            active.update(extra_cells)
        lines: list[str] = []
        for y in range(rows):
            line_chars = []
            for x in range(cols):
                line_chars.append(stroke_char if (x, y) in active else " ")
            lines.append("".join(line_chars))
        return lines

    for stroke in stroke_cells:
        if not stroke:
            continue
        step = max(1, len(stroke) // 18)
        for idx in range(step, len(stroke) + 1, step):
            frames.append(make_frame(stroke[:idx]))
        if len(stroke) % step != 0:
            frames.append(make_frame(stroke))
        done.update(stroke)

    if done:
        frames.append(make_frame())
    return frames


class StrokeOrderRepository:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or find_strokeorder_root()
        self.kanji_dir = self.root / "kanji" if self.root else None
        self._index: dict[str, Path] | None = None

    @property
    def is_available(self) -> bool:
        return self.kanji_dir is not None and self.kanji_dir.exists()

    def _build_index(self) -> dict[str, Path]:
        if not self.is_available or self.kanji_dir is None:
            return {}
        index: dict[str, Path] = {}
        for path in self.kanji_dir.iterdir():
            if not path.is_file():
                continue
            name = path.name
            if name not in index:
                index[name] = path
            for ch in name:
                index.setdefault(ch, path)
        return index

    def _get_index(self) -> dict[str, Path]:
        if self._index is None:
            self._index = self._build_index()
        return self._index

    def svg_path_for_char(self, ch: str) -> Path | None:
        if not ch:
            return None
        idx = self._get_index()
        return idx.get(ch)

    def has_char(self, ch: str) -> bool:
        return self.svg_path_for_char(ch) is not None

    def load(self, ch: str) -> StrokeOrderData | None:
        path = self.svg_path_for_char(ch)
        if path is None:
            return None
        tree = ET.parse(path)
        root = tree.getroot()
        view_box = root.attrib.get("viewBox", "0 0 109 109").strip()
        vb_parts = view_box.replace(",", " ").split()
        width = 109.0
        height = 109.0
        if len(vb_parts) == 4:
            try:
                width = float(vb_parts[2])
                height = float(vb_parts[3])
            except ValueError:
                width = 109.0
                height = 109.0

        strokes: list[list[tuple[float, float]]] = []
        for elem in root.iter():
            tag = elem.tag
            if tag.endswith("path"):
                d = elem.attrib.get("d", "")
                pts = parse_path_points(d)
                if pts:
                    strokes.append(pts)
        if not strokes:
            return None
        return StrokeOrderData(ch=ch, strokes=strokes, width=width, height=height, source_path=path)


def find_strokeorder_root() -> Path | None:
    env = os.environ.get("KANJITUI_STROKEORDER_DIR", "").strip()
    if env:
        candidate = Path(env).expanduser()
        if (candidate / "kanji").exists():
            return candidate

    cwd = Path.cwd()
    candidates = [
        cwd / "StrokeOrder",
        cwd.parent / "StrokeOrder",
    ]

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / "StrokeOrder")

    for candidate in candidates:
        if (candidate / "kanji").exists():
            return candidate
    return None
