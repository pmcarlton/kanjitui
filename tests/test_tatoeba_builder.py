from pathlib import Path

from kanjitui.providers.tatoeba import BuildSentencesConfig, build_sentences_tsv


def test_build_sentences_tsv_from_small_fixture(tmp_path: Path) -> None:
    fx = Path(__file__).parent / "fixtures" / "tatoeba"
    out_path = tmp_path / "sentences.tsv"

    stats = build_sentences_tsv(
        BuildSentencesConfig(
            jpn_sentences=fx / "jpn_sentences.tsv",
            cmn_sentences=fx / "cmn_sentences.tsv",
            eng_sentences=fx / "eng_sentences.tsv",
            jpn_eng_links=fx / "jpn-eng_links.tsv",
            cmn_eng_links=fx / "cmn-eng_links.tsv",
            out_path=out_path,
            max_per_cp_per_lang=2,
            require_translation=True,
        )
    )

    text = out_path.read_text(encoding="utf-8")
    assert "U+6F22\tjp\t漢字を勉強する。" in text
    assert "U+6C49\tcn\t我在学汉字。" in text
    assert "Tatoeba" in text
    assert stats["rows_total"] > 0
