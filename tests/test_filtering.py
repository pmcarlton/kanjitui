from __future__ import annotations

from pathlib import Path

from kanjitui.db.build import BuildConfig, BuildPaths, build_database
from kanjitui.db.query import connect, load_filter_data
from kanjitui.filtering import FilterState, apply_filter_state


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


def test_apply_filter_state_by_reading_and_variants(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        ordered = [int(row[0]) for row in conn.execute("SELECT cp FROM chars ORDER BY cp").fetchall()]
        data = load_filter_data(conn)
        jp_only = FilterState(reading_availability="jp")
        res_jp = apply_filter_state(ordered, jp_only, data)
        assert res_jp
        assert all(cp in data.jp_cps for cp in res_jp)

        no_variant = FilterState(variant_class="none")
        res_none = apply_filter_state(ordered, no_variant, data)
        assert res_none
        assert all(cp not in data.any_variant_cps for cp in res_none)
    finally:
        conn.close()


def test_apply_filter_state_frequency_unranked(tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    conn = connect(db_path)
    try:
        ordered = [int(row[0]) for row in conn.execute("SELECT cp FROM chars ORDER BY cp").fetchall()]
        data = load_filter_data(conn)
        state = FilterState(frequency_profile="jp_kanjidic", frequency_band="unranked")
        result = apply_filter_state(ordered, state, data, default_frequency_profile="jp_kanjidic")
        assert result
        ranks = data.frequency_ranks.get("jp_kanjidic", {})
        assert all(cp not in ranks for cp in result)
    finally:
        conn.close()
