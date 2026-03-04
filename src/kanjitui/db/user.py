from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any


USER_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_bookmark_sets (
    name TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_bookmarks (
    set_name TEXT NOT NULL,
    cp INTEGER NOT NULL,
    tag TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(set_name, cp),
    FOREIGN KEY(set_name) REFERENCES user_bookmark_sets(name) ON DELETE CASCADE
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

CREATE TABLE IF NOT EXISTS user_settings (
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
CREATE INDEX IF NOT EXISTS idx_user_bookmark_sets_updated ON user_bookmark_sets(updated_at DESC, name);
"""

BOOKMARK_SET_DEFAULT = "default"
BOOKMARK_SET_ACTIVE_KEY = "active_bookmark_set"


@dataclass
class UserStore:
    db_path: Path

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.executescript(USER_SCHEMA_SQL)
                self._migrate_bookmark_schema(conn)
                self._ensure_default_bookmark_set(conn)
                self._ensure_bookmark_indexes(conn)
        finally:
            conn.close()

    @staticmethod
    def _normalize_set_name(name: str | None) -> str:
        if name is None:
            return ""
        return " ".join(name.strip().split())

    @staticmethod
    def _bookmark_table_has_set_name(conn: sqlite3.Connection) -> bool:
        rows = conn.execute("PRAGMA table_info(user_bookmarks)").fetchall()
        return any(str(row["name"]) == "set_name" for row in rows)

    def _migrate_bookmark_schema(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_bookmarks'"
        ).fetchone()
        if row is None:
            return
        if self._bookmark_table_has_set_name(conn):
            return

        conn.execute("ALTER TABLE user_bookmarks RENAME TO user_bookmarks_legacy")
        conn.execute(
            """
            CREATE TABLE user_bookmarks (
                set_name TEXT NOT NULL,
                cp INTEGER NOT NULL,
                tag TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(set_name, cp),
                FOREIGN KEY(set_name) REFERENCES user_bookmark_sets(name) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO user_bookmark_sets(name) VALUES(?)",
            (BOOKMARK_SET_DEFAULT,),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO user_bookmarks(set_name, cp, tag, created_at)
            SELECT ?, cp, tag, COALESCE(created_at, CURRENT_TIMESTAMP)
            FROM user_bookmarks_legacy
            """,
            (BOOKMARK_SET_DEFAULT,),
        )
        conn.execute("DROP TABLE user_bookmarks_legacy")

    def _ensure_bookmark_indexes(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_bookmarks_set_created ON user_bookmarks(set_name, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_bookmarks_cp ON user_bookmarks(cp)"
        )

    def _get_setting(self, conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute("SELECT value FROM user_settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return str(row[0])

    def _set_setting(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            """
            INSERT INTO user_settings(key, value, updated_at)
            VALUES(?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=CURRENT_TIMESTAMP
            """,
            (key, value),
        )

    def _bookmark_set_exists(self, conn: sqlite3.Connection, name: str) -> bool:
        row = conn.execute("SELECT 1 FROM user_bookmark_sets WHERE name = ?", (name,)).fetchone()
        return row is not None

    def _touch_bookmark_set(self, conn: sqlite3.Connection, name: str) -> None:
        conn.execute(
            "UPDATE user_bookmark_sets SET updated_at = CURRENT_TIMESTAMP WHERE name = ?",
            (name,),
        )

    def _ensure_default_bookmark_set(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO user_bookmark_sets(name) VALUES(?)",
            (BOOKMARK_SET_DEFAULT,),
        )
        active = self._get_setting(conn, BOOKMARK_SET_ACTIVE_KEY)
        if not active or not self._bookmark_set_exists(conn, active):
            self._set_setting(conn, BOOKMARK_SET_ACTIVE_KEY, BOOKMARK_SET_DEFAULT)

    def _active_bookmark_set_conn(self, conn: sqlite3.Connection) -> str:
        self._ensure_default_bookmark_set(conn)
        active = self._normalize_set_name(self._get_setting(conn, BOOKMARK_SET_ACTIVE_KEY))
        if not active or not self._bookmark_set_exists(conn, active):
            active = BOOKMARK_SET_DEFAULT
            self._set_setting(conn, BOOKMARK_SET_ACTIVE_KEY, active)
        return active

    def _resolve_bookmark_set(
        self,
        conn: sqlite3.Connection,
        set_name: str | None,
        create_if_missing: bool = False,
    ) -> str:
        target = self._normalize_set_name(set_name)
        if not target:
            return self._active_bookmark_set_conn(conn)
        if self._bookmark_set_exists(conn, target):
            return target
        if create_if_missing:
            conn.execute("INSERT INTO user_bookmark_sets(name) VALUES(?)", (target,))
            return target
        return ""

    @staticmethod
    def _parse_cp(value: Any) -> int | None:
        if isinstance(value, int):
            return value if value >= 0 else None
        text = str(value or "").strip()
        if not text:
            return None
        if len(text) == 1:
            return ord(text)
        if text.lower().startswith("u+"):
            text = text[2:]
        try:
            return int(text, 16)
        except ValueError:
            return None

    def active_bookmark_set(self) -> str:
        conn = self._connect()
        try:
            return self._active_bookmark_set_conn(conn)
        finally:
            conn.close()

    def list_bookmark_sets(self, limit: int = 200) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT name
                FROM user_bookmark_sets
                ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END, updated_at DESC, name
                LIMIT ?
                """,
                (BOOKMARK_SET_DEFAULT, limit),
            ).fetchall()
            return [str(row[0]) for row in rows]
        finally:
            conn.close()

    def set_active_bookmark_set(self, name: str) -> bool:
        target = self._normalize_set_name(name)
        if not target:
            return False
        conn = self._connect()
        try:
            with conn:
                if not self._bookmark_set_exists(conn, target):
                    return False
                self._set_setting(conn, BOOKMARK_SET_ACTIVE_KEY, target)
                self._touch_bookmark_set(conn, target)
            return True
        finally:
            conn.close()

    def create_bookmark_set(self, name: str, make_active: bool = True) -> bool:
        target = self._normalize_set_name(name)
        if not target:
            return False
        conn = self._connect()
        try:
            with conn:
                if self._bookmark_set_exists(conn, target):
                    return False
                conn.execute("INSERT INTO user_bookmark_sets(name) VALUES(?)", (target,))
                if make_active:
                    self._set_setting(conn, BOOKMARK_SET_ACTIVE_KEY, target)
            return True
        finally:
            conn.close()

    def delete_bookmark_set(self, name: str) -> bool:
        target = self._normalize_set_name(name)
        if not target or target == BOOKMARK_SET_DEFAULT:
            return False
        conn = self._connect()
        try:
            with conn:
                if not self._bookmark_set_exists(conn, target):
                    return False
                active = self._active_bookmark_set_conn(conn)
                conn.execute("DELETE FROM user_bookmark_sets WHERE name = ?", (target,))
                if active == target:
                    fallback = conn.execute(
                        """
                        SELECT name
                        FROM user_bookmark_sets
                        ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END, updated_at DESC, name
                        LIMIT 1
                        """,
                        (BOOKMARK_SET_DEFAULT,),
                    ).fetchone()
                    if fallback is None:
                        conn.execute(
                            "INSERT OR IGNORE INTO user_bookmark_sets(name) VALUES(?)",
                            (BOOKMARK_SET_DEFAULT,),
                        )
                        next_set = BOOKMARK_SET_DEFAULT
                    else:
                        next_set = str(fallback[0])
                    self._set_setting(conn, BOOKMARK_SET_ACTIVE_KEY, next_set)
            return True
        finally:
            conn.close()

    def is_bookmarked(self, cp: int, set_name: str | None = None) -> bool:
        conn = self._connect()
        try:
            target = self._resolve_bookmark_set(conn, set_name)
            if not target:
                return False
            row = conn.execute(
                "SELECT 1 FROM user_bookmarks WHERE set_name = ? AND cp = ?",
                (target, cp),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def toggle_bookmark(self, cp: int, tag: str | None = None, set_name: str | None = None) -> bool:
        conn = self._connect()
        try:
            with conn:
                target = self._resolve_bookmark_set(conn, set_name, create_if_missing=True)
                row = conn.execute(
                    "SELECT 1 FROM user_bookmarks WHERE set_name = ? AND cp = ?",
                    (target, cp),
                ).fetchone()
                if row is not None:
                    conn.execute(
                        "DELETE FROM user_bookmarks WHERE set_name = ? AND cp = ?",
                        (target, cp),
                    )
                    self._touch_bookmark_set(conn, target)
                    return False
                conn.execute(
                    "INSERT INTO user_bookmarks(set_name, cp, tag) VALUES(?, ?, ?)",
                    (target, cp, tag),
                )
                self._touch_bookmark_set(conn, target)
                return True
        finally:
            conn.close()

    def delete_bookmark(self, cp: int, set_name: str | None = None) -> bool:
        conn = self._connect()
        try:
            with conn:
                target = self._resolve_bookmark_set(conn, set_name)
                if not target:
                    return False
                cur = conn.execute(
                    "DELETE FROM user_bookmarks WHERE set_name = ? AND cp = ?",
                    (target, cp),
                )
                if cur.rowcount > 0:
                    self._touch_bookmark_set(conn, target)
                    return True
                return False
        finally:
            conn.close()

    def list_bookmarks(self, limit: int = 200, set_name: str | None = None) -> list[tuple[int, str | None]]:
        conn = self._connect()
        try:
            target = self._resolve_bookmark_set(conn, set_name)
            if not target:
                return []
            rows = conn.execute(
                """
                SELECT cp, tag
                FROM user_bookmarks
                WHERE set_name = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (target, limit),
            ).fetchall()
            return [(int(row[0]), row[1]) for row in rows]
        finally:
            conn.close()

    def export_bookmark_set(self, out_path: Path, set_name: str | None = None) -> int:
        conn = self._connect()
        try:
            target = self._resolve_bookmark_set(conn, set_name)
            if not target:
                raise ValueError(f"Bookmark set not found: {set_name}")
            rows = conn.execute(
                """
                SELECT cp, tag, created_at
                FROM user_bookmarks
                WHERE set_name = ?
                ORDER BY created_at DESC, cp
                """,
                (target,),
            ).fetchall()
            payload = {
                "version": 1,
                "set_name": target,
                "bookmarks": [
                    {"cp": int(row[0]), "tag": row[1], "created_at": str(row[2])}
                    for row in rows
                ],
            }
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            return len(rows)
        finally:
            conn.close()

    def import_bookmark_set(
        self,
        in_path: Path,
        set_name: str | None = None,
        replace: bool = False,
        make_active: bool = True,
    ) -> tuple[str, int]:
        payload = json.loads(in_path.read_text(encoding="utf-8"))
        entries: list[dict[str, Any]]
        source_set = ""
        if isinstance(payload, dict):
            source_set = self._normalize_set_name(str(payload.get("set_name") or ""))
            raw_entries = payload.get("bookmarks", [])
            entries = [row for row in raw_entries if isinstance(row, dict)]
        elif isinstance(payload, list):
            entries = [row for row in payload if isinstance(row, dict)]
        else:
            entries = []

        target = self._normalize_set_name(set_name) or source_set or self._normalize_set_name(in_path.stem)
        if not target:
            target = BOOKMARK_SET_DEFAULT

        parsed: list[tuple[int, str | None]] = []
        for row in entries:
            cp = self._parse_cp(row.get("cp"))
            if cp is None:
                continue
            tag = row.get("tag")
            parsed.append((cp, str(tag) if tag is not None else None))

        conn = self._connect()
        try:
            with conn:
                if not self._bookmark_set_exists(conn, target):
                    conn.execute("INSERT INTO user_bookmark_sets(name) VALUES(?)", (target,))
                if replace:
                    conn.execute("DELETE FROM user_bookmarks WHERE set_name = ?", (target,))
                for cp, tag in parsed:
                    conn.execute(
                        """
                        INSERT INTO user_bookmarks(set_name, cp, tag)
                        VALUES(?, ?, ?)
                        ON CONFLICT(set_name, cp) DO UPDATE SET
                            tag=excluded.tag
                        """,
                        (target, cp, tag),
                    )
                self._touch_bookmark_set(conn, target)
                if make_active:
                    self._set_setting(conn, BOOKMARK_SET_ACTIVE_KEY, target)
            return target, len(parsed)
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
