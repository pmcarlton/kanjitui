from kanjitui.tui.radicals import (
    all_kangxi_radical_numbers,
    kangxi_radical_base_char,
    kangxi_radical_cn_name,
    kangxi_radical_english_name,
    kangxi_radical_glyph,
    kangxi_radical_jp_name,
)


def test_kangxi_radicals_cover_full_range() -> None:
    nums = all_kangxi_radical_numbers()
    assert nums[0] == 1
    assert nums[-1] == 214
    assert len(nums) == 214


def test_kangxi_radical_glyph_mapping() -> None:
    assert kangxi_radical_glyph(1) == "⼀"
    assert kangxi_radical_glyph(214) == "⿕"


def test_kangxi_radical_names_and_base_chars() -> None:
    assert kangxi_radical_base_char(1) == "一"
    assert kangxi_radical_base_char(85) == "水"
    assert kangxi_radical_english_name(1) == "One"
    assert kangxi_radical_english_name(85) == "Water"
    assert kangxi_radical_jp_name(9) == "にんべん"
    assert kangxi_radical_jp_name(85) == "さんずい"
    assert kangxi_radical_jp_name(162) == "しんにょう"
    assert kangxi_radical_jp_name(13) == "けいがまえ"
    assert kangxi_radical_cn_name(85) == "三点水"
    assert kangxi_radical_cn_name(162) == "走之底"
