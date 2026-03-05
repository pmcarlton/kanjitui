from __future__ import annotations

import hashlib
import os


NOTO_CJK_URL = "https://github.com/notofonts/noto-cjk"
BABELSTONE_HAN_URL = "http://www.babelstone.co.uk/Fonts/Han.html"


def detect_tui_runtime_font() -> str | None:
    for key in ("KANJITUI_UI_FONT", "KANJITUI_FONT", "WEZTERM_FONT", "TERM_FONT"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def normalize_font_token(value: str | None) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    return "".join(ch for ch in text if ch.isalnum())


def _fonts_equal(runtime_font: str, db_font_label_text: str) -> bool:
    runtime_norm = normalize_font_token(runtime_font)
    if not runtime_norm:
        return False
    db_norm = normalize_font_token(db_font_label_text)
    if not db_norm:
        return False
    return runtime_norm == db_norm


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

    # Strict policy: if displayed db-font and ui-font values are unequal, always warn.
    if runtime_label and _fonts_equal(runtime_label, built_label):
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
