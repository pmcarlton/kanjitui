from __future__ import annotations

from dataclasses import dataclass
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


def _filter_allowed(candidates: Sequence[int], allowed: set[int] | None) -> list[int]:
    if allowed is None:
        return list(candidates)
    return [cp for cp in candidates if cp in allowed]


def jp_word_related_cps(current_cp: int, word: str, allowed: set[int] | None = None) -> list[int]:
    candidates = _ordered_unique_cps_from_texts([word], current_cp=current_cp)
    return _filter_allowed(candidates, allowed)


def jp_word_related_cp(current_cp: int, word: str, allowed: set[int] | None = None) -> int | None:
    candidates = jp_word_related_cps(current_cp, word, allowed=allowed)
    return _first_allowed(candidates, allowed)


def cn_word_related_cps(
    current_cp: int,
    trad: str,
    simp: str,
    allowed: set[int] | None = None,
) -> list[int]:
    candidates = _ordered_unique_cps_from_texts([trad, simp], current_cp=current_cp)
    return _filter_allowed(candidates, allowed)


def cn_word_related_cp(
    current_cp: int,
    trad: str,
    simp: str,
    allowed: set[int] | None = None,
) -> int | None:
    candidates = cn_word_related_cps(current_cp, trad, simp, allowed=allowed)
    return _first_allowed(candidates, allowed)


def build_related_rows(
    current_cp: int,
    jp_words: Sequence[tuple[str, str | None, str | None, int]],
    cn_words: Sequence[tuple[str, str, str | None, str | None, str, int]],
    phonetic_rows: Sequence[tuple[int, str, str, str | None, str | None]] | None = None,
    allowed: set[int] | None = None,
) -> list[list[int]]:
    layout = build_related_rows_layout(
        current_cp=current_cp,
        jp_words=jp_words,
        cn_words=cn_words,
        allowed=allowed,
    )
    rows = [list(row) for row in layout.rows]
    seen: set[int] = {cp for row in rows for cp in row}
    for member_cp, _member_ch, _key, _pinyin_marked, _pinyin_numbered in phonetic_rows or []:
        row = [member_cp]
        row = [cp for cp in row if cp != current_cp]
        if allowed is not None:
            row = [cp for cp in row if cp in allowed]
        row = [cp for cp in row if cp not in seen]
        if not row:
            continue
        seen.update(row)
        rows.append(row)
    return rows


@dataclass(frozen=True)
class RelatedRowsLayout:
    rows: list[list[int]]
    jp_row_indexes: list[int | None]
    cn_row_indexes: list[int | None]


def build_related_rows_layout(
    current_cp: int,
    jp_words: Sequence[tuple[str, str | None, str | None, int]],
    cn_words: Sequence[tuple[str, str, str | None, str | None, str, int]],
    allowed: set[int] | None = None,
) -> RelatedRowsLayout:
    rows: list[list[int]] = []
    seen: set[int] = set()
    jp_row_indexes: list[int | None] = []
    cn_row_indexes: list[int | None] = []

    def add_row(values: list[int]) -> int | None:
        row = [cp for cp in values if cp != current_cp]
        if allowed is not None:
            row = [cp for cp in row if cp in allowed]
        # Global uniquify while preserving first appearance order by row then column.
        row = [cp for cp in row if cp not in seen]
        if not row:
            return None
        seen.update(row)
        rows.append(row)
        return len(rows) - 1

    for word, _kana, _gloss, _rank in jp_words:
        jp_row_indexes.append(add_row(jp_word_related_cps(current_cp, word, allowed=allowed)))

    for trad, simp, _marked, _numbered, _gloss, _rank in cn_words:
        cn_row_indexes.append(add_row(cn_word_related_cps(current_cp, trad, simp, allowed=allowed)))

    return RelatedRowsLayout(
        rows=rows,
        jp_row_indexes=jp_row_indexes,
        cn_row_indexes=cn_row_indexes,
    )



def build_related_candidates(
    current_cp: int,
    jp_words: Sequence[tuple[str, str | None, str | None, int]],
    cn_words: Sequence[tuple[str, str, str | None, str | None, str, int]],
    phonetic_rows: Sequence[tuple[int, str, str, str | None, str | None]] | None = None,
    allowed: set[int] | None = None,
) -> list[int]:
    rows = build_related_rows(
        current_cp,
        jp_words,
        cn_words,
        phonetic_rows=phonetic_rows,
        allowed=allowed,
    )
    out: list[int] = []
    for row in rows:
        out.extend(row)
    return out
