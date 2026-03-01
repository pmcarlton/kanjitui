from __future__ import annotations

import re
from pathlib import Path

from kanjitui.models import CharAnnotations, Variant
from kanjitui.search.normalize import contains_cjk


UNI_LINE_RE = re.compile(r"^U\+([0-9A-F]{4,6})\t([^\t]+)\t(.+)$")
CP_RE = re.compile(r"U\+([0-9A-F]{4,6})")

VARIANT_FIELDS = {
    "kTraditionalVariant": "traditional",
    "kSimplifiedVariant": "simplified",
    "kZVariant": "zvariant",
    "kCompatibilityVariant": "compat",
    "kSemanticVariant": "semantic",
    "kSpecializedSemanticVariant": "specialized",
}


def _split_values(raw: str) -> list[str]:
    return [tok for tok in raw.replace(",", " ").split() if tok]


def _parse_radical(raw: str) -> int | None:
    token = raw.split()[0]
    m = re.match(r"(\d+)", token)
    if not m:
        return None
    return int(m.group(1))


def _parse_strokes(raw: str) -> int | None:
    for token in raw.split():
        if token.isdigit():
            return int(token)
    return None


def parse_unihan_dir(unihan_dir: Path) -> dict[int, CharAnnotations]:
    data: dict[int, CharAnnotations] = {}
    txt_files = sorted(unihan_dir.glob("Unihan*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"No Unihan*.txt files found in {unihan_dir}")

    for path in txt_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            m = UNI_LINE_RE.match(line)
            if not m:
                continue

            cp = int(m.group(1), 16)
            field = m.group(2)
            raw = m.group(3).strip()

            record = data.setdefault(cp, CharAnnotations(cp=cp, ch=chr(cp)))
            record.sources.add("unihan")

            if field == "kJapaneseOn":
                record.jp_on.extend(_split_values(raw))
            elif field == "kJapaneseKun":
                record.jp_kun.extend(_split_values(raw))
            elif field == "kMandarin":
                record.cn_pinyin_marked.extend(_split_values(raw))
            elif field == "kDefinition":
                record.jp_gloss.append(raw)
                record.cn_gloss.append(raw)
            elif field == "kRSUnicode":
                radical = _parse_radical(raw)
                if radical is not None:
                    record.radical = record.radical or radical
            elif field == "kTotalStrokes":
                strokes = _parse_strokes(raw)
                if strokes is not None:
                    record.strokes = record.strokes or strokes
            elif field in VARIANT_FIELDS:
                kind = VARIANT_FIELDS[field]
                for cp_match in CP_RE.finditer(raw):
                    target_cp = int(cp_match.group(1), 16)
                    record.variants.append(Variant(kind=kind, target_cp=target_cp, note=None))
            elif field == "kIDS":
                for ch in raw:
                    if contains_cjk(ch):
                        record.components.append(ord(ch))
            elif field == "kPhonetic":
                for cp_match in CP_RE.finditer(raw):
                    record.phonetics.append(int(cp_match.group(1), 16))
                for ch in raw:
                    if contains_cjk(ch):
                        record.phonetics.append(ord(ch))

    for record in data.values():
        record.jp_on = sorted(set(record.jp_on))
        record.jp_kun = sorted(set(record.jp_kun))
        record.cn_pinyin_marked = sorted(set(record.cn_pinyin_marked))
        record.jp_gloss = sorted(set(record.jp_gloss))
        record.cn_gloss = sorted(set(record.cn_gloss))
        record.components = sorted(set(record.components))
        record.phonetics = sorted(set(record.phonetics))
        record.variants = sorted(set(record.variants), key=lambda v: (v.kind, v.target_cp))

    return data
