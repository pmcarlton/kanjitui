from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import sqlite3
import unicodedata

from kanjitui.db.migrations import rebuild_schema
from kanjitui.models import CharAnnotations, CnWordEntry, JpWordEntry
from kanjitui.providers.cedict import CEDICTEntry
from kanjitui.providers.fontcov import compute_font_coverage, save_coverage_json
from kanjitui.providers.jmdict import JMDictEntry
from kanjitui.providers.registry import ProviderRegistry, default_build_registry
from kanjitui.search.normalize import (
    contains_cjk,
    normalize_kana,
    normalize_pinyin_for_search,
    pinyin_marked_to_numbered,
    pinyin_numbered_to_marked,
)


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuildPaths:
    unihan_dir: Path
    kanjidic2_xml: Path
    jmdict_xml: Path
    cedict_txt: Path


@dataclass(frozen=True)
class BuildConfig:
    db_path: Path
    paths: BuildPaths
    font: str | None = None
    font_profile_out: Path | None = None
    build_report_out: Path | None = None
    enabled_providers: tuple[str, ...] = ("unihan", "kanjidic2", "jmdict", "cedict")


def default_build_paths(data_dir: Path) -> BuildPaths:
    unihan_dir = data_dir / "unihan"
    if not unihan_dir.exists():
        unihan_dir = data_dir
    return BuildPaths(
        unihan_dir=unihan_dir,
        kanjidic2_xml=data_dir / "kanjidic2.xml",
        jmdict_xml=data_dir / "jmdict.xml",
        cedict_txt=data_dir / "cedict_ts.u8",
    )


def _score_jmdict(entry: JMDictEntry, word: str) -> int:
    score = 0
    if entry.common:
        score += 100
    if 2 <= len(word) <= 3:
        score += 20
    if len(entry.readings) == 1:
        score += 10
    penalty = max(len(entry.glosses) - 4, 0)
    return score - penalty


def _is_pinyin_well_formed(pinyin: str) -> bool:
    return all(tok and tok[-1] in "12345" for tok in pinyin.split())


def _score_cedict(entry: CEDICTEntry) -> int:
    score = 0
    length = len(entry.trad)
    if 2 <= length <= 3:
        score += 50
    elif length == 1:
        score += 20
    else:
        score += 10
    if _is_pinyin_well_formed(entry.pinyin_numbered):
        score += 30
    if entry.glosses and len(entry.glosses[0]) < 48:
        score += 10
    return score


def _extract_aligned_syllables(word: str, pinyin_numbered: str, target_ch: str) -> list[str]:
    syllables = pinyin_numbered.split()
    if len(word) != len(syllables):
        return []
    out: list[str] = []
    for idx, ch in enumerate(word):
        if ch == target_ch:
            out.append(syllables[idx])
    return out


def _collect_jp_words(entries: list[JMDictEntry]) -> dict[int, list[JpWordEntry]]:
    candidates: dict[int, list[tuple[int, JpWordEntry]]] = defaultdict(list)
    for entry in entries:
        reading = normalize_kana(entry.readings[0]) if entry.readings else None
        gloss = entry.glosses[0] if entry.glosses else None
        for word in entry.words:
            if not contains_cjk(word):
                continue
            score = _score_jmdict(entry, word)
            item = JpWordEntry(
                word=word,
                reading_kana=reading,
                gloss_en=gloss,
                common=entry.common,
                reading_count=len(entry.readings),
                sense_count=len(entry.glosses),
            )
            for ch in set(word):
                if contains_cjk(ch):
                    candidates[ord(ch)].append((score, item))

    out: dict[int, list[JpWordEntry]] = {}
    for cp, bucket in candidates.items():
        ranked = sorted(bucket, key=lambda row: (-row[0], row[1].word, row[1].reading_kana or ""))
        dedup: list[JpWordEntry] = []
        seen: set[tuple[str, str | None]] = set()
        for _, item in ranked:
            key = (item.word, item.reading_kana)
            if key in seen:
                continue
            seen.add(key)
            dedup.append(item)
            if len(dedup) >= 5:
                break
        out[cp] = dedup
    return out


