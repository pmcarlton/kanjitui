from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from kanjitui.db.migrations import apply_migrations
from kanjitui.filtering import FilterData
from kanjitui.providers.kanjidic2 import parse_kanjidic2
from kanjitui.search import normalize as search_normalize
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


def reading_cp_sets(conn: sqlite3.Connection) -> tuple[set[int], set[int]]:
    jp_rows = conn.execute("SELECT DISTINCT cp FROM jp_readings").fetchall()
    cn_rows = conn.execute("SELECT DISTINCT cp FROM cn_readings").fetchall()
    jp = {int(row[0]) for row in jp_rows}
    cn = {int(row[0]) for row in cn_rows}
    return (jp, cn)


def _kanjidic2_fallback_paths() -> list[Path]:
    candidates: list[Path] = []
    env_kanjidic2 = os.environ.get("KANJITUI_KANJIDIC2", "").strip()
    if env_kanjidic2:
        candidates.append(Path(env_kanjidic2).expanduser())
    env_data = os.environ.get("KANJITUI_DATA_DIR", "").strip()
    if env_data:
        candidates.append(Path(env_data).expanduser() / "kanjidic2.xml")
    candidates.append(Path("data/raw/kanjidic2.xml"))
    dedup: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(path)
    return dedup


def load_filter_data(conn: sqlite3.Connection) -> FilterData:
    data = FilterData()
    raw_is_simplified: set[int] = set()
    raw_is_traditional: set[int] = set()
    rows = conn.execute("SELECT cp, strokes, sources FROM chars").fetchall()
    for row in rows:
        cp = int(row[0])
        data.all_cps.add(cp)
        data.strokes_by_cp[cp] = int(row[1]) if row[1] is not None else None
        source_text = str(row[2] or "")
        source_set = {part.strip() for part in source_text.split(",") if part.strip()}
        if "unihan" in source_set:
            data.source_unihan_cps.add(cp)
        if "kanjidic2" in source_set:
            data.source_kanjidic2_cps.add(cp)
        if "cedict" in source_set:
            data.source_cedict_cps.add(cp)

    jp_rows = conn.execute("SELECT cp, type FROM jp_readings").fetchall()
    for row in jp_rows:
        cp = int(row[0])
        data.jp_cps.add(cp)
        typ = str(row[1] or "")
        if typ == "on":
            data.jp_on_cps.add(cp)
        elif typ == "kun":
            data.jp_kun_cps.add(cp)

    cn_rows = conn.execute(
        "SELECT cp, COUNT(DISTINCT pinyin_numbered) FROM cn_readings GROUP BY cp"
    ).fetchall()
    for cp, cnt in cn_rows:
        icp = int(cp)
        data.cn_cps.add(icp)
        if int(cnt) > 1:
            data.cn_multi_cps.add(icp)

    var_rows = conn.execute("SELECT cp, kind, target_cp FROM variants").fetchall()
    for row in var_rows:
        cp = int(row[0])
        kind = str(row[1] or "")
        target = int(row[2])
        data.any_variant_cps.add(cp)
        data.any_variant_cps.add(target)
        if kind == "simplified":
            raw_is_traditional.add(cp)
            raw_is_simplified.add(target)
        if kind == "traditional":
            raw_is_simplified.add(cp)
            raw_is_traditional.add(target)
        if kind in {"semantic", "specialized"}:
            data.variant_semantic_cps.add(cp)
        if kind == "compat":
            data.variant_compat_cps.add(cp)
    data.variant_is_simplified_cps = raw_is_simplified - raw_is_traditional
    data.variant_is_traditional_cps = raw_is_traditional - raw_is_simplified

    data.components_cps = {int(row[0]) for row in conn.execute("SELECT DISTINCT cp FROM components").fetchall()}
    data.phonetic_cps = {int(row[0]) for row in conn.execute("SELECT DISTINCT cp FROM phonetic_series").fetchall()}
    data.provenance_cps = {
        int(row[0]) for row in conn.execute("SELECT DISTINCT cp FROM field_provenance").fetchall()
    }
    data.sentences_cps = {int(row[0]) for row in conn.execute("SELECT DISTINCT cp FROM sentences").fetchall()}

    freq_rows = conn.execute("SELECT profile, cp, rank FROM frequency_scores").fetchall()
    for profile, cp, rank in freq_rows:
        p = str(profile)
        ranks = data.frequency_ranks.setdefault(p, {})
        ranks[int(cp)] = int(rank)

    words_rows = conn.execute(
        """
        SELECT DISTINCT cp FROM (
            SELECT cp FROM jp_words
            UNION
            SELECT cp FROM cn_words
        )
        """
    ).fetchall()
    data.has_words_cps = {int(row[0]) for row in words_rows}

    grade_rows = conn.execute(
        "SELECT cp, value FROM field_provenance WHERE field = 'jp_grade' AND source = 'kanjidic2'"
    ).fetchall()
    for cp, value in grade_rows:
        try:
            grade = int(str(value))
        except (TypeError, ValueError):
            continue
        icp = int(cp)
        if grade in {1, 2, 3, 4, 5, 6, 8}:
            data.joyo_cps.add(icp)
        if grade in {1, 2, 3, 4, 5, 6}:
            data.kyoiku_cps.add(icp)
        if grade in {9, 10}:
            data.jinmeiyo_cps.add(icp)

    if not data.joyo_cps and data.source_kanjidic2_cps:
        for path in _kanjidic2_fallback_paths():
            if not path.exists():
                continue
            try:
                parsed = parse_kanjidic2(path)
            except Exception:
                continue
            for cp, record in parsed.items():
                if cp not in data.all_cps:
                    continue
                grade = record.jp_grade
                if grade is None:
                    continue
                if grade in {1, 2, 3, 4, 5, 6, 8}:
                    data.joyo_cps.add(cp)
                if grade in {1, 2, 3, 4, 5, 6}:
                    data.kyoiku_cps.add(cp)
                if grade in {9, 10}:
                    data.jinmeiyo_cps.add(cp)
            if data.joyo_cps:
                break
    return data


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


