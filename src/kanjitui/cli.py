from __future__ import annotations

import argparse
import csv
import json
import logging
import sys

from kanjitui import __version__
from kanjitui.config import ConfigError, resolve_app_config, resolve_build_paths
from kanjitui.db.build import BuildConfig, BuildPaths, build_database
from kanjitui.db import query as db_query
from kanjitui.db.query import connect
from kanjitui.logging_utils import configure_logging
from kanjitui.search.normalizer import get_normalizer
from kanjitui.tui.app import run_tui


LOGGER = logging.getLogger(__name__)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kanji/CJK terminal explorer")
    parser.add_argument("--config", help="Path to TOML config file")
    parser.add_argument("--db", help="SQLite DB path")
    parser.add_argument("--user-db", help="User metadata DB path (groundwork)")
    parser.add_argument("--build", action="store_true", default=None, help="Build database from source files")
    parser.add_argument("--data-dir", help="Directory containing source data files")
    parser.add_argument("--font", help="Font name/path for coverage filtering")
    parser.add_argument("--providers", help="Comma-separated provider list (e.g. unihan,kanjidic2,jmdict,cedict)")
    parser.add_argument("--normalizer", help="Search normalization profile (default, strict)")
    parser.add_argument("--font-profile-out", help="Coverage cache output path")
    parser.add_argument("--build-report-out", help="Build report JSON path")
    parser.add_argument("--unihan-dir", help="Path to Unihan text files directory")
    parser.add_argument("--kanjidic2", help="Path to KANJIDIC2 XML")
    parser.add_argument("--jmdict", help="Path to JMdict XML")
    parser.add_argument("--cedict", help="Path to CC-CEDICT text file")
    parser.add_argument("--no-font-filter", action="store_true", default=None, help="Disable font coverage filtering")
    parser.add_argument("--export-char", help="Export one character detail (char, U+XXXX, or hex cp)")
    parser.add_argument("--export-query", help="Export search results for a query")
    parser.add_argument("--export-format", choices=("json", "csv"), default="json", help="Export format")
    parser.add_argument("--export-out", help="Export output file path (default: stdout)")
    parser.add_argument("--verbose", action="store_true", default=None, help="Verbose logging")
    parser.add_argument("--version", action="version", version=f"kanjitui {__version__}")
    return parser


def _parse_cp_token(token: str) -> int | None:
    raw = token.strip()
    if not raw:
        return None
    if len(raw) == 1:
        return ord(raw)
    if raw.lower().startswith("u+"):
        raw = raw[2:]
    try:
        return int(raw, 16)
    except ValueError:
        return None


def _write_text(path: str | None, text: str) -> None:
    if path:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return
    print(text)


def _export_json(path: str | None, payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    _write_text(path, text)


def _export_csv(path: str | None, rows: list[dict], fieldnames: list[str]) -> None:
    if path:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return

    out = []
    out.append(",".join(fieldnames))
    for row in rows:
        out.append(",".join(str(row.get(field, "")) for field in fieldnames))
    print("\n".join(out))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        app_config = resolve_app_config(args)
    except (ConfigError, FileNotFoundError) as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    try:
        _ = get_normalizer(app_config.normalizer)
    except ValueError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    configure_logging(verbose=app_config.verbose)
    export_requested = bool(args.export_char or args.export_query)

    if app_config.build:
        source_paths = resolve_build_paths(app_config)
        paths = BuildPaths(
            unihan_dir=source_paths.unihan_dir,
            kanjidic2_xml=source_paths.kanjidic2_xml,
            jmdict_xml=source_paths.jmdict_xml,
            cedict_txt=source_paths.cedict_txt,
        )
        font = None if app_config.no_font_filter else app_config.font
        config = BuildConfig(
            db_path=app_config.db_path,
            paths=paths,
            font=font,
            font_profile_out=app_config.font_profile_out,
            build_report_out=app_config.build_report_out,
            enabled_providers=app_config.providers,
        )
        try:
            counts = build_database(config)
        except FileNotFoundError as exc:
            print(f"Build error: {exc}", file=sys.stderr)
            print("Place source files and rerun with --build.", file=sys.stderr)
            return 2

        LOGGER.info("build_summary", extra=counts)
        print(
            f"Built DB at {app_config.db_path} with {counts['included']} included chars "
            f"({counts['excluded_font']} excluded by font filter)."
        )
        if not export_requested:
            return 0

    if not app_config.db_path.exists():
        print(f"Database missing: {app_config.db_path}", file=sys.stderr)
        print("Run `kanjitui --build` first (or `make build-db`).", file=sys.stderr)
        return 2

    conn = connect(app_config.db_path)
    try:
        if args.export_char:
            cp = _parse_cp_token(args.export_char)
            if cp is None:
                print(f"Invalid --export-char value: {args.export_char}", file=sys.stderr)
                return 2
            try:
                detail = db_query.get_char_detail(conn, cp)
            except KeyError:
                print(f"Character not found in DB: U+{cp:04X}", file=sys.stderr)
                return 2
            detail["provenance"] = db_query.get_provenance(conn, cp)
            if args.export_format == "json":
                _export_json(args.export_out, detail)
            else:
                rows = []
                for key, value in detail.items():
                    if isinstance(value, list):
                        flattened = "; ".join(str(x) for x in value)
                    else:
                        flattened = str(value)
                    rows.append({"field": key, "value": flattened})
                _export_csv(args.export_out, rows, ["field", "value"])
            return 0

        if args.export_query:
            rows = db_query.search(
                conn,
                args.export_query,
                limit=200,
                normalizer=get_normalizer(app_config.normalizer),
            )
            if args.export_format == "json":
                _export_json(args.export_out, rows)
            else:
                _export_csv(args.export_out, rows, ["cp", "ch", "jp", "cn", "gloss"])
            return 0

        run_tui(conn, normalizer_name=app_config.normalizer)
    except KeyboardInterrupt:
        return 0
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
