from pathlib import Path

from kanjitui.db.build import BuildConfig, BuildPaths, build_database
from kanjitui.db.query import connect, get_char_detail, search


def test_build_and_query_roundtrip(tmp_path: Path) -> None:
    fixtures = Path(__file__).parent / "fixtures"
    db_path = tmp_path / "db.sqlite"

    config = BuildConfig(
        db_path=db_path,
        paths=BuildPaths(
            unihan_dir=fixtures / "unihan",
            kanjidic2_xml=fixtures / "kanjidic2.xml",
            jmdict_xml=fixtures / "jmdict.xml",
            cedict_txt=fixtures / "cedict_ts.u8",
        ),
        font=None,
        build_report_out=tmp_path / "build_report.json",
    )
    counts = build_database(config)

    assert counts["included"] >= 2
    conn = connect(db_path)
    try:
        detail = get_char_detail(conn, 0x6F22)
        assert detail["ch"] == "漢"
        assert any(r[1] == "han4" for r in detail["cn_readings"])
        assert len(detail["jp_words"]) >= 1

        results = search(conn, "han4")
        assert any(row["cp"] == 0x6F22 for row in results)

        results = search(conn, "U+5B57")
        assert any(row["cp"] == 0x5B57 for row in results)

        results = search(conn, "kanji")
        assert any(row["cp"] == 0x6F22 for row in results)
    finally:
        conn.close()
