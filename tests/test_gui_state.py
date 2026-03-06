from __future__ import annotations

from pathlib import Path

from kanjitui.db.build import BuildConfig, BuildPaths, build_database
from kanjitui.db.query import connect
from kanjitui.db.user import UserStore
from kanjitui.filtering import FilterState
from kanjitui.gui.state import GuiState


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


def test_gui_state_sentence_lang_scope_and_filter(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        state = GuiState(conn)
        assert state.sentence_langs() == ("jp", "cn")
        baseline = len(state.ordered_cps)

        state.toggle_no_reading()
        assert state.hide_no_reading is True
        assert len(state.ordered_cps) == baseline

        state.show_cn = False
        state.refresh_ordering()
        assert state.sentence_langs() == ("jp",)
        assert len(state.ordered_cps) < baseline
    finally:
        conn.close()


def test_gui_state_ccamc_and_bookmark(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    user_store = UserStore(tmp_path / "user.sqlite")
    try:
        state = GuiState(conn, user_store=user_store)
        url = state.current_ccamc_url()
        assert url is not None
        assert url.startswith("http://ccamc.org/cjkv.php?cjkv=")

        cp = state.current_cp
        assert cp is not None
        state.toggle_bookmark()
        assert cp in state.bookmarked_cps
        assert state.delete_bookmark(cp) is True
        assert cp not in state.bookmarked_cps

        state.save_glyph_note("glyph note")
        assert any("glyph" in note for note in user_store.get_glyph_notes(cp, limit=5))
        state.save_global_note("global note")
        assert any("global" in note for note in user_store.get_global_notes(limit=5))
    finally:
        conn.close()


def test_gui_state_tab_focus_cycles_to_variants(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        state = GuiState(conn)
        assert state.panel_focus == "jp"
        assert state.focus == "jp"

        state.toggle_focus()
        assert state.panel_focus == "cn"
        assert state.focus == "cn"

        state.toggle_focus()
        assert state.panel_focus == "sentences"
        assert state.focus == "cn"

        state.toggle_focus()
        assert state.panel_focus == "variants"
        assert state.focus == "cn"

        state.show_variants = False
        state.ensure_panel_focus_valid()
        assert state.panel_focus in ("jp", "cn")
    finally:
        conn.close()


def test_gui_state_reload_db_state_preserves_current_cp_when_possible(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        state = GuiState(conn)
        cp = state.current_cp
        assert cp is not None
        state.move_next()
        cp2 = state.current_cp
        assert cp2 is not None
        state.reload_db_state(current_cp=cp2)
        assert state.current_cp == cp2
    finally:
        conn.close()


def test_gui_state_filter_state_applies(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        state = GuiState(conn)
        baseline = len(state.ordered_cps)
        state.set_filter_state(FilterState(reading_availability="cn"))
        assert state.ordered_cps
        assert len(state.ordered_cps) <= baseline
        assert all(cp in state.cn_reading_cps for cp in state.ordered_cps)
        assert state.preview_filter_count(FilterState(reading_availability="jp_or_cn")) >= len(state.ordered_cps)
    finally:
        conn.close()


def test_gui_state_filter_fallback_uses_final_filtered_order(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        state = GuiState(conn)
        base = list(state.ordered_cps)
        assert base

        # Pick a glyph that has readings but no sentence rows in fixture data.
        current = next((cp for cp in base if cp in state.cn_reading_cps and cp not in state.filter_data.sentences_cps), None)
        assert current is not None
        state.pos = base.index(current)
        assert state.current_cp == current

        state.hide_no_reading = True
        state.set_filter_state(FilterState(has_sentences="yes"))

        assert state.current_cp in state.ordered_cps
        assert all(cp in state.filter_data.sentences_cps for cp in state.ordered_cps)
    finally:
        conn.close()


def test_gui_state_radical_results_follow_filters_and_include_names(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        state = GuiState(conn)
        state.set_filter_state(FilterState(has_sentences="yes"))

        assert state.radical_is_available(85) is True
        assert state.radical_is_available(1) is False

        state.radical_pick(84)  # radical #85 (water)
        assert state.radical_selected == 85
        assert state.radical_results == [0x6F22]

        info = state.radical_info_line(85)
        assert "#85" in info
        assert "EN:Water" in info
        assert "JP:さんずい" in info
        assert "CN:三点水" in info
    finally:
        conn.close()
