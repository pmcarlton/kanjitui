from kanjitui.search import normalize


def test_kana_to_romaji_hiragana_basic() -> None:
    assert normalize.kana_to_romaji("かんじ") == "kanji"
    assert normalize.kana_to_romaji("しゅう") == "shuu"


def test_kana_to_romaji_handles_sokuon_and_long_mark() -> None:
    assert normalize.kana_to_romaji("がっこう") == "gakkou"
    assert normalize.kana_to_romaji("スーパー") == "suupaa"
