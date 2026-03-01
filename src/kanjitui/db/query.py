from __future__ import annotations

import sqlite3
from pathlib import Path

from kanjitui.db.migrations import apply_migrations
from kanjitui.search.normalize import (
    contains_cjk,
    is_kana_text,
    looks_like_pinyin,
    looks_like_romaji,
    normalize_kana,
    normalize_pinyin_for_search,
    parse_codepoint_token,
    romaji_to_hiragana,
)


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    return conn


def get_ordered_cps(conn: sqlite3.Connection, ordering: str, focus: str = "jp") -> list[int]:
    if ordering == "freq":
        rows = conn.execute(
            "SELECT cp FROM chars ORDER BY (freq IS NULL), freq, cp"
        ).fetchall()
    elif ordering == "radical":
        rows = conn.execute(
            "SELECT cp FROM chars ORDER BY (radical IS NULL), radical, (strokes IS NULL), strokes, cp"
        ).fetchall()
    elif ordering == "reading":
        if focus == "cn":
            rows = conn.execute(
                """
                SELECT c.cp, COALESCE(MIN(cr.pinyin_numbered), '') AS key
                FROM chars c
                LEFT JOIN cn_readings cr ON cr.cp = c.cp
                GROUP BY c.cp
                ORDER BY key, c.cp
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT c.cp, COALESCE(MIN(jr.reading), '') AS key
                FROM chars c
                LEFT JOIN jp_readings jr ON jr.cp = c.cp
                GROUP BY c.cp
                ORDER BY key, c.cp
                """
            ).fetchall()
    else:
        rows = conn.execute("SELECT cp FROM chars ORDER BY cp").fetchall()
    return [int(row[0]) for row in rows]


def radical_counts(conn: sqlite3.Connection) -> list[tuple[int, int]]:
    rows = conn.execute(
        "SELECT radical, COUNT(*) FROM chars WHERE radical IS NOT NULL GROUP BY radical ORDER BY radical"
    ).fetchall()
    return [(int(rad), int(cnt)) for rad, cnt in rows]


def cps_by_radical(conn: sqlite3.Connection, radical: int) -> list[int]:
    rows = conn.execute(
        "SELECT cp FROM chars WHERE radical = ? ORDER BY (strokes IS NULL), strokes, cp",
        (radical,),
    ).fetchall()
    return [int(row[0]) for row in rows]


def get_char_detail(conn: sqlite3.Connection, cp: int) -> dict:
    char_row = conn.execute("SELECT * FROM chars WHERE cp = ?", (cp,)).fetchone()
    if char_row is None:
        raise KeyError(cp)

    jp_readings = conn.execute(
        "SELECT type, reading FROM jp_readings WHERE cp = ? ORDER BY rank, reading", (cp,)
    ).fetchall()
    jp_on = [row[1] for row in jp_readings if row[0] == "on"]
    jp_kun = [row[1] for row in jp_readings if row[0] == "kun"]

    jp_gloss = [
        row[0] for row in conn.execute("SELECT gloss FROM jp_gloss WHERE cp = ? ORDER BY gloss", (cp,)).fetchall()
    ]

    cn_readings = conn.execute(
        "SELECT pinyin_marked, pinyin_numbered FROM cn_readings WHERE cp = ? ORDER BY rank, pinyin_numbered",
        (cp,),
    ).fetchall()

    cn_gloss = [
        row[0] for row in conn.execute("SELECT gloss FROM cn_gloss WHERE cp = ? ORDER BY gloss", (cp,)).fetchall()
    ]

    variants = conn.execute(
        "SELECT kind, target_cp, note FROM variants WHERE cp = ? ORDER BY kind, target_cp", (cp,)
    ).fetchall()

    jp_words = conn.execute(
        "SELECT word, reading_kana, gloss_en, rank FROM jp_words WHERE cp = ? ORDER BY rank", (cp,)
    ).fetchall()
    cn_words = conn.execute(
        "SELECT trad, simp, pinyin_marked, pinyin_numbered, gloss_en, rank FROM cn_words WHERE cp = ? ORDER BY rank",
        (cp,),
    ).fetchall()

    return {
        "cp": int(char_row["cp"]),
        "ch": char_row["ch"],
        "radical": char_row["radical"],
        "strokes": char_row["strokes"],
        "freq": char_row["freq"],
        "sources": char_row["sources"],
        "jp_on": jp_on,
        "jp_kun": jp_kun,
        "jp_gloss": jp_gloss,
        "cn_readings": [tuple(row) for row in cn_readings],
        "cn_gloss": cn_gloss,
        "variants": [tuple(row) for row in variants],
        "jp_words": [tuple(row) for row in jp_words],
        "cn_words": [tuple(row) for row in cn_words],
    }


