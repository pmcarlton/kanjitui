from pathlib import Path

from kanjitui.db.build import BuildConfig, BuildPaths, build_database
from kanjitui.db.query import connect, get_char_detail, get_provenance, search, variant_graph
from kanjitui.db.query import (
    available_frequency_profiles,
    derived_data_counts,
    get_components,
    get_sentences,
    stroke_options_by_radical,
)
from kanjitui.search.normalizer import get_normalizer


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

        strict_results = search(conn, "kanji", normalizer=get_normalizer("strict"))
        assert any(row["cp"] == 0x6F22 for row in strict_results)

        provenance = get_provenance(conn, 0x6F22)
        assert any(row[0] == "jp_on" and row[2] in {"unihan", "kanjidic2"} for row in provenance)

        graph = variant_graph(conn, 0x6C49, depth=2)
        assert any(edge[2] == 0x6F22 for edge in graph["edges"])

        profiles = available_frequency_profiles(conn)
        assert "jp_kanjidic" in profiles
        assert "cn_cedict" in profiles

        stroke_opts = stroke_options_by_radical(conn, 85)
        assert 13 in stroke_opts

        components = get_components(conn, 0x6F22)
        assert isinstance(components, list)
        assert len(components) >= 1

        derived = derived_data_counts(conn)
        assert derived["field_provenance"] > 0
    finally:
        conn.close()


def test_build_with_optional_sentences_provider(tmp_path: Path) -> None:
    fixtures = Path(__file__).parent / "fixtures"
    db_path = tmp_path / "db_sentences.sqlite"

    config = BuildConfig(
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
    build_database(config)

    conn = connect(db_path)
    try:
        rows = get_sentences(conn, 0x6F22, limit=5)
        assert len(rows) >= 2
        assert any(row[0] == "jp" for row in rows)
    finally:
        conn.close()


def test_build_reports_when_font_filter_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    fixtures = Path(__file__).parent / "fixtures"
    db_path = tmp_path / "db_font.sqlite"
    logs: list[str] = []

    config = BuildConfig(
        db_path=db_path,
        paths=BuildPaths(
            unihan_dir=fixtures / "unihan",
            kanjidic2_xml=fixtures / "kanjidic2.xml",
            jmdict_xml=fixtures / "jmdict.xml",
            cedict_txt=fixtures / "cedict_ts.u8",
        ),
        font="Missing Font Family",
    )
    monkeypatch.setattr("kanjitui.db.build.compute_font_coverage", lambda _font: None)
    counts = build_database(config, progress=logs.append)

    assert counts["included"] >= 2
    assert any("Font coverage unavailable" in line for line in logs)
