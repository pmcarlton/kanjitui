from __future__ import annotations

from kanjitui.font_warning import (
    font_warning_flag_key,
    font_warning_lines,
)


def test_font_warning_lines_hidden_when_not_font_filtered() -> None:
    meta = {
        "font_filter_enabled": "0",
        "font_spec": "",
        "font_resolved": "",
        "build_timestamp_utc": "2026-01-01T00:00:00+00:00",
    }
    assert font_warning_lines(meta, runtime_font="Noto Sans CJK JP") is None


def test_font_warning_lines_hidden_when_fonts_match() -> None:
    meta = {
        "font_filter_enabled": "1",
        "font_spec": "Noto Sans CJK JP",
        "font_resolved": "/Library/Fonts/NotoSansCJKjp-Regular.otf",
        "build_timestamp_utc": "2026-01-01T00:00:00+00:00",
    }
    assert font_warning_lines(meta, runtime_font="Noto Sans CJK JP") is None


def test_font_warning_lines_present_when_mismatch() -> None:
    meta = {
        "font_filter_enabled": "1",
        "font_spec": "BabelStone Han",
        "font_resolved": "/Users/me/Fonts/BabelStoneHan.ttf",
        "build_timestamp_utc": "2026-01-01T00:00:00+00:00",
    }
    lines = font_warning_lines(meta, runtime_font="Noto Sans CJK JP")
    assert lines is not None
    assert any("Font Coverage Warning" in line for line in lines)
    assert any("Noto CJK" in line for line in lines)
    assert any("BabelStone Han" in line for line in lines)


def test_font_warning_flag_key_changes_with_runtime_font() -> None:
    meta = {
        "font_filter_enabled": "1",
        "font_spec": "BabelStone Han",
        "font_resolved": "/Users/me/Fonts/BabelStoneHan.ttf",
        "build_timestamp_utc": "2026-01-01T00:00:00+00:00",
    }
    key_a = font_warning_flag_key(meta, runtime_font="Noto Sans CJK JP")
    key_b = font_warning_flag_key(meta, runtime_font="BabelStone Han")
    assert key_a != key_b
