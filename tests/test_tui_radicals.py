from kanjitui.tui.radicals import all_kangxi_radical_numbers, kangxi_radical_glyph


def test_kangxi_radicals_cover_full_range() -> None:
    nums = all_kangxi_radical_numbers()
    assert nums[0] == 1
    assert nums[-1] == 214
    assert len(nums) == 214


def test_kangxi_radical_glyph_mapping() -> None:
    assert kangxi_radical_glyph(1) == "⼀"
    assert kangxi_radical_glyph(214) == "⿕"
