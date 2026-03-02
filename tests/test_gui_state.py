from __future__ import annotations

from pathlib import Path

from kanjitui.db.build import BuildConfig, BuildPaths, build_database
from kanjitui.db.query import connect
from kanjitui.db.user import UserStore
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
        assert state.panel_focus == "variants"
        assert state.focus == "cn"

        state.show_variants = False
        state.ensure_panel_focus_valid()
        assert state.panel_focus in ("jp", "cn")
    finally:
        conn.close()
