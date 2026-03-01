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

        for ch in ["1", "2", "3", "v", "p", "g", "c", "s", "u", "?", "b", "O", "F"]:
            assert app._handle_normal_key(ord(ch)) is True

        assert app._handle_normal_key(ord("n")) is True
        assert app.note_input_open is True
        assert app._handle_note_key(ord("a")) is True
        assert app._handle_note_key(10) is True
        assert app.note_input_open is False

        assert app._handle_normal_key(ord("i")) is True
        assert app.image_panel_open is True
        assert app._handle_image_key(ord("o")) is True
        assert opened
        assert app._handle_image_key(27) is True

        assert app._handle_normal_key(ord("/")) is True
        assert app._handle_search_key(ord("h")) is True
        assert app._handle_search_key(ord("a")) is True
        assert app._handle_search_key(ord("n")) is True
        assert app._handle_search_key(ord("4")) is True
        assert app._handle_search_key(10) is True
        assert isinstance(app.search_results, list)
        assert app._handle_search_key(27) is True

        assert app._handle_normal_key(ord("r")) is True
        assert app._handle_radical_key(curses.KEY_RIGHT) is True
        assert app._handle_radical_key(10) is True
        assert app._handle_radical_key(ord("]")) is True
        assert app._handle_radical_key(ord("[")) is True
        assert app._handle_radical_key(27) is True
    finally:
        conn.close()
