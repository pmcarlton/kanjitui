from __future__ import annotations

import bz2
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import urllib.request


def _open_text(path: Path):
    if path.suffix == ".bz2":
        return bz2.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def _is_han(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x3400 <= cp <= 0x4DBF
        or 0x4E00 <= cp <= 0x9FFF
        or 0xF900 <= cp <= 0xFAFF
        or 0x20000 <= cp <= 0x2EBEF
    )


def _ordered_unique_han(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for ch in text:
        if ch in seen:
            continue
        if _is_han(ch):
            seen.add(ch)
            out.append(ch)
    return out


def download_if_missing(url: str, dest: Path, force: bool = False) -> Path:
    if dest.exists() and not force:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as resp, dest.open("wb") as out:
        out.write(resp.read())
    return dest


def parse_links(path: Path) -> dict[int, int]:
    mapping: dict[int, int] = {}
    with _open_text(path) as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            try:
                src_id = int(parts[0])
                eng_id = int(parts[1])
            except ValueError:
                continue
            mapping.setdefault(src_id, eng_id)
    return mapping


def parse_english_sentences(path: Path, needed_ids: set[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    if not needed_ids:
        return out

    with _open_text(path) as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t", 2)
            if len(parts) < 3:
                continue
            try:
                sent_id = int(parts[0])
            except ValueError:
                continue
            if sent_id not in needed_ids:
                continue
            out[sent_id] = parts[2].strip()
    return out


@dataclass(frozen=True)
class BuildSentencesConfig:
    jpn_sentences: Path
    cmn_sentences: Path
    eng_sentences: Path
    jpn_eng_links: Path
    cmn_eng_links: Path
    out_path: Path
    max_per_cp_per_lang: int = 3
    require_translation: bool = False


def _write_rows(
    *,
    lang: str,
    sentence_path: Path,
    links: dict[int, int],
    eng: dict[int, str],
    out_fh,
    counts: dict[tuple[str, int], int],
    max_per_cp_per_lang: int,
    require_translation: bool,
) -> int:
    written = 0
    with _open_text(sentence_path) as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t", 2)
            if len(parts) < 3:
                continue
            try:
                sent_id = int(parts[0])
            except ValueError:
                continue
            text = parts[2].strip()
            if not text:
                continue
            gloss = eng.get(links.get(sent_id, -1), "")
            if require_translation and not gloss:
                continue

            for ch in _ordered_unique_han(text):
                cp = ord(ch)
                key = (lang, cp)
                if counts[key] >= max_per_cp_per_lang:
                    continue
                counts[key] += 1
                out_fh.write(
                    f"U+{cp:04X}\t{lang}\t{text}\t\t{gloss}\tTatoeba\tCC BY 2.0 FR / partial CC0\n"
                )
                written += 1
    return written


def build_sentences_tsv(config: BuildSentencesConfig) -> dict[str, int]:
    jp_links = parse_links(config.jpn_eng_links)
    cn_links = parse_links(config.cmn_eng_links)
    needed_eng = set(jp_links.values()) | set(cn_links.values())
    eng = parse_english_sentences(config.eng_sentences, needed_eng)

    config.out_path.parent.mkdir(parents=True, exist_ok=True)

    counts: dict[tuple[str, int], int] = defaultdict(int)
    jp_rows = 0
    cn_rows = 0

    with config.out_path.open("w", encoding="utf-8") as out:
        out.write("# cp\\tlang\\ttext\\treading\\tgloss\\tsource\\tlicense\n")
        jp_rows = _write_rows(
            lang="jp",
            sentence_path=config.jpn_sentences,
            links=jp_links,
            eng=eng,
            out_fh=out,
            counts=counts,
            max_per_cp_per_lang=config.max_per_cp_per_lang,
            require_translation=config.require_translation,
        )
        cn_rows = _write_rows(
            lang="cn",
            sentence_path=config.cmn_sentences,
            links=cn_links,
            eng=eng,
            out_fh=out,
            counts=counts,
            max_per_cp_per_lang=config.max_per_cp_per_lang,
            require_translation=config.require_translation,
        )

    distinct_cp = len({cp for _, cp in counts})
    return {
        "rows_jp": jp_rows,
        "rows_cn": cn_rows,
        "rows_total": jp_rows + cn_rows,
        "distinct_cp": distinct_cp,
        "eng_gloss_loaded": len(eng),
    }
