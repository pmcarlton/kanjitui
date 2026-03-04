from pathlib import Path
import sqlite3

from kanjitui.db.user import UserStore


def test_user_store_bookmark_note_query(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "user.sqlite")
    cp = 0x6F22

    assert store.is_bookmarked(cp) is False
    assert store.toggle_bookmark(cp) is True
    assert store.is_bookmarked(cp) is True
    assert store.delete_bookmark(cp) is True
    assert store.is_bookmarked(cp) is False
    assert store.delete_bookmark(cp) is False

    store.add_glyph_note(cp, "review this kanji")
    notes = store.get_glyph_notes(cp)
    assert notes and "review" in notes[0]

    store.add_global_note("global memo")
    gnotes = store.get_global_notes(limit=5)
    assert gnotes and "global" in gnotes[0]

    store.save_query("han4")
    assert "han4" in store.recent_queries(limit=5)


def test_user_store_flags_roundtrip(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "user.sqlite")
    assert store.get_flag("startup_seen", default=False) is False
    assert store.get_flag("startup_seen", default=True) is True
    store.set_flag("startup_seen", True)
    assert store.get_flag("startup_seen", default=False) is True
    store.set_flag("startup_seen", False)
    assert store.get_flag("startup_seen", default=True) is False


def test_user_store_filter_presets_roundtrip(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "user.sqlite")
    payload = {"filters": {"reading_availability": "jp"}, "hide_no_reading": True}
    store.save_filter_preset("jp-only", payload)
    names = store.list_filter_presets(limit=10)
    assert "jp-only" in names
    loaded = store.get_filter_preset("jp-only")
    assert loaded is not None
    assert loaded["hide_no_reading"] is True
    assert store.delete_filter_preset("jp-only") is True
    assert store.get_filter_preset("jp-only") is None


def test_user_store_bookmark_sets_import_export(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "user.sqlite")
    cp_default = 0x6F22
    cp_jp = 0x89D2

    assert store.active_bookmark_set() == "default"
    assert store.toggle_bookmark(cp_default) is True

    assert store.create_bookmark_set("jp-study", make_active=True) is True
    assert store.active_bookmark_set() == "jp-study"
    assert store.toggle_bookmark(cp_jp) is True
    assert store.is_bookmarked(cp_default) is False
    assert store.is_bookmarked(cp_jp) is True

    out_path = tmp_path / "jp-study.json"
    exported = store.export_bookmark_set(out_path)
    assert exported == 1

    imported_name, imported_count = store.import_bookmark_set(
        out_path,
        set_name="imported",
        replace=True,
        make_active=True,
    )
    assert imported_name == "imported"
    assert imported_count == 1
    assert store.active_bookmark_set() == "imported"
    assert store.is_bookmarked(cp_jp) is True

    assert store.delete_bookmark_set("imported") is True
    assert store.active_bookmark_set() != "imported"


def test_user_store_migrates_legacy_bookmark_table(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            """
            CREATE TABLE user_bookmarks (
                cp INTEGER PRIMARY KEY,
                tag TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT INTO user_bookmarks(cp, tag) VALUES(?, ?)",
            (0x6F22, "legacy"),
        )
    conn.close()

    store = UserStore(db_path)
    assert store.active_bookmark_set() == "default"
    rows = store.list_bookmarks(limit=10, set_name="default")
    assert rows
    assert rows[0][0] == 0x6F22
