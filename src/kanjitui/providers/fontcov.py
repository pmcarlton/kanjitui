from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable


LOGGER = logging.getLogger(__name__)


def _iter_font_paths(font_name: str) -> Iterable[Path]:
    candidates = [
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
        Path.home() / "Library/Fonts",
        Path("/usr/share/fonts"),
        Path.home() / ".local/share/fonts",
    ]
    needle = font_name.lower().replace(" ", "")
    for base in candidates:
        if not base.exists():
            continue
        for path in base.rglob("*.ttf"):
            if needle in path.stem.lower().replace(" ", ""):
                yield path
        for path in base.rglob("*.otf"):
            if needle in path.stem.lower().replace(" ", ""):
                yield path


def compute_font_coverage(font_spec: str) -> set[int] | None:
    font_path = Path(font_spec)
    if not font_path.exists():
        match = next(_iter_font_paths(font_spec), None)
        if match is None:
            LOGGER.warning("font_not_found", extra={"font": font_spec})
            return None
        font_path = match

    try:
        from fontTools.ttLib import TTFont  # type: ignore
    except Exception:
        LOGGER.warning("fonttools_unavailable")
        return None

    coverage: set[int] = set()
    with TTFont(font_path) as font:
        for table in font["cmap"].tables:
            coverage.update(table.cmap.keys())
    return coverage


def load_coverage_json(path: Path) -> set[int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cps = payload.get("codepoints", [])
    return {int(cp) for cp in cps}


def save_coverage_json(path: Path, codepoints: set[int], font: str) -> None:
    payload = {
        "font": font,
        "count": len(codepoints),
        "codepoints": sorted(codepoints),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
