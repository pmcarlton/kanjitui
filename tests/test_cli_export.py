from __future__ import annotations

from pathlib import Path

from kanjitui.cli import main
from kanjitui.db.build import BuildConfig, BuildPaths, build_database


def _build_fixture_db(tmp_path: Path) -> Path:
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
    )
    build_database(config)
    return db_path


def test_export_query_json(capsys, tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    code = main(["--db", str(db_path), "--export-query", "han4", "--export-format", "json"])
    assert code == 0
    out = capsys.readouterr().out
    assert "\"cp\"" in out


def test_export_char_csv(capsys, tmp_path: Path) -> None:
    db_path = _build_fixture_db(tmp_path)
    code = main(["--db", str(db_path), "--export-char", "U+6F22", "--export-format", "csv"])
    assert code == 0
    out = capsys.readouterr().out
    assert "field,value" in out
    assert "jp_on" in out
