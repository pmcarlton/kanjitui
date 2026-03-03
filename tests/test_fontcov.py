from kanjitui.providers.fontcov import _iter_font_name_candidates


def test_font_name_candidates_include_cjk_region_and_non_mono_fallback() -> None:
    candidates = list(_iter_font_name_candidates("Noto Sans Mono CJK"))
    assert "Noto Sans Mono CJK" in candidates
    assert "Noto Sans CJK" in candidates
    assert "Noto Sans Mono CJK JP" in candidates
    assert "Noto Sans CJK JP" in candidates
