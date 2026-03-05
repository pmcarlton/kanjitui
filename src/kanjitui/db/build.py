from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
import unicodedata
from typing import Callable

from kanjitui.db.migrations import rebuild_schema
from kanjitui.models import CharAnnotations, CnWordEntry, JpWordEntry
from kanjitui.providers.cedict import CEDICTEntry
from kanjitui.providers.fontcov import compute_font_coverage_with_path, save_coverage_json
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
    sentences_tsv: Path | None = None


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
        sentences_tsv=data_dir / "sentences.tsv",
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


def _collect_cn_words(
    entries: list[CEDICTEntry],
) -> tuple[dict[int, list[CnWordEntry]], dict[int, set[str]], dict[int, int]]:
    candidates: dict[int, list[tuple[int, CnWordEntry]]] = defaultdict(list)
    char_to_pinyin_num: dict[int, set[str]] = defaultdict(set)
    char_occurrence_count: dict[int, int] = defaultdict(int)

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
            char_occurrence_count[cp] += 1

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

    return out, char_to_pinyin_num, dict(char_occurrence_count)


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
            record.jp_grade = record.jp_grade or source_record.jp_grade
            record.jp_on.extend(source_record.jp_on)
            record.jp_kun.extend(source_record.jp_kun)
            record.jp_gloss.extend(source_record.jp_gloss)
            record.cn_pinyin_marked.extend(source_record.cn_pinyin_marked)
            record.cn_gloss.extend(source_record.cn_gloss)
            record.components.extend(source_record.components)
            record.phonetics.extend(source_record.phonetics)
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
        record.components = sorted(set(record.components))
        record.phonetics = sorted(set(record.phonetics))
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
        or record.components
        or record.phonetics
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


