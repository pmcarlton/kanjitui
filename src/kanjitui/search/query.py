from __future__ import annotations

import sqlite3

from kanjitui.db import query as db_query


class SearchEngine:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def run(self, text: str, limit: int = 200) -> list[dict]:
        return db_query.search(self._conn, text, limit=limit)
