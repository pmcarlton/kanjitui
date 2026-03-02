from pathlib import Path

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
