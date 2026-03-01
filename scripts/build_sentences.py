#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from kanjitui.providers.tatoeba import BuildSentencesConfig, build_sentences_tsv, download_if_missing


BASE = "https://downloads.tatoeba.org/exports/per_language"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build kanjitui sentences.tsv from Tatoeba exports")
    parser.add_argument("--download-dir", default="data/raw/tatoeba", help="Directory for downloaded Tatoeba files")
    parser.add_argument("--out", default="data/raw/sentences.tsv", help="Output TSV path")
    parser.add_argument("--max-per-cp", type=int, default=3, help="Max sentence rows per cp per language")
    parser.add_argument("--force-download", action="store_true", help="Force redownload even if files exist")
    parser.add_argument(
        "--require-translation",
        action="store_true",
        help="Only include rows with English translation gloss",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    download_dir = Path(args.download_dir)

    urls = {
        "jpn_sentences": f"{BASE}/jpn/jpn_sentences.tsv.bz2",
        "cmn_sentences": f"{BASE}/cmn/cmn_sentences.tsv.bz2",
        "eng_sentences": f"{BASE}/eng/eng_sentences.tsv.bz2",
        "jpn_eng_links": f"{BASE}/jpn/jpn-eng_links.tsv.bz2",
        "cmn_eng_links": f"{BASE}/cmn/cmn-eng_links.tsv.bz2",
    }

    paths: dict[str, Path] = {}
    for key, url in urls.items():
        dest = download_dir / Path(url).name
        print(f"fetching {url}")
        paths[key] = download_if_missing(url, dest, force=args.force_download)

    cfg = BuildSentencesConfig(
        jpn_sentences=paths["jpn_sentences"],
        cmn_sentences=paths["cmn_sentences"],
        eng_sentences=paths["eng_sentences"],
        jpn_eng_links=paths["jpn_eng_links"],
        cmn_eng_links=paths["cmn_eng_links"],
        out_path=Path(args.out),
        max_per_cp_per_lang=args.max_per_cp,
        require_translation=args.require_translation,
    )

    stats = build_sentences_tsv(cfg)
    print(f"wrote {cfg.out_path}")
    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
