from __future__ import annotations

import curses
from pathlib import Path

from kanjitui.db import query as db_query
from kanjitui.db.build import BuildConfig, BuildPaths, build_database
from kanjitui.db.query import connect
from kanjitui.db.user import UserStore
from kanjitui.tui.app import KEY_SHIFT_LEFT, KEY_SHIFT_RIGHT, TuiApp


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

        for ch in ["1", "2", "3", "4", "p", "c", "s", "u", "?", "b", "O", "F", "m", "N"]:
            assert app._handle_normal_key(ord(ch)) is True

        assert app._handle_normal_key(ord("n")) is True
        assert app.note_input_open is True
        assert "U+" in app.note_input_text
        assert app._handle_note_key(10) is True
        assert app._handle_note_key(ord("a")) is True
        assert app._handle_note_key("字") is True
        assert "\n" in app.note_input_text
        assert app._handle_note_key(19) is True  # Ctrl+S save
        assert app.note_input_open is False

        assert app._handle_normal_key(ord("g")) is True
        assert app.note_input_open is True
        assert app.note_target == "global"
        assert app._handle_note_key(ord("G")) is True
        assert app._handle_note_key(ord("L")) is True
        assert app._handle_note_key(ord("B")) is True
        assert app._handle_note_key(19) is True
        assert app.note_input_open is False

        assert app._handle_normal_key(ord("i")) is True
        assert opened
        assert "http://ccamc.org/cjkv.php?cjkv=" in opened[-1]

        assert app._handle_normal_key(ord("B")) is True
        assert app.bookmark_open is True
        assert app._handle_bookmark_key(curses.KEY_RIGHT) is True
        assert app.bookmark_reveal_mode == "readings"
        assert app._handle_bookmark_key(curses.KEY_LEFT) is True
        assert app.bookmark_reveal_mode == "gloss"
        assert app._handle_bookmark_key(curses.KEY_DOWN) is True
        assert app._handle_bookmark_key(ord("x")) is True
        if app.bookmark_open:
            assert app._handle_bookmark_key(curses.KEY_HOME) is True
            assert app._handle_bookmark_key(10) is True
            assert app.bookmark_open is False
            assert app.bookmark_reveal_mode == "none"
        else:
            assert not app.bookmark_rows

        assert app._handle_normal_key(ord("/")) is True
        assert app._handle_search_key(ord("h")) is True
        assert app._handle_search_key(ord("a")) is True
        assert app._handle_search_key(ord("n")) is True
        assert app._handle_search_key(ord("4")) is True
        assert app._handle_search_key("角") is True
        assert "角" in app.search_input
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

        # Variants panel focus and Enter jump path.
        found_variant = False
        for idx in range(len(app.ordered_cps)):
            app.pos = idx
            _graph, targets = app._variant_data_for_current()
            if targets:
                found_variant = True
                break
        assert found_variant is True

        app.show_jp = True
        app.show_cn = True
        app.show_variants = True
        app.panel_focus = "jp"
        assert app._handle_normal_key(9) is True  # cn
        assert app._handle_normal_key(9) is True  # variants
        assert app.panel_focus == "variants"

        old_cp = app.current_cp
        assert old_cp is not None
        app.variant_idx = 0
        assert app._handle_normal_key(10) is True
        assert app.current_cp != old_cp
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


