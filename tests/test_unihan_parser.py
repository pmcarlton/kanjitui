from pathlib import Path

from kanjitui.providers.unihan import parse_unihan_dir


def test_parse_unihan_sample() -> None:
    root = Path(__file__).parent / "fixtures" / "unihan"
    parsed = parse_unihan_dir(root)

    han = parsed[0x6F22]
    assert han.radical == 85
    assert han.strokes == 13
    assert "カン" in han.jp_on
    assert "han4" in han.cn_pinyin_marked

    hans = parsed[0x6C49]
    assert any(v.target_cp == 0x6F22 for v in hans.variants)