def build_database(
    config: BuildConfig,
    provider_registry: ProviderRegistry | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
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
    sentences = loaded.get("sentences", [])

    jp_words = _collect_jp_words(jmdict)
    cn_words, cn_char_pinyin_num, cn_occurrence = _collect_cn_words(cedict)
    sentences_by_cp: dict[int, list] = defaultdict(list)
    for entry in sentences:
        sentences_by_cp[entry.cp].append(entry)
    for cp in list(sentences_by_cp.keys()):
        sentences_by_cp[cp] = sorted(
            sentences_by_cp[cp], key=lambda row: (row.lang, row.text, row.reading, row.gloss)
        )[:6]

    merged = _merge_chars(unihan, kanjidic, jp_words, cn_words, cn_char_pinyin_num)

    coverage: set[int] | None = None
    resolved_font_path: Path | None = None
    if config.font:
        coverage, resolved_font_path, coverage_error = compute_font_coverage_with_path(config.font)
        if coverage is None:
            if coverage_error == "fonttools_unavailable":
                raise RuntimeError(
                    "Font coverage extraction requires 'fonttools'. "
                    "Install it with: pip install fonttools"
                )
            raise FileNotFoundError(
                f"Font coverage unavailable for '{config.font}'. "
                "Install the font (or pass a valid font path) before enabling font filter."
            )
        if progress is not None:
            resolved = str(resolved_font_path) if resolved_font_path is not None else config.font
            progress(f"Font coverage ready: {len(coverage)} codepoints ({resolved})")
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
            jp_freq_candidates: list[tuple[int, int]] = []
            cn_freq_candidates: list[tuple[int, int]] = []

            total_merged = len(merged)
            processed = 0
            for cp, record in sorted(merged.items()):
                processed += 1
                if progress is not None and (processed == 1 or processed % 2000 == 0 or processed == total_merged):
                    progress(
                        f"DB build progress: {processed}/{total_merged} "
                        f"included={counts['included']} "
                        f"excluded_no_annotation={counts['excluded_no_annotation']} "
                        f"excluded_font={counts['excluded_font']}"
                    )
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
                unihan_record = unihan.get(cp)
                kanjidic_record = kanjidic.get(cp)
                unihan_cn_num = {
                    normalize_pinyin_for_search(pinyin_marked_to_numbered(value))
                    for value in (unihan_record.cn_pinyin_marked if unihan_record else [])
                }
                cedict_cn_num = {
                    normalize_pinyin_for_search(value) for value in cn_char_pinyin_num.get(cp, set())
                }
                provenance_seen: set[tuple[str, str, str]] = set()

                def add_provenance(field: str, value: str, source: str, confidence: float) -> None:
                    key = (field, value, source)
                    if key in provenance_seen:
                        return
                    provenance_seen.add(key)
                    conn.execute(
                        "INSERT INTO field_provenance(cp, field, value, source, confidence) VALUES(?,?,?,?,?)",
                        (cp, field, value, source, confidence),
                    )

                if record.radical is not None:
                    if unihan_record and unihan_record.radical == record.radical:
                        add_provenance("radical", str(record.radical), "unihan", 0.85)
                    if kanjidic_record and kanjidic_record.radical == record.radical:
                        add_provenance("radical", str(record.radical), "kanjidic2", 0.95)
                if record.strokes is not None:
                    if unihan_record and unihan_record.strokes == record.strokes:
                        add_provenance("strokes", str(record.strokes), "unihan", 0.85)
                    if kanjidic_record and kanjidic_record.strokes == record.strokes:
                        add_provenance("strokes", str(record.strokes), "kanjidic2", 0.95)

                if record.freq is not None:
                    jp_freq_candidates.append((cp, record.freq))
                if record.jp_grade is not None:
                    add_provenance("jp_grade", str(record.jp_grade), "kanjidic2", 0.99)
                    if record.jp_grade in {1, 2, 3, 4, 5, 6}:
                        add_provenance("jp_class", "kyoiku", "kanjidic2", 0.99)
                        add_provenance("jp_class", "joyo", "kanjidic2", 0.99)
                    elif record.jp_grade == 8:
                        add_provenance("jp_class", "joyo", "kanjidic2", 0.99)
                    elif record.jp_grade in {9, 10}:
                        add_provenance("jp_class", "jinmeiyo", "kanjidic2", 0.99)
                cn_count = cn_occurrence.get(cp, 0)
                if cn_count > 0:
                    cn_freq_candidates.append((cp, cn_count))

                for idx, reading in enumerate(record.jp_on, start=1):
                    conn.execute(
                        "INSERT INTO jp_readings(cp, type, reading, rank) VALUES(?,?,?,?)",
                        (cp, "on", reading, idx),
                    )
                    if unihan_record and reading in unihan_record.jp_on:
                        add_provenance("jp_on", reading, "unihan", 0.80)
                    if kanjidic_record and reading in kanjidic_record.jp_on:
                        add_provenance("jp_on", reading, "kanjidic2", 0.95)
                for idx, reading in enumerate(record.jp_kun, start=1):
                    conn.execute(
                        "INSERT INTO jp_readings(cp, type, reading, rank) VALUES(?,?,?,?)",
                        (cp, "kun", reading, idx),
                    )
                    if unihan_record and reading in unihan_record.jp_kun:
                        add_provenance("jp_kun", reading, "unihan", 0.80)
                    if kanjidic_record and reading in kanjidic_record.jp_kun:
                        add_provenance("jp_kun", reading, "kanjidic2", 0.95)

                for gloss in record.jp_gloss:
                    conn.execute("INSERT INTO jp_gloss(cp, gloss) VALUES(?,?)", (cp, gloss))
                    if unihan_record and gloss in unihan_record.jp_gloss:
                        add_provenance("jp_gloss", gloss, "unihan", 0.75)
                    if kanjidic_record and gloss in kanjidic_record.jp_gloss:
                        add_provenance("jp_gloss", gloss, "kanjidic2", 0.95)

                for idx, num in enumerate(record.cn_pinyin_numbered, start=1):
                    marked = pinyin_numbered_to_marked(num)
                    conn.execute(
                        "INSERT INTO cn_readings(cp, pinyin_marked, pinyin_numbered, rank) VALUES(?,?,?,?)",
                        (cp, marked, num, idx),
                    )
                    if num in unihan_cn_num:
                        add_provenance("cn_reading", num, "unihan", 0.80)
                    if num in cedict_cn_num:
                        add_provenance("cn_reading", num, "cedict", 0.75)

                for gloss in record.cn_gloss:
                    conn.execute("INSERT INTO cn_gloss(cp, gloss) VALUES(?,?)", (cp, gloss))
                    if unihan_record and gloss in unihan_record.cn_gloss:
                        add_provenance("cn_gloss", gloss, "unihan", 0.75)
                    if cp in cn_words:
                        add_provenance("cn_gloss", gloss, "cedict", 0.70)

                for var in record.variants:
                    conn.execute(
                        "INSERT INTO variants(cp, kind, target_cp, note) VALUES(?,?,?,?)",
                        (cp, var.kind, var.target_cp, var.note),
                    )
                    add_provenance("variant", f"{var.kind}:U+{var.target_cp:04X}", "unihan", 0.90)

                for component_cp in record.components:
                    conn.execute(
                        "INSERT INTO components(cp, component_cp, kind, source) VALUES(?,?,?,?)",
                        (cp, component_cp, "ids", "unihan"),
                    )
                    add_provenance("component", f"U+{component_cp:04X}", "unihan", 0.70)
                if not record.components and record.radical is not None and 1 <= record.radical <= 214:
                    radical_cp = 0x2F00 + record.radical - 1
                    conn.execute(
                        "INSERT INTO components(cp, component_cp, kind, source) VALUES(?,?,?,?)",
                        (cp, radical_cp, "radical", "unihan"),
                    )
                    add_provenance("component", f"U+{radical_cp:04X}", "unihan", 0.65)

                for phonetic_cp in record.phonetics:
                    if phonetic_cp >= 0x3400:
                        series_key = f"U+{phonetic_cp:04X}"
                    else:
                        series_key = f"PHON:{phonetic_cp}"
                    conn.execute(
                        "INSERT INTO phonetic_series(series_key, cp, source) VALUES(?,?,?)",
                        (series_key, cp, "unihan"),
                    )
                    add_provenance("phonetic", series_key, "unihan", 0.70)

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
                    add_provenance("jp_word", word.word, "jmdict", 0.95)

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
                    add_provenance("cn_word", f"{word.trad}/{word.simp}", "cedict", 0.95)

                sentence_rows = sentences_by_cp.get(cp, [])
                sentence_rank = 1
                for sentence in sentence_rows:
                    conn.execute(
                        "INSERT INTO sentences(cp, lang, text, reading, gloss, source, license, rank) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            cp,
                            sentence.lang,
                            sentence.text,
                            sentence.reading,
                            sentence.gloss,
                            sentence.source,
                            sentence.license,
                            sentence_rank,
                        ),
                    )
                    add_provenance("sentence", sentence.text, "sentences", 0.90)
                    sentence_rank += 1

                jp_keys, cn_keys, gloss_keys = _build_search_keys(record, record_jp_words, record_cn_words)
                conn.execute(
                    "INSERT INTO search_index(cp, jp_keys, cn_keys, gloss_keys) VALUES(?,?,?,?)",
                    (cp, jp_keys, cn_keys, gloss_keys),
                )

            jp_ranked = sorted(jp_freq_candidates, key=lambda row: (row[1], row[0]))
            for rank, (cp, freq) in enumerate(jp_ranked, start=1):
                conn.execute(
                    "INSERT INTO frequency_scores(cp, profile, score, rank) VALUES(?,?,?,?)",
                    (cp, "jp_kanjidic", float(freq), rank),
                )

            cn_ranked = sorted(cn_freq_candidates, key=lambda row: (-row[1], row[0]))
            for rank, (cp, count) in enumerate(cn_ranked, start=1):
                conn.execute(
                    "INSERT INTO frequency_scores(cp, profile, score, rank) VALUES(?,?,?,?)",
                    (cp, "cn_cedict", float(count), rank),
                )

            build_meta = {
                "font_filter_enabled": "1" if config.font else "0",
                "font_spec": str(config.font or ""),
                "font_resolved": str(resolved_font_path) if resolved_font_path is not None else "",
                "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            for key, value in build_meta.items():
                conn.execute(
                    """
                    INSERT INTO build_meta(key, value, updated_at)
                    VALUES(?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (key, value),
                )

    finally:
        conn.close()

    LOGGER.info("db_build_complete", extra=counts)

    if config.build_report_out:
        config.build_report_out.parent.mkdir(parents=True, exist_ok=True)
        config.build_report_out.write_text(json.dumps(counts, indent=2), encoding="utf-8")

    return counts
