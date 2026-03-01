from __future__ import annotations

from pathlib import Path

from kanjitui.db import query as db_query
from kanjitui.db.build import BuildConfig, BuildPaths, build_database
from kanjitui.db.query import connect


def _build_fixture_db(tmp_path: Path) -> Path:
    fixtures = Path(__file__).parent / "fixtures"
    db_path = tmp_path / "db.sqlite"
    build_database(
        BuildConfig(
            db_path=db_path,
            paths=BuildPaths(
                unihan_dir=fixtures / "unihan",
                kanjidic2_xml=fixtures / "kanjidic2.xml",
                jmdict_xml=fixtures / "jmdict.xml",
                cedict_txt=fixtures / "cedict_ts.u8",
                sentences_tsv=fixtures / "sentences.tsv",
            ),
            font=None,
            enabled_providers=("unihan", "kanjidic2", "jmdict", "cedict", "sentences"),
        )
    )
    return db_path


def test_get_sentences_can_filter_by_language_scope(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        cp_row = conn.execute(
            """
            SELECT cp
            FROM sentences
            GROUP BY cp
            HAVING COUNT(DISTINCT lang) >= 2
            LIMIT 1
            """
        ).fetchone()
        assert cp_row is not None
        cp = int(cp_row[0])

        both = db_query.get_sentences(conn, cp, limit=8, langs=("jp", "cn"))
        assert both
        langs_both = {row[0] for row in both}
        assert "jp" in langs_both
        assert "cn" in langs_both

        only_jp = db_query.get_sentences(conn, cp, limit=8, langs=("jp",))
        assert only_jp
        assert {row[0] for row in only_jp} == {"jp"}

        only_cn = db_query.get_sentences(conn, cp, limit=8, langs=("cn",))
        assert only_cn
        assert {row[0] for row in only_cn} == {"cn"}
    finally:
        conn.close()
