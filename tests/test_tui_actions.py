from __future__ import annotations

import curses
from pathlib import Path

from kanjitui.db.build import BuildConfig, BuildPaths, build_database
from kanjitui.db.query import connect
from kanjitui.db.user import UserStore
from kanjitui.tui.app import TuiApp


def _build_fixture_db(tmp_path: Path) -> Path:
    fixtures = Path(__file__).parent / "fixtures"
    db_path = tmp_path / "db.sqlite"
    build_database(
        BuildConfig(
            db_path=db_path,
            paths=BuildPaths(
                unihan_dir=fixtures / "unihan",
                kanjidic2_xml=fixtures / "kanjidic2.xml",
                jmdict_xml=fixtures / "jmdict.xml",
                cedict_txt=fixtures / "cedict_ts.u8",
                sentences_tsv=fixtures / "sentences.tsv",
            ),
            font=None,
            enabled_providers=("unihan", "kanjidic2", "jmdict", "cedict", "sentences"),
        )
    )
    return db_path


def test_menu_actions_smoke(tmp_path: Path, monkeypatch) -> None:
    db_path = _build_fixture_db(tmp_path)
    user_store = UserStore(tmp_path / "user.sqlite")

    opened: list[str] = []

    def fake_open(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr("webbrowser.open", fake_open)

    conn = connect(db_path)
    try:
        app = TuiApp(conn, user_store=user_store)

        for ch in ["1", "2", "3", "v", "p", "c", "s", "u", "?", "b", "O", "F", "m", "N"]:
            assert app._handle_normal_key(ord(ch)) is True

        assert app._handle_normal_key(ord("n")) is True
        assert app.note_input_open is True
        assert app._handle_note_key(ord("a")) is True
        assert app._handle_note_key(10) is True
        assert app.note_input_open is False

        assert app._handle_normal_key(ord("i")) is True
        assert opened
        assert "http://ccamc.org/cjkv.php?cjkv=" in opened[-1]

        assert app._handle_normal_key(ord("/")) is True
        assert app._handle_search_key(ord("h")) is True
        assert app._handle_search_key(ord("a")) is True
        assert app._handle_search_key(ord("n")) is True
        assert app._handle_search_key(ord("4")) is True
        assert app._handle_search_key(10) is True
        assert isinstance(app.search_results, list)
        if app.search_results:
            app.search_idx = min(3, len(app.search_results) - 1)
            assert app._handle_search_key(curses.KEY_NPAGE) is True
            assert app.search_idx == len(app.search_results) - 1
            assert app._handle_search_key(curses.KEY_PPAGE) is True
            assert app.search_idx == 0
        assert app._handle_search_key(27) is True

        assert app._handle_normal_key(ord("r")) is True
        assert app._handle_radical_key(curses.KEY_RIGHT) is True
        assert app._handle_radical_key(10) is True
        assert app._handle_radical_key(ord("]")) is True
        assert app._handle_radical_key(ord("[")) is True
        assert app._handle_radical_key(27) is True

        assert app._handle_normal_key(ord("N")) is True
        assert app.hide_no_reading is False
    finally:
        conn.close()


def test_no_reading_filter_respects_language_scope(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        app = TuiApp(conn)
        baseline = len(app.ordered_cps)
        assert baseline > 0

        # With both JP and CN shown, "either" scope keeps all fixture chars.
        assert app.show_jp is True and app.show_cn is True
        assert app._handle_normal_key(ord("N")) is True
        assert app.hide_no_reading is True
        assert len(app.ordered_cps) == baseline

        # JP-only view filters to chars that actually have JP readings.
        assert app._handle_normal_key(ord("2")) is True
        assert len(app.ordered_cps) < baseline
        assert len(app.ordered_cps) > 0
    finally:
        conn.close()


def test_no_reading_filter_advances_to_next_glyph_when_current_filtered(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        app = TuiApp(conn)
        app.ordering_idx = 3  # codepoint ordering for deterministic neighbor checks
        app._refresh_ordering()

        base = list(app.ordered_cps)
        assert base
        assert app.jp_reading_cps

        current = next((cp for cp in base if cp not in app.jp_reading_cps), None)
        assert current is not None
        app.pos = base.index(current)
        assert app.current_cp == current

        expected = None
        for offset in range(1, len(base) + 1):
            candidate = base[(app.pos + offset) % len(base)]
            if candidate in app.jp_reading_cps:
                expected = candidate
                break
        assert expected is not None

        assert app._handle_normal_key(ord("2")) is True  # JP only
        assert app._handle_normal_key(ord("N")) is True  # enable hide-no-reading
        assert app.current_cp == expected
    finally:
        conn.close()
