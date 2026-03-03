from __future__ import annotations

from typing import Iterable, Sequence

from kanjitui.search.normalize import contains_cjk


def _ordered_unique_cps_from_texts(texts: Iterable[str], current_cp: int) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for text in texts:
        for ch in text:
            if not contains_cjk(ch):
                continue
            cp = ord(ch)
            if cp == current_cp or cp in seen:
                continue
            seen.add(cp)
            out.append(cp)
    return out


def _first_allowed(candidates: Sequence[int], allowed: set[int] | None) -> int | None:
    if not candidates:
        return None
    if allowed is None:
        return candidates[0]
    for cp in candidates:
        if cp in allowed:
            return cp
    return None


def jp_word_related_cp(current_cp: int, word: str, allowed: set[int] | None = None) -> int | None:
    candidates = _ordered_unique_cps_from_texts([word], current_cp=current_cp)
    return _first_allowed(candidates, allowed)


def cn_word_related_cp(
    current_cp: int,
    trad: str,
    simp: str,
    allowed: set[int] | None = None,
) -> int | None:
    candidates = _ordered_unique_cps_from_texts([trad, simp], current_cp=current_cp)
    return _first_allowed(candidates, allowed)


def build_related_candidates(
    current_cp: int,
    jp_words: Sequence[tuple[str, str | None, str | None, int]],
    cn_words: Sequence[tuple[str, str, str | None, str | None, str, int]],
    phonetic_rows: Sequence[tuple[int, str, str, str | None, str | None]] | None = None,
    allowed: set[int] | None = None,
) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()

    def add(cp: int | None) -> None:
        if cp is None or cp == current_cp or cp in seen:
            return
        if allowed is not None and cp not in allowed:
            return
        seen.add(cp)
        out.append(cp)

    for word, _kana, _gloss, _rank in jp_words:
        add(jp_word_related_cp(current_cp, word, allowed=allowed))

    for trad, simp, _marked, _numbered, _gloss, _rank in cn_words:
        add(cn_word_related_cp(current_cp, trad, simp, allowed=allowed))

    for member_cp, _member_ch, _key, _pinyin_marked, _pinyin_numbered in phonetic_rows or []:
        add(member_cp)

    return out
