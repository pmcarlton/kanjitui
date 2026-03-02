from pathlib import Path

from kanjitui.providers.kanjidic2 import parse_kanjidic2


def test_parse_kanjidic2_sample() -> None:
    path = Path(__file__).parent / "fixtures" / "kanjidic2.xml"
    parsed = parse_kanjidic2(path)

    han = parsed[0x6F22]
    assert han.jp_grade == 8
    assert han.freq == 432
    assert han.strokes == 13
    assert "カン" in han.jp_on
    assert "China" in han.jp_gloss
