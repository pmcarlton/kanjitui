from kanjitui.related_nav import build_related_candidates, cn_word_related_cp, jp_word_related_cp


def test_word_related_cp_extracts_non_current_cjk() -> None:
    current = ord("漢")
    assert jp_word_related_cp(current, "漢字", allowed=None) == ord("字")
    assert cn_word_related_cp(current, "漢語", "汉语", allowed=None) == ord("語")


def test_build_related_candidates_respects_order_and_allowed_set() -> None:
    current = ord("漢")
    jp_words = [("漢字", None, None, 1), ("漢方", None, None, 2)]
    cn_words = [("漢語", "汉语", None, None, "", 1)]
    phonetic = [(ord("汗"), "汗", "PHON", None, None)]
    allowed = {ord("字"), ord("汗")}
    out = build_related_candidates(
        current,
        jp_words,
        cn_words,
        phonetic_rows=phonetic,
        allowed=allowed,
    )
    assert out == [ord("字"), ord("汗")]
