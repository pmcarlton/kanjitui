from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Variant:
    kind: str
    target_cp: int
    note: str | None = None


@dataclass
class CharAnnotations:
    cp: int
    ch: str
    radical: int | None = None
    strokes: int | None = None
    freq: int | None = None
    jp_on: list[str] = field(default_factory=list)
    jp_kun: list[str] = field(default_factory=list)
    jp_gloss: list[str] = field(default_factory=list)
    cn_pinyin_marked: list[str] = field(default_factory=list)
    cn_pinyin_numbered: list[str] = field(default_factory=list)
    cn_gloss: list[str] = field(default_factory=list)
    variants: list[Variant] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class JpWordEntry:
    word: str
    reading_kana: str | None
    gloss_en: str | None
    common: bool
    reading_count: int
    sense_count: int


@dataclass(frozen=True)
class CnWordEntry:
    trad: str
    simp: str
    pinyin_marked: str
    pinyin_numbered: str
    gloss_en: str