def _search_char_exact(conn: sqlite3.Connection, token: str, limit: int) -> list[dict]:
    cps = sorted({ord(ch) for ch in token if contains_cjk(ch)})
    if not cps:
        return []
    placeholders = ",".join("?" for _ in cps)
    rows = conn.execute(
        f"SELECT cp FROM chars WHERE cp IN ({placeholders}) ORDER BY cp LIMIT ?",
        (*cps, limit),
    ).fetchall()
    return [preview_row(conn, int(row[0])) for row in rows]


def preview_row(conn: sqlite3.Connection, cp: int) -> dict:
    row = conn.execute("SELECT ch FROM chars WHERE cp = ?", (cp,)).fetchone()
    if row is None:
        raise KeyError(cp)

    jp = conn.execute(
        "SELECT reading FROM jp_readings WHERE cp = ? ORDER BY rank, reading LIMIT 1", (cp,)
    ).fetchone()
    cn = conn.execute(
        "SELECT pinyin_numbered FROM cn_readings WHERE cp = ? ORDER BY rank, pinyin_numbered LIMIT 1", (cp,)
    ).fetchone()

    gloss = conn.execute(
        """
        SELECT gloss FROM (
            SELECT gloss FROM jp_gloss WHERE cp = ?
            UNION ALL
            SELECT gloss FROM cn_gloss WHERE cp = ?
        ) LIMIT 1
        """,
        (cp, cp),
    ).fetchone()

    return {
        "cp": cp,
        "ch": row[0],
        "jp": jp[0] if jp else "",
        "cn": cn[0] if cn else "",
        "gloss": gloss[0] if gloss else "",
    }


def _search_sql(conn: sqlite3.Connection, sql: str, args: tuple, limit: int) -> list[dict]:
    rows = conn.execute(sql, (*args, limit)).fetchall()
    return [preview_row(conn, int(row[0])) for row in rows]


def search(conn: sqlite3.Connection, query: str, limit: int = 200) -> list[dict]:
    token = query.strip()
    if not token:
        return []

    if contains_cjk(token):
        return _search_char_exact(conn, token, limit)

    cp = parse_codepoint_token(token)
    if cp is not None:
        rows = conn.execute("SELECT cp FROM chars WHERE cp = ? LIMIT ?", (cp, limit)).fetchall()
        return [preview_row(conn, int(row[0])) for row in rows]

    if is_kana_text(token):
        kana = normalize_kana(token)
        like = f"%{kana}%"
        return _search_sql(
            conn,
            """
            SELECT DISTINCT c.cp
            FROM chars c
            JOIN search_index s ON s.cp = c.cp
            WHERE s.jp_keys LIKE ?
            ORDER BY c.cp
            LIMIT ?
            """,
            (like,),
            limit,
        )

    if looks_like_romaji(token):
        kana = normalize_kana(romaji_to_hiragana(token))
        like = f"%{kana}%"
        return _search_sql(
            conn,
            """
            SELECT DISTINCT c.cp
            FROM chars c
            JOIN search_index s ON s.cp = c.cp
            WHERE s.jp_keys LIKE ?
            ORDER BY c.cp
            LIMIT ?
            """,
            (like,),
            limit,
        )

    if looks_like_pinyin(token):
        num = normalize_pinyin_for_search(token)
        like = f"%{num}%"
        return _search_sql(
            conn,
            """
            SELECT DISTINCT c.cp
            FROM chars c
            LEFT JOIN cn_readings cr ON cr.cp = c.cp
            LEFT JOIN cn_words cw ON cw.cp = c.cp
            WHERE cr.pinyin_numbered LIKE ?
               OR cw.pinyin_numbered LIKE ?
               OR cw.trad LIKE ?
               OR cw.simp LIKE ?
            ORDER BY c.cp
            LIMIT ?
            """,
            (like, like, like, like),
            limit,
        )

    like = f"%{token.lower()}%"
    return _search_sql(
        conn,
        """
        SELECT DISTINCT c.cp
        FROM chars c
        JOIN search_index s ON s.cp = c.cp
        WHERE s.gloss_keys LIKE ? OR s.jp_keys LIKE ? OR s.cn_keys LIKE ?
        ORDER BY c.cp
        LIMIT ?
        """,
        (like, like, like),
        limit,
    )