def get_phonetic_series(conn: sqlite3.Connection, cp: int, limit: int = 80) -> list[tuple[int, str, str, str, str]]:
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
        SELECT
            ps.cp,
            COALESCE(c.ch, ''),
            ps.series_key,
            COALESCE(
                (
                    SELECT cr.pinyin_marked
                    FROM cn_readings cr
                    WHERE cr.cp = ps.cp AND cr.pinyin_marked != ''
                    ORDER BY cr.rank, cr.pinyin_numbered
                    LIMIT 1
                ),
                ''
            ) AS pinyin_marked,
            COALESCE(
                (
                    SELECT cr.pinyin_numbered
                    FROM cn_readings cr
                    WHERE cr.cp = ps.cp AND cr.pinyin_numbered != ''
                    ORDER BY cr.rank, cr.pinyin_numbered
                    LIMIT 1
                ),
                ''
            ) AS pinyin_numbered
        FROM phonetic_series ps
        LEFT JOIN chars c ON c.cp = ps.cp
        WHERE ps.series_key IN ({placeholders})
        ORDER BY ps.series_key, ps.cp
        LIMIT ?
        """,
        (*keys, limit),
    ).fetchall()
    return [
        (
            int(row[0]),
            row[1] or chr(int(row[0])),
            str(row[2]),
            str(row[3] or ""),
            str(row[4] or ""),
        )
        for row in rows
    ]


def get_sentences(
    conn: sqlite3.Connection,
    cp: int,
    limit: int = 5,
    langs: tuple[str, ...] | None = None,
) -> list[tuple]:
    if langs:
        placeholders = ",".join("?" for _ in langs)
        rows = conn.execute(
            f"""
            SELECT lang, text, reading, gloss, source, license, rank
            FROM sentences
            WHERE cp = ? AND lang IN ({placeholders})
            ORDER BY rank, lang
            LIMIT ?
            """,
            (cp, *langs, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT lang, text, reading, gloss, source, license, rank
            FROM sentences
            WHERE cp = ?
            ORDER BY rank, lang
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
        "SELECT pinyin_marked, pinyin_numbered FROM cn_readings WHERE cp = ? ORDER BY rank, pinyin_numbered LIMIT 1",
        (cp,),
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
        "cn": (
            (cn[0] or search_normalize.pinyin_numbered_to_marked(cn[1] or ""))
            if cn
            else ""
        ),
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
