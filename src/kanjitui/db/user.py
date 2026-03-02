from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3


USER_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_bookmarks (
    cp INTEGER PRIMARY KEY,
    tag TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cp INTEGER NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_global_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS saved_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_flags (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_filter_presets (
    name TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_notes_cp ON user_notes(cp, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_global_notes_created ON user_global_notes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_saved_queries_created ON saved_queries(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_filter_presets_updated ON user_filter_presets(updated_at DESC);
"""


@dataclass
class UserStore:
    db_path: Path

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.executescript(USER_SCHEMA_SQL)
        finally:
            conn.close()

    def is_bookmarked(self, cp: int) -> bool:
        conn = self._connect()
        try:
            row = conn.execute("SELECT 1 FROM user_bookmarks WHERE cp = ?", (cp,)).fetchone()
            return row is not None
        finally:
            conn.close()

    def toggle_bookmark(self, cp: int, tag: str | None = None) -> bool:
        conn = self._connect()
        try:
            with conn:
                row = conn.execute("SELECT 1 FROM user_bookmarks WHERE cp = ?", (cp,)).fetchone()
                if row is not None:
                    conn.execute("DELETE FROM user_bookmarks WHERE cp = ?", (cp,))
                    return False
                conn.execute("INSERT INTO user_bookmarks(cp, tag) VALUES(?, ?)", (cp, tag))
                return True
        finally:
            conn.close()

    def delete_bookmark(self, cp: int) -> bool:
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute("DELETE FROM user_bookmarks WHERE cp = ?", (cp,))
                return cur.rowcount > 0
        finally:
            conn.close()

    def list_bookmarks(self, limit: int = 200) -> list[tuple[int, str | None]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT cp, tag FROM user_bookmarks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [(int(row[0]), row[1]) for row in rows]
        finally:
            conn.close()

    def add_glyph_note(self, cp: int, note: str) -> None:
        text = note.strip()
        if not text:
            return
        conn = self._connect()
        try:
            with conn:
                conn.execute("INSERT INTO user_notes(cp, note) VALUES(?, ?)", (cp, text))
        finally:
            conn.close()

    def get_glyph_notes(self, cp: int, limit: int = 5) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT note FROM user_notes WHERE cp = ? ORDER BY created_at DESC LIMIT ?",
                (cp, limit),
            ).fetchall()
            return [str(row[0]) for row in rows]
        finally:
            conn.close()

    def add_global_note(self, note: str) -> None:
        text = note.strip()
        if not text:
            return
        conn = self._connect()
        try:
            with conn:
                conn.execute("INSERT INTO user_global_notes(note) VALUES(?)", (text,))
        finally:
            conn.close()

    def get_global_notes(self, limit: int = 5) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT note FROM user_global_notes ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [str(row[0]) for row in rows]
        finally:
            conn.close()

    # Backwards-compatible aliases used by existing callers/tests.
    def add_note(self, cp: int, note: str) -> None:
        self.add_glyph_note(cp, note)

    def get_notes(self, cp: int, limit: int = 5) -> list[str]:
        return self.get_glyph_notes(cp, limit=limit)

    def save_query(self, query: str) -> None:
        text = query.strip()
        if not text:
            return
        conn = self._connect()
        try:
            with conn:
                conn.execute("INSERT INTO saved_queries(query) VALUES(?)", (text,))
        finally:
            conn.close()

    def recent_queries(self, limit: int = 10) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT query FROM saved_queries ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [str(row[0]) for row in rows]
        finally:
            conn.close()

    def get_flag(self, key: str, default: bool = False) -> bool:
        conn = self._connect()
        try:
            row = conn.execute("SELECT value FROM user_flags WHERE key = ?", (key,)).fetchone()
            if row is None:
                return default
            value = str(row[0]).strip().lower()
            return value in {"1", "true", "yes", "on"}
        finally:
            conn.close()

    def set_flag(self, key: str, value: bool) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO user_flags(key, value, updated_at)
                    VALUES(?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (key, "1" if value else "0"),
                )
        finally:
            conn.close()

    def save_filter_preset(self, name: str, payload: dict[str, object]) -> None:
        preset = name.strip()
        if not preset:
            return
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO user_filter_presets(name, payload, updated_at)
                    VALUES(?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(name) DO UPDATE SET
                        payload=excluded.payload,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (preset, encoded),
                )
        finally:
            conn.close()

    def list_filter_presets(self, limit: int = 200) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT name FROM user_filter_presets ORDER BY updated_at DESC, name LIMIT ?",
                (limit,),
            ).fetchall()
            return [str(row[0]) for row in rows]
        finally:
            conn.close()

    def get_filter_preset(self, name: str) -> dict[str, object] | None:
        preset = name.strip()
        if not preset:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT payload FROM user_filter_presets WHERE name = ?",
                (preset,),
            ).fetchone()
            if row is None:
                return None
            payload = str(row[0])
            return json.loads(payload)
        finally:
            conn.close()

    def delete_filter_preset(self, name: str) -> bool:
        preset = name.strip()
        if not preset:
            return False
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute("DELETE FROM user_filter_presets WHERE name = ?", (preset,))
                return cur.rowcount > 0
        finally:
            conn.close()
