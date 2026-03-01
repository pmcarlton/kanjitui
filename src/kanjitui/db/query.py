from __future__ import annotations

import sqlite3
from pathlib import Path

from kanjitui.db.migrations import apply_migrations
from kanjitui.search.normalizer import NormalizerPlugin, get_normalizer


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    return conn


def available_frequency_profiles(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT profile FROM frequency_scores ORDER BY profile").fetchall()
    return [str(row[0]) for row in rows]


def get_ordered_cps(
    conn: sqlite3.Connection,
    ordering: str,
    focus: str = "jp",
    freq_profile: str | None = None,
) -> list[int]:
    if ordering == "freq":
        if freq_profile:
            # Fast path: fetch ranked profile chars first, then append remaining chars.
            # A single LEFT JOIN + ORDER BY on expressions is significantly slower on large DBs.
            prof_rows = conn.execute(
                "SELECT cp FROM frequency_scores WHERE profile = ? ORDER BY rank, cp",
                (freq_profile,),
            ).fetchall()
            first = [int(row[0]) for row in prof_rows]
            seen = set(first)
            base_rows = conn.execute(
                "SELECT cp FROM chars ORDER BY (freq IS NULL), freq, cp"
            ).fetchall()
            second = [int(row[0]) for row in base_rows if int(row[0]) not in seen]
            return first + second
        else:
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


def stroke_options_by_radical(conn: sqlite3.Connection, radical: int) -> list[int]:
    rows = conn.execute(
        "SELECT DISTINCT strokes FROM chars WHERE radical = ? AND strokes IS NOT NULL ORDER BY strokes",
        (radical,),
    ).fetchall()
    return [int(row[0]) for row in rows]


def cps_by_radical(conn: sqlite3.Connection, radical: int, stroke_filter: int | None = None) -> list[int]:
    if stroke_filter is None:
        rows = conn.execute(
            "SELECT cp FROM chars WHERE radical = ? ORDER BY (strokes IS NULL), strokes, cp",
            (radical,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT cp FROM chars WHERE radical = ? AND strokes = ? ORDER BY cp",
            (radical, stroke_filter),
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


def get_components(conn: sqlite3.Connection, cp: int) -> list[tuple[int, str]]:
    rows = conn.execute(
        """
        SELECT cmp.component_cp, COALESCE(c2.ch, '')
        FROM components cmp
        LEFT JOIN chars c2 ON c2.cp = cmp.component_cp
        WHERE cmp.cp = ?
        ORDER BY cmp.component_cp
        """,
        (cp,),
    ).fetchall()
    return [(int(row[0]), row[1] or chr(int(row[0]))) for row in rows]


def get_phonetic_series(conn: sqlite3.Connection, cp: int, limit: int = 80) -> list[tuple[int, str, str]]:
    series_rows = conn.execute(
        "SELECT DISTINCT series_key FROM phonetic_series WHERE cp = ? LIMIT 4",
        (cp,),
    ).fetchall()
    keys = [str(row[0]) for row in series_rows]
    if not keys:
        own_key = f"U+{cp:04X}"
        keys_rows = conn.execute(
            "SELECT DISTINCT series_key FROM phonetic_series WHERE series_key = ? LIMIT 1",
            (own_key,),
        ).fetchall()
        keys = [str(row[0]) for row in keys_rows]
    if not keys:
        return []
    placeholders = ",".join("?" for _ in keys)
    rows = conn.execute(
        f"""
        SELECT ps.cp, COALESCE(c.ch, ''), ps.series_key
        FROM phonetic_series ps
        LEFT JOIN chars c ON c.cp = ps.cp
        WHERE ps.series_key IN ({placeholders})
        ORDER BY ps.series_key, ps.cp
        LIMIT ?
        """,
        (*keys, limit),
    ).fetchall()
    return [(int(row[0]), row[1] or chr(int(row[0])), str(row[2])) for row in rows]


def get_sentences(conn: sqlite3.Connection, cp: int, limit: int = 5) -> list[tuple]:
    rows = conn.execute(
        """
        SELECT lang, text, reading, gloss, source, license, rank
        FROM sentences
        WHERE cp = ?
        ORDER BY lang, rank
        LIMIT ?
        """,
        (cp, limit),
    ).fetchall()
    return [tuple(row) for row in rows]


def derived_data_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = ["field_provenance", "phonetic_series", "sentences", "components", "frequency_scores"]
    counts: dict[str, int] = {}
    for table in tables:
        rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        counts[table] = int(rows[0]) if rows is not None else 0
    return counts


def _search_char_exact(conn: sqlite3.Connection, token: str, limit: int, normalizer: NormalizerPlugin) -> list[dict]:
    cps = sorted({ord(ch) for ch in token if normalizer.contains_cjk(ch)})
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


def search(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 200,
    normalizer: NormalizerPlugin | None = None,
) -> list[dict]:
    plugin = normalizer or get_normalizer("default")
    token = query.strip()
    if not token:
        return []

    if plugin.contains_cjk(token):
        return _search_char_exact(conn, token, limit, plugin)

    cp = plugin.parse_codepoint_token(token)
    if cp is not None:
        rows = conn.execute("SELECT cp FROM chars WHERE cp = ? LIMIT ?", (cp, limit)).fetchall()
        return [preview_row(conn, int(row[0])) for row in rows]

    if plugin.is_kana_text(token):
        kana = plugin.normalize_kana(token)
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

    if plugin.looks_like_romaji(token):
        kana = plugin.normalize_kana(plugin.romaji_to_hiragana(token))
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

    if plugin.looks_like_pinyin(token):
        num = plugin.normalize_pinyin_for_search(token)
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


def get_provenance(conn: sqlite3.Connection, cp: int, limit: int = 80) -> list[tuple]:
    rows = conn.execute(
        """
        SELECT field, value, source, confidence
        FROM field_provenance
        WHERE cp = ?
        ORDER BY field, source, value
        LIMIT ?
        """,
        (cp, limit),
    ).fetchall()
    return [tuple(row) for row in rows]


def variant_graph(conn: sqlite3.Connection, cp: int, depth: int = 2, max_nodes: int = 64) -> dict:
    seen: set[int] = {cp}
    frontier = [cp]
    edges: list[tuple[int, str, int]] = []
    level = 0
    while frontier and level < max(depth, 1):
        next_frontier: list[int] = []
        for node in frontier:
            rows = conn.execute(
                "SELECT cp, kind, target_cp FROM variants WHERE cp = ? OR target_cp = ?",
                (node, node),
            ).fetchall()
            for a, kind, b in rows:
                src = int(a)
                dst = int(b)
                edges.append((src, kind, dst))
                for candidate in (src, dst):
                    if candidate not in seen and len(seen) < max_nodes:
                        seen.add(candidate)
                        next_frontier.append(candidate)
        frontier = next_frontier
        level += 1

    node_rows = conn.execute(
        f"SELECT cp, ch FROM chars WHERE cp IN ({','.join('?' for _ in seen)}) ORDER BY cp",
        tuple(sorted(seen)),
    ).fetchall()
    nodes = [(int(row[0]), row[1]) for row in node_rows]
    return {"nodes": nodes, "edges": sorted(set(edges))}
