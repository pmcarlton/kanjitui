from pathlib import Path

from kanjitui.db.user import UserStore


def test_user_store_bookmark_note_query(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "user.sqlite")
    cp = 0x6F22

    assert store.is_bookmarked(cp) is False
    assert store.toggle_bookmark(cp) is True
    assert store.is_bookmarked(cp) is True
    assert store.toggle_bookmark(cp) is False
    assert store.is_bookmarked(cp) is False

    store.add_note(cp, "review this kanji")
    notes = store.get_notes(cp)
    assert notes and "review" in notes[0]

    store.save_query("han4")
    assert "han4" in store.recent_queries(limit=5)
