from pathlib import Path

from kanjitui.providers.jmdict import parse_jmdict


def test_parse_jmdict_sample() -> None:
    path = Path(__file__).parent / "fixtures" / "jmdict.xml"
    entries = parse_jmdict(path)

    assert len(entries) >= 3
    kanji = next(e for e in entries if "漢字" in e.words)
    assert kanji.common is True
    assert "かんじ" in kanji.readings
    assert kanji.glosses[0] == "Chinese character"