def test_no_reading_plus_filters_keeps_valid_current_glyph(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        app = TuiApp(conn)
        base = list(app.ordered_cps)
        assert base

        # Pick a glyph that has readings but no sentence rows in fixture data.
        current = next((cp for cp in base if cp in app.cn_reading_cps and cp not in app.filter_data.sentences_cps), None)
        assert current is not None
        app.pos = base.index(current)
        assert app.current_cp == current

        app.hide_no_reading = True
        app.filter_state.has_sentences = "yes"
        app._refresh_ordering()

        assert app.current_cp in app.ordered_cps
        assert all(cp in app.filter_data.sentences_cps for cp in app.ordered_cps)
    finally:
        conn.close()


def test_radical_results_follow_current_filters(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        app = TuiApp(conn)
        app.filter_state.has_sentences = "yes"
        app._refresh_ordering()

        app.radical_open = True
        app.radical_idx = 84  # radical #85 (water)
        assert app._handle_radical_key(10) is True
        assert app.radical_selected == 85
        assert app.radical_results == [0x6F22]

        app.radical_results = None
        app.radical_selected = None
        app.radical_idx = 0  # radical #1 has no fixture matches
        assert app._handle_radical_key(10) is True
        assert app.radical_results is None
        assert app.radical_selected is None
        assert "no matches under current filters" in app.message
    finally:
        conn.close()


def test_shift_s_and_shift_r_open_setup_and_advanced(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        app = TuiApp(conn)
        assert app.setup_open is False
        assert app.advanced_open is False
        assert app.show_phonetic is False

        assert app._handle_normal_key(ord("S")) is True
        assert app.setup_open is True
        assert app.advanced_open is False
        assert app.show_phonetic is False

        assert app._handle_setup_key(27) is True
        assert app.setup_open is False

        assert app._handle_normal_key(ord("R")) is True
        assert app.advanced_open is True
        assert app.show_phonetic is False

        assert app._handle_advanced_key(27) is True
        assert app.advanced_open is False

        assert app._handle_normal_key(ord("s")) is True
        assert app.show_phonetic is True
    finally:
        conn.close()


def test_startup_overlay_dismissed_on_non_ascii_input(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        app = TuiApp(conn)
        app.show_startup_overlay = True
        assert app._handle_normal_key("角") is True
        assert app.show_startup_overlay is False
    finally:
        conn.close()


def test_setup_download_triggers_auto_build_and_reconnect(tmp_path: Path, monkeypatch) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    app = TuiApp(conn)
    app.setup_selected = {"unihan"}
    calls: dict[str, object] = {}

    def fake_download_selected_sources(selected, paths, progress):
        calls["selected"] = tuple(selected)
        progress("download ok")
        return {"unihan": "ok"}

    def fake_rebuild_database_from_sources(paths, db_path, progress, font=None):
        calls["db_path"] = db_path
        calls["font"] = font
        progress("build ok")
        return {"included": 1, "excluded_font": 0}

    monkeypatch.setattr("kanjitui.tui.app.download_selected_sources", fake_download_selected_sources)
    monkeypatch.setattr("kanjitui.tui.app.rebuild_database_from_sources", fake_rebuild_database_from_sources)

    app._run_setup_download()
    try:
        assert calls["selected"] == ("unihan",)
        assert Path(calls["db_path"]) == db_path
        assert calls["font"] is None
        assert any("build ok" in line for line in app.setup_logs)
        assert app.conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        app.conn.close()


def test_setup_download_passes_default_font_when_font_filter_enabled(tmp_path: Path, monkeypatch) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    app = TuiApp(conn)
    app.setup_selected = {"unihan"}
    app.setup_font_filter = True
    calls: dict[str, object] = {}

    def fake_download_selected_sources(selected, paths, progress):
        calls["selected"] = tuple(selected)
        progress("download ok")
        return {"unihan": "ok"}

    def fake_rebuild_database_from_sources(paths, db_path, progress, font=None):
        calls["font"] = font
        progress("build ok")
        return {"included": 1, "excluded_font": 0}

    monkeypatch.setattr("kanjitui.tui.app.default_build_font", lambda: "Test Font")
    monkeypatch.setattr("kanjitui.tui.app.download_selected_sources", fake_download_selected_sources)
    monkeypatch.setattr("kanjitui.tui.app.rebuild_database_from_sources", fake_rebuild_database_from_sources)

    app._run_setup_download()
    try:
        assert calls["selected"] == ("unihan",)
        assert calls["font"] == "Test Font"
        assert any("Using font filter for setup auto-build: Test Font" in line for line in app.setup_logs)
    finally:
        app.conn.close()


def test_setup_rebuild_progress_does_not_render_while_db_is_closed(tmp_path: Path, monkeypatch) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    app = TuiApp(conn)
    app.setup_selected = {"unihan"}
    app._stdscr = object()  # enable render path in setup progress callback
    render_calls: list[str] = []

    def fake_download_selected_sources(selected, paths, progress):
        return {"unihan": "ok"}

    def fake_render(_stdscr) -> None:
        render_calls.append("render")

    def fake_rebuild_database_from_sources(paths, db_path, progress, font=None):
        progress("build progress")
        return {"included": 1, "excluded_font": 0}

    monkeypatch.setattr("kanjitui.tui.app.download_selected_sources", fake_download_selected_sources)
    monkeypatch.setattr("kanjitui.tui.app.rebuild_database_from_sources", fake_rebuild_database_from_sources)
    monkeypatch.setattr(app, "_render", fake_render)

    app._run_setup_download()
    try:
        assert render_calls == []
    finally:
        app.conn.close()


def test_up_down_select_related_and_enter_jumps(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        app = TuiApp(conn)
        if 0x6F22 in app.ordered_cps:
            app.pos = app.ordered_cps.index(0x6F22)
        start_cp = app.current_cp
        assert start_cp is not None

        assert app._handle_normal_key(curses.KEY_DOWN) is True
        assert app.current_cp == start_cp
        assert "Related:" in app.message or "No related glyphs" in app.message

        if "Related:" in app.message:
            assert app._handle_normal_key(10) is True
            assert app.current_cp != start_cp
    finally:
        conn.close()


def test_tui_decodes_shift_arrow_escape_sequences(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        app = TuiApp(conn)
        assert app._decode_escape_sequence("[1;2C") == KEY_SHIFT_RIGHT
        assert app._decode_escape_sequence("[1;2D") == KEY_SHIFT_LEFT
        assert app._decode_escape_sequence("[C") == curses.KEY_RIGHT
        assert app._decode_escape_sequence("[A") == curses.KEY_UP
    finally:
        conn.close()


def test_shift_left_right_cycle_related_on_same_line(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        app = TuiApp(conn)
        if 0x6F22 in app.ordered_cps:
            app.pos = app.ordered_cps.index(0x6F22)
        current = app.current_cp
        assert current is not None
        detail_obj = db_query.get_char_detail(app.conn, current)
        # Find a related row that has at least 2 selectable glyphs.
        rows = app._related_rows_for_detail(detail_obj, include_phonetic=False)
        idx = next((i for i, row in enumerate(rows) if len(row) > 1), None)
        if idx is None:
            return
        app.related_row_idx = idx
        app.related_col_idx = 0
        first = app._selected_related_cp(detail_obj, include_phonetic=False)
        assert first is not None
        assert app._move_related_selection_horizontal(+1) is True
        second = app._selected_related_cp(detail_obj, include_phonetic=False)
        assert second is not None
        assert second != first
    finally:
        conn.close()


def test_phonetic_rows_participate_in_related_selection(tmp_path: Path, monkeypatch) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        app = TuiApp(conn)
        if 0x6F22 in app.ordered_cps:
            app.pos = app.ordered_cps.index(0x6F22)
        app.show_phonetic = True

        def fake_phonetic(_conn, _cp, limit=120):
            _ = limit
            return [(0x3400, "㐀", "PHON:X", None, None)]

        monkeypatch.setattr("kanjitui.tui.app.db_query.get_phonetic_series", fake_phonetic)
        detail = db_query.get_char_detail(app.conn, app.current_cp or 0x6F22)
        rows = app._related_rows_for_detail(detail, include_phonetic=True)
        assert rows
        app.related_row_idx = max(0, len(rows) - 2)
        app.related_col_idx = 0
        assert app._move_related_selection_vertical(+1) is True
        assert "U+3400" in app.message
    finally:
        conn.close()


def test_filter_overlay_applies_reading_filter(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        app = TuiApp(conn)
        baseline = len(app.ordered_cps)
        assert app._handle_normal_key(ord("f")) is True
        assert app.filter_open is True
        target_idx = next(
            idx
            for idx, (group_key, _group_label, value, _label) in enumerate(app.filter_options)
            if group_key == "reading_availability" and value == "jp"
        )
        app.filter_idx = target_idx
        assert app._handle_filter_key(ord(" ")) is True
        assert len(app.ordered_cps) <= baseline
        assert app.ordered_cps
        assert all(cp in app.jp_reading_cps for cp in app.ordered_cps)
        assert app._handle_filter_key(27) is True
        assert app.filter_open is False
    finally:
        conn.close()
