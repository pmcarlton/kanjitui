from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path


NOTO_CJK_URL = "https://github.com/notofonts/noto-cjk"
BABELSTONE_HAN_URL = "http://www.babelstone.co.uk/Fonts/Han.html"


def detect_tui_runtime_font() -> str | None:
    for key in ("KANJITUI_UI_FONT", "KANJITUI_FONT", "WEZTERM_FONT", "TERM_FONT"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    if _is_wezterm_session():
        detected = _detect_wezterm_font_from_config()
        if detected:
            return detected
    return None


def _is_wezterm_session() -> bool:
    term_program = os.environ.get("TERM_PROGRAM", "").strip().lower()
    if "wezterm" in term_program:
        return True
    if os.environ.get("WEZTERM_PANE"):
        return True
    if os.environ.get("WEZTERM_EXECUTABLE"):
        return True
    return False


def _wezterm_config_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("WEZTERM_CONFIG_FILE", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(Path("~/.wezterm.lua").expanduser())
    candidates.append(Path("~/.config/wezterm/wezterm.lua").expanduser())
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _extract_wezterm_font_candidates(config_text: str) -> list[str]:
    names: list[str] = []

    def _add_name(name: str) -> None:
        value = name.strip()
        if not value:
            return
        if value not in names:
            names.append(value)

    cleaned_text = _strip_lua_comments(config_text)
    for block in re.findall(r"font_with_fallback\s*\{(.*?)\}", cleaned_text, flags=re.DOTALL):
        for match in re.findall(r"['\"]([^'\"]+)['\"]", block):
            _add_name(match)
    for match in re.findall(r"font\(\s*['\"]([^'\"]+)['\"]\s*\)", cleaned_text):
        _add_name(match)
    return names


def _strip_lua_comments(text: str) -> str:
    # Drop simple block comments first.
    no_block = re.sub(r"--\[\[.*?\]\]", "", text, flags=re.DOTALL)
    cleaned_lines: list[str] = []
    for raw_line in no_block.splitlines():
        line_chars: list[str] = []
        in_single = False
        in_double = False
        idx = 0
        while idx < len(raw_line):
            ch = raw_line[idx]
            nxt = raw_line[idx + 1] if idx + 1 < len(raw_line) else ""
            if not in_single and not in_double and ch == "-" and nxt == "-":
                break
            if ch == "'" and not in_double:
                escaped = idx > 0 and raw_line[idx - 1] == "\\"
                if not escaped:
                    in_single = not in_single
            elif ch == '"' and not in_single:
                escaped = idx > 0 and raw_line[idx - 1] == "\\"
                if not escaped:
                    in_double = not in_double
            line_chars.append(ch)
            idx += 1
        cleaned_lines.append("".join(line_chars))
    return "\n".join(cleaned_lines)


def _pick_likely_cjk_font(candidates: list[str]) -> str | None:
    if not candidates:
        return None
    markers = (
        "han",
        "cjk",
        "hiragino",
        "pingfang",
        "song",
        "ming",
        "kai",
        "honoka",
        "hanazono",
        "ipaex",
        "wenquanyi",
        "simsun",
        "fang",
        "noto sans tc",
        "noto sans sc",
        "noto sans cjk",
        "noto serif cjk",
    )
    for candidate in candidates:
        lower = candidate.lower()
        if any(marker in lower for marker in markers):
            return candidate
    return candidates[0]


def _detect_wezterm_font_from_config() -> str | None:
    for path in _wezterm_config_candidates():
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        candidates = _extract_wezterm_font_candidates(text)
        chosen = _pick_likely_cjk_font(candidates)
        if chosen:
            return chosen
    return None


def normalize_font_token(value: str | None) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    return "".join(ch for ch in text if ch.isalnum())


def _strip_style_suffix(token: str) -> str:
    suffixes = (
        "regular",
        "roman",
        "normal",
        "book",
        "medium",
        "bold",
        "italic",
        "oblique",
    )
    value = token
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if value.endswith(suffix) and len(value) > len(suffix) + 3:
                value = value[: -len(suffix)]
                changed = True
    return value


def _normalized_font_identities(label: str) -> set[str]:
    candidates: set[str] = set()
    raw = (label or "").strip()
    if not raw:
        return candidates
    variants = {raw}
    # If a path is provided, include basename/stem-derived identities.
    if "/" in raw or "\\" in raw:
        try:
            path = Path(raw)
            variants.add(path.name)
            variants.add(path.stem)
        except Exception:
            pass
    for value in variants:
        norm = normalize_font_token(value)
        if not norm:
            continue
        candidates.add(norm)
        stripped = _strip_style_suffix(norm)
        if stripped:
            candidates.add(stripped)
    return candidates


def _fonts_equal(runtime_font: str, built_spec: str, built_resolved: str) -> bool:
    runtime_norm = normalize_font_token(runtime_font)
    if not runtime_norm:
        return False
    runtime_ids = _normalized_font_identities(runtime_font)
    if not runtime_ids:
        return False
    db_ids = _normalized_font_identities(built_spec) | _normalized_font_identities(built_resolved)
    if not db_ids:
        return False
    return not runtime_ids.isdisjoint(db_ids)


def font_warning_lines(build_meta: dict[str, str], runtime_font: str | None) -> list[str] | None:
    if not build_meta:
        runtime_label = (runtime_font or "").strip()
        return [
            "Font Coverage Warning",
            "",
            "DB build font metadata is missing (legacy DB build).",
            f"Current UI font: {runtime_label or '(unknown terminal/font env)'}",
            "",
            "Rebuild DB to record build-font metadata and avoid tofu mismatches.",
            "",
            "Actions:",
            "R: rebuild DB against current font (or configured default)",
            "D / Esc: dismiss warning",
            "N: open Noto CJK fonts page",
            "B: open BabelStone Han page",
            "",
            f"Noto CJK: {NOTO_CJK_URL}",
            f"BabelStone Han: {BABELSTONE_HAN_URL}",
        ]

    if build_meta.get("font_filter_enabled", "0") != "1":
        return None

    built_spec = build_meta.get("font_spec", "").strip()
    built_resolved = build_meta.get("font_resolved", "").strip()
    built_label = built_resolved or built_spec or "(unknown)"
    runtime_label = (runtime_font or "").strip()

    if runtime_label and _fonts_equal(runtime_label, built_spec, built_resolved):
        return None

    lines = [
        "Font Coverage Warning",
        "",
        f"DB font filter build: {built_label}",
        f"Current UI font: {runtime_label or '(unknown terminal/font env)'}",
        "",
    ]
    if runtime_label:
        lines.append("Current font appears different from the build font.")
    else:
        lines.append("Current font could not be detected reliably.")
    lines.extend(
        [
            "Some glyphs may appear as tofu or be filtered unexpectedly.",
            "",
            "Actions:",
            "R: rebuild DB against current font (or configured default)",
            "D / Esc: dismiss warning",
            "N: open Noto CJK fonts page",
            "B: open BabelStone Han page",
            "",
            f"Noto CJK: {NOTO_CJK_URL}",
            f"BabelStone Han: {BABELSTONE_HAN_URL}",
        ]
    )
    return lines


def font_warning_allows_persistent_dismiss(
    build_meta: dict[str, str],
    runtime_font: str | None,
) -> bool:
    """Return True only when warning suppression is safe for ambiguous cases."""
    if not build_meta:
        return True
    if build_meta.get("font_filter_enabled", "0") != "1":
        return True
    built_spec = build_meta.get("font_spec", "").strip()
    built_resolved = build_meta.get("font_resolved", "").strip()
    runtime_label = (runtime_font or "").strip()
    if not runtime_label:
        # Unknown runtime font: user may need to suppress noisy warnings.
        return True
    if _fonts_equal(runtime_label, built_spec, built_resolved):
        return True
    # Explicit mismatch should always warn on startup (no persistent suppression).
    return False


def font_warning_flag_key(build_meta: dict[str, str], runtime_font: str | None) -> str:
    stamp = build_meta.get("build_timestamp_utc", "")
    spec = build_meta.get("font_spec", "")
    resolved = build_meta.get("font_resolved", "")
    runtime = runtime_font or ""
    payload = f"{stamp}|{spec}|{resolved}|{runtime}".encode("utf-8")
    digest = hashlib.sha1(payload).hexdigest()[:20]
    return f"font_warning_dismissed_{digest}"


def db_font_label(build_meta: dict[str, str]) -> str:
    if not build_meta:
        return "unknown"
    enabled = build_meta.get("font_filter_enabled", "0")
    if enabled != "1":
        return "unfiltered"
    resolved = build_meta.get("font_resolved", "").strip()
    spec = build_meta.get("font_spec", "").strip()
    return resolved or spec or "unknown"


def startup_status_line(
    *,
    program: str,
    version: str,
    build_meta: dict[str, str],
    runtime_font: str | None,
    total_glyphs: int,
    visible_glyphs: int | None = None,
) -> str:
    db_font = db_font_label(build_meta)
    ui_font = (runtime_font or "").strip() or "unknown"
    glyph_bits = [f"glyphs={total_glyphs}"]
    if visible_glyphs is not None:
        glyph_bits.append(f"visible={visible_glyphs}")
    glyph_text = " ".join(glyph_bits)
    return f"{program} v{version}  db-font={db_font}  ui-font={ui_font}  {glyph_text}"