def _collect_cn_words(entries: list[CEDICTEntry]) -> tuple[dict[int, list[CnWordEntry]], dict[int, set[str]]]:
    candidates: dict[int, list[tuple[int, CnWordEntry]]] = defaultdict(list)
    char_to_pinyin_num: dict[int, set[str]] = defaultdict(set)

    for entry in entries:
        gloss = entry.glosses[0] if entry.glosses else ""
        item = CnWordEntry(
            trad=entry.trad,
            simp=entry.simp,
            pinyin_marked=entry.pinyin_marked,
            pinyin_numbered=entry.pinyin_numbered,
            gloss_en=gloss,
        )
        score = _score_cedict(entry)

        chars = set(entry.trad + entry.simp)
        for ch in chars:
            if not contains_cjk(ch):
                continue
            cp = ord(ch)
            candidates[cp].append((score, item))

            for syllable in _extract_aligned_syllables(entry.trad, entry.pinyin_numbered, ch):
                char_to_pinyin_num[cp].add(syllable)
            for syllable in _extract_aligned_syllables(entry.simp, entry.pinyin_numbered, ch):
                char_to_pinyin_num[cp].add(syllable)

    out: dict[int, list[CnWordEntry]] = {}
    for cp, bucket in candidates.items():
        ranked = sorted(bucket, key=lambda row: (-row[0], row[1].trad, row[1].simp))
        dedup: list[CnWordEntry] = []
        seen: set[tuple[str, str]] = set()
        for _, item in ranked:
            key = (item.trad, item.simp)
            if key in seen:
                continue
            seen.add(key)
            dedup.append(item)
            if len(dedup) >= 5:
                break
        out[cp] = dedup

    return out, char_to_pinyin_num


def _nfc(value: str | None) -> str | None:
    if value is None:
        return None
    return unicodedata.normalize("NFC", value)


def _merge_chars(
    unihan: dict[int, CharAnnotations],
    kanjidic: dict[int, CharAnnotations],
    jp_words: dict[int, list[JpWordEntry]],
    cn_words: dict[int, list[CnWordEntry]],
    cn_char_pinyin_num: dict[int, set[str]],
) -> dict[int, CharAnnotations]:
    all_cps = set(unihan) | set(kanjidic) | set(jp_words) | set(cn_words)
    merged: dict[int, CharAnnotations] = {}

    for cp in sorted(all_cps):
        record = CharAnnotations(cp=cp, ch=chr(cp))

        for source_record in (unihan.get(cp), kanjidic.get(cp)):
            if source_record is None:
                continue
            record.radical = record.radical or source_record.radical
            record.strokes = record.strokes or source_record.strokes
            record.freq = record.freq or source_record.freq
            record.jp_on.extend(source_record.jp_on)
            record.jp_kun.extend(source_record.jp_kun)
            record.jp_gloss.extend(source_record.jp_gloss)
            record.cn_pinyin_marked.extend(source_record.cn_pinyin_marked)
            record.cn_gloss.extend(source_record.cn_gloss)
            record.variants.extend(source_record.variants)
            record.sources.update(source_record.sources)

        for pinyin_num in sorted(cn_char_pinyin_num.get(cp, set())):
            record.cn_pinyin_numbered.append(pinyin_num)
        for marked in record.cn_pinyin_marked:
            record.cn_pinyin_numbered.append(pinyin_marked_to_numbered(marked))

        if cp in cn_words and not record.cn_gloss:
            first_gloss = cn_words[cp][0].gloss_en
            if first_gloss:
                record.cn_gloss.append(first_gloss)
                record.sources.add("cedict")

        if cp in jp_words:
            record.sources.add("jmdict")
        if cp in cn_words:
            record.sources.add("cedict")

        record.jp_on = sorted(set(_nfc(x) for x in record.jp_on if x))
        record.jp_kun = sorted(set(_nfc(x) for x in record.jp_kun if x))
        record.jp_gloss = sorted(set(_nfc(x) for x in record.jp_gloss if x))
        record.cn_pinyin_marked = sorted(set(_nfc(x) for x in record.cn_pinyin_marked if x))
        record.cn_pinyin_numbered = sorted(
            set(normalize_pinyin_for_search(x) for x in record.cn_pinyin_numbered if x)
        )
        record.cn_gloss = sorted(set(_nfc(x) for x in record.cn_gloss if x))
        record.variants = sorted(set(record.variants), key=lambda v: (v.kind, v.target_cp))

        merged[cp] = record

    return merged


def _has_annotation(record: CharAnnotations) -> bool:
    return bool(
        record.jp_on
        or record.jp_kun
        or record.jp_gloss
        or record.cn_pinyin_marked
        or record.cn_pinyin_numbered
        or record.cn_gloss
        or record.variants
    )


def _build_search_keys(
    record: CharAnnotations,
    jp_words: list[JpWordEntry],
    cn_words: list[CnWordEntry],
) -> tuple[str, str, str]:
    jp_parts = list(record.jp_on) + list(record.jp_kun)
    jp_parts.extend([w.word for w in jp_words])
    jp_parts.extend([w.reading_kana or "" for w in jp_words])
    jp_parts.extend([normalize_kana(part) for part in jp_parts if part])

    cn_parts = list(record.cn_pinyin_numbered) + list(record.cn_pinyin_marked)
    cn_parts.extend([w.trad for w in cn_words])
    cn_parts.extend([w.simp for w in cn_words])
    cn_parts.extend([w.pinyin_numbered for w in cn_words])

    gloss_parts = list(record.jp_gloss) + list(record.cn_gloss)
    gloss_parts.extend([w.gloss_en or "" for w in jp_words])
    gloss_parts.extend([w.gloss_en for w in cn_words])

    return (
        " ".join(part.lower() for part in jp_parts if part),
        " ".join(part.lower() for part in cn_parts if part),
        " ".join(part.lower() for part in gloss_parts if part),
    )


