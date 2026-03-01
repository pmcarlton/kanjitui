from pathlib import Path

from kanjitui.providers.sentences import parse_sentences_tsv


def test_parse_sentences_tsv() -> None:
    path = Path(__file__).parent / "fixtures" / "sentences.tsv"
    rows = parse_sentences_tsv(path)

    assert len(rows) == 3
    assert rows[0].cp == 0x6F22
    assert rows[0].lang == "jp"
    assert "kanji" in rows[0].gloss.lower()
