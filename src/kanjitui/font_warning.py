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


def _fonts_match(runtime_font: str, built_spec: str, built_resolved: str) -> bool:
    runtime_norm = normalize_font_token(runtime_font)
    if not runtime_norm:
        return False
    for candidate in (built_spec, built_resolved):
        cand_norm = normalize_font_token(candidate)
        if not cand_norm:
            continue
        if runtime_norm in cand_norm or cand_norm in runtime_norm:
            return True
    return False


def font_warning_lines(build_meta: dict[str, str], runtime_font: str | None) -> list[str] | None:
    if build_meta.get("font_filter_enabled", "0") != "1":
        return None

    built_spec = build_meta.get("font_spec", "").strip()
    built_resolved = build_meta.get("font_resolved", "").strip()
    built_label = built_resolved or built_spec or "(unknown)"
    runtime_label = (runtime_font or "").strip()

    if runtime_label and _fonts_match(runtime_label, built_spec, built_resolved):
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