def build_database(config: BuildConfig, provider_registry: ProviderRegistry | None = None) -> dict[str, int]:
    registry = provider_registry or default_build_registry()
    enabled_providers = registry.resolve_enabled(config.enabled_providers)

    for required in registry.required_paths(enabled_providers, config.paths):
        if not required.exists():
            raise FileNotFoundError(f"Required data missing: {required}")

    loaded = registry.load_selected(enabled_providers, config.paths)
    unihan = loaded.get("unihan", {})
    kanjidic = loaded.get("kanjidic2", {})
    jmdict = loaded.get("jmdict", [])
    cedict = loaded.get("cedict", [])

    jp_words = _collect_jp_words(jmdict)
    cn_words, cn_char_pinyin_num = _collect_cn_words(cedict)

    merged = _merge_chars(unihan, kanjidic, jp_words, cn_words, cn_char_pinyin_num)

    coverage: set[int] | None = None
    if config.font:
        coverage = compute_font_coverage(config.font)
        if coverage and config.font_profile_out:
            save_coverage_json(config.font_profile_out, coverage, font=config.font)

    counts = {
        "candidates": len(merged),
        "included": 0,
        "excluded_no_annotation": 0,
        "excluded_font": 0,
    }

    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    try:
        with conn:
            _ = rebuild_schema(conn)

            for cp, record in sorted(merged.items()):
                if not _has_annotation(record):
                    counts["excluded_no_annotation"] += 1
                    continue
                if coverage is not None and cp not in coverage:
                    counts["excluded_font"] += 1
                    continue

                counts["included"] += 1
                sources = ",".join(sorted(record.sources))

                conn.execute(
                    "INSERT INTO chars(cp, ch, radical, strokes, freq, sources) VALUES(?,?,?,?,?,?)",
                    (cp, record.ch, record.radical, record.strokes, record.freq, sources),
                )

                for idx, reading in enumerate(record.jp_on, start=1):
                    conn.execute(
                        "INSERT INTO jp_readings(cp, type, reading, rank) VALUES(?,?,?,?)",
                        (cp, "on", reading, idx),
                    )
                for idx, reading in enumerate(record.jp_kun, start=1):
                    conn.execute(
                        "INSERT INTO jp_readings(cp, type, reading, rank) VALUES(?,?,?,?)",
                        (cp, "kun", reading, idx),
                    )

                for gloss in record.jp_gloss:
                    conn.execute("INSERT INTO jp_gloss(cp, gloss) VALUES(?,?)", (cp, gloss))

                for idx, num in enumerate(record.cn_pinyin_numbered, start=1):
                    marked = pinyin_numbered_to_marked(num)
                    conn.execute(
                        "INSERT INTO cn_readings(cp, pinyin_marked, pinyin_numbered, rank) VALUES(?,?,?,?)",
                        (cp, marked, num, idx),
                    )

                for gloss in record.cn_gloss:
                    conn.execute("INSERT INTO cn_gloss(cp, gloss) VALUES(?,?)", (cp, gloss))

                for var in record.variants:
                    conn.execute(
                        "INSERT INTO variants(cp, kind, target_cp, note) VALUES(?,?,?,?)",
                        (cp, var.kind, var.target_cp, var.note),
                    )

                record_jp_words = jp_words.get(cp, [])[:5]
                for rank, word in enumerate(record_jp_words, start=1):
                    conn.execute(
                        "INSERT INTO jp_words(cp, word, reading_kana, gloss_en, rank) VALUES(?,?,?,?,?)",
                        (
                            cp,
                            word.word,
                            normalize_kana(word.reading_kana) if word.reading_kana else None,
                            word.gloss_en,
                            rank,
                        ),
                    )

                record_cn_words = cn_words.get(cp, [])[:5]
                for rank, word in enumerate(record_cn_words, start=1):
                    conn.execute(
                        "INSERT INTO cn_words(cp, trad, simp, pinyin_marked, pinyin_numbered, gloss_en, rank) VALUES(?,?,?,?,?,?,?)",
                        (
                            cp,
                            word.trad,
                            word.simp,
                            word.pinyin_marked,
                            word.pinyin_numbered,
                            word.gloss_en,
                            rank,
                        ),
                    )

                jp_keys, cn_keys, gloss_keys = _build_search_keys(record, record_jp_words, record_cn_words)
                conn.execute(
                    "INSERT INTO search_index(cp, jp_keys, cn_keys, gloss_keys) VALUES(?,?,?,?)",
                    (cp, jp_keys, cn_keys, gloss_keys),
                )

    finally:
        conn.close()

    LOGGER.info("db_build_complete", extra=counts)

    if config.build_report_out:
        config.build_report_out.parent.mkdir(parents=True, exist_ok=True)
        config.build_report_out.write_text(json.dumps(counts, indent=2), encoding="utf-8")

    return counts
