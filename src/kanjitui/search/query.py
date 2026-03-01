from __future__ import annotations

import sqlite3

from kanjitui.db import query as db_query
from kanjitui.search.normalizer import get_normalizer


class SearchEngine:
    def __init__(self, conn: sqlite3.Connection, normalizer_name: str = "default") -> None:
        self._conn = conn
        self._normalizer = get_normalizer(normalizer_name)

    def run(self, text: str, limit: int = 200) -> list[dict]:
        return db_query.search(self._conn, text, limit=limit, normalizer=self._normalizer)
