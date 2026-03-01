import sqlite3

from kanjitui.db.migrations import apply_migrations, current_schema_version, rebuild_schema


def test_apply_migrations_creates_schema() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        version = apply_migrations(conn)
        assert version >= 1
        assert current_schema_version(conn) == version

        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chars'"
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_rebuild_schema_clears_data_and_reapplies() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        apply_migrations(conn)
        conn.execute(
            "INSERT INTO chars(cp, ch, radical, strokes, freq, sources) VALUES(?,?,?,?,?,?)",
            (0x6F22, "漢", 85, 13, None, "test"),
        )
        conn.commit()

        rebuild_schema(conn)
        count = conn.execute("SELECT COUNT(*) FROM chars").fetchone()[0]
        assert count == 0
        assert current_schema_version(conn) >= 1
    finally:
        conn.close()
