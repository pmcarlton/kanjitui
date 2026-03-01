from pathlib import Path

from kanjitui.providers.cedict import parse_cedict


def test_parse_cedict_sample() -> None:
    path = Path(__file__).parent / "fixtures" / "cedict_ts.u8"
    entries = parse_cedict(path)

    assert len(entries) == 4
    hanzi = next(e for e in entries if e.trad == "漢字")
    assert hanzi.pinyin_numbered == "han4 zi4"
    assert "Chinese character" in hanzi.glosses[0]
