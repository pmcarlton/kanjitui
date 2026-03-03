from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable


LOGGER = logging.getLogger(__name__)
FONT_EXTENSIONS = (".ttf", ".otf", ".ttc", ".otc")


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
        for ext in FONT_EXTENSIONS:
            for path in base.rglob(f"*{ext}"):
                if needle in path.stem.lower().replace(" ", ""):
                    yield path


def _iter_font_name_candidates(font_spec: str) -> Iterable[str]:
    base = font_spec.strip()
    if not base:
        return
    emitted: set[str] = set()

    def emit(candidate: str) -> Iterable[str]:
        text = candidate.strip()
        if not text or text in emitted:
            return
        emitted.add(text)
        yield text

    roots = [base]
    collapsed = " ".join(base.split())
    if " mono " in collapsed.lower():
        roots.append(collapsed.replace(" Mono ", " "))

    for root in roots:
        for value in emit(root):
            yield value
        normalized = root.lower()
        if "cjk" not in normalized:
            continue
        if normalized.endswith((" jp", " sc", " tc", " kr", " hk")):
            continue
        for suffix in (" JP", " SC", " TC", " KR", " HK"):
            for value in emit(root + suffix):
                yield value


def compute_font_coverage(font_spec: str) -> set[int] | None:
    font_path = Path(font_spec)
    if not font_path.exists():
        match = None
        for candidate in _iter_font_name_candidates(font_spec):
            match = next(_iter_font_paths(candidate), None)
            if match is not None:
                break
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
    if font_path.suffix.lower() in (".ttc", ".otc"):
        try:
            from fontTools.ttLib import TTCollection  # type: ignore
        except Exception:
            LOGGER.warning("fonttools_unavailable")
            return None
        with TTCollection(font_path) as collection:
            for member in collection.fonts:
                if "cmap" not in member:
                    continue
                for table in member["cmap"].tables:
                    coverage.update(table.cmap.keys())
        return coverage

    with TTFont(font_path) as font:
        if "cmap" not in font:
            return coverage
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
