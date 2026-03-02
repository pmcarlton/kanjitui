from __future__ import annotations

import argparse
import logging
import sqlite3
import sys

from kanjitui import __version__
from kanjitui.config import ConfigError, resolve_app_config, resolve_build_paths
from kanjitui.db import query as db_query
from kanjitui.db.build import BuildConfig, BuildPaths, build_database
from kanjitui.db.query import connect
from kanjitui.db.user import UserStore
from kanjitui.logging_utils import configure_logging
from kanjitui.search.normalizer import get_normalizer


LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kanji/CJK desktop explorer (PySide6)")
    parser.add_argument("--config", help="Path to TOML config file")
    parser.add_argument("--db", help="SQLite DB path")
    parser.add_argument("--user-db", help="User metadata DB path")
    parser.add_argument("--build", action="store_true", default=None, help="Build database from source files")
    parser.add_argument("--data-dir", help="Directory containing source data files")
    parser.add_argument("--font", help="Font name/path for coverage filtering")
    parser.add_argument("--providers", help="Comma-separated provider list")
    parser.add_argument("--normalizer", help="Search normalization profile (default, strict)")
    parser.add_argument("--font-profile-out", help="Coverage cache output path")
    parser.add_argument("--build-report-out", help="Build report JSON path")
    parser.add_argument("--unihan-dir", help="Path to Unihan text files directory")
    parser.add_argument("--kanjidic2", help="Path to KANJIDIC2 XML")
    parser.add_argument("--jmdict", help="Path to JMdict XML")
    parser.add_argument("--cedict", help="Path to CC-CEDICT text file")
    parser.add_argument("--sentences", help="Path to optional sentence TSV")
    parser.add_argument("--no-font-filter", action="store_true", default=None, help="Disable font coverage filtering")
    parser.add_argument("--verbose", action="store_true", default=None, help="Verbose logging")
    parser.add_argument("--version", action="version", version=f"kanjigui {__version__}")
    return parser


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

    if app_config.build:
        source_paths = resolve_build_paths(app_config)
        paths = BuildPaths(
            unihan_dir=source_paths.unihan_dir,
            kanjidic2_xml=source_paths.kanjidic2_xml,
            jmdict_xml=source_paths.jmdict_xml,
            cedict_txt=source_paths.cedict_txt,
            sentences_tsv=source_paths.sentences_tsv,
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
        except sqlite3.OperationalError as exc:
            if "database is locked" in str(exc).lower():
                print(f"Build error: {exc}", file=sys.stderr)
                print(
                    "Target DB is locked. Close running kanjitui/kanjigui instances or build to a different --db path.",
                    file=sys.stderr,
                )
                return 2
            raise
        LOGGER.info("build_summary", extra=counts)
        print(
            f"Built DB at {app_config.db_path} with {counts['included']} included chars "
            f"({counts['excluded_font']} excluded by font filter)."
        )

    app_config.db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from kanjitui.gui.window import run_gui
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            print("Missing dependency: PySide6", file=sys.stderr)
            print("Install with: pip install '.[gui]'", file=sys.stderr)
            return 2
        raise

    conn = connect(app_config.db_path)
    user_store = UserStore(app_config.user_db_path)
    try:
        # Warm one query early so the first frame is immediate.
        _ = db_query.available_frequency_profiles(conn)
        run_gui(conn, normalizer_name=app_config.normalizer, user_store=user_store)
    except KeyboardInterrupt:
        return 0
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
