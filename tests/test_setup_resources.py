from __future__ import annotations

from pathlib import Path

from kanjitui.setup_resources import (
    acknowledgements_for_sources,
    build_enabled_providers,
    default_setup_selection,
    detect_available_sources,
    RuntimePaths,
    SOURCES,
)


def test_detect_available_sources_and_defaults(tmp_path: Path) -> None:
    paths = RuntimePaths(
        data_dir=tmp_path / "raw",
        strokeorder_dir=tmp_path / "strokeorder",
        tatoeba_dir=tmp_path / "raw" / "tatoeba",
    )
    paths.data_dir.mkdir(parents=True)
    (paths.data_dir / "unihan").mkdir(parents=True)
    (paths.data_dir / "unihan" / "Unihan_Readings.txt").write_text("x", encoding="utf-8")
    (paths.data_dir / "cedict_ts.u8").write_text("x", encoding="utf-8")
    (paths.strokeorder_dir / "kanji").mkdir(parents=True)

    presence = detect_available_sources(paths)
    assert presence["unihan"] is True
    assert presence["cedict"] is True
    assert presence["strokeorder"] is True
    assert presence["kanjidic2"] is False
    assert presence["jmdict"] is False
    assert presence["sentences"] is False

    defaults = default_setup_selection(presence)
    assert "kanjidic2" in defaults
    assert "jmdict" in defaults
    assert "sentences" in defaults
    assert "unihan" not in defaults


def test_acknowledgements_include_edrdg_line() -> None:
    lines = acknowledgements_for_sources(
        {
            "unihan": False,
            "cedict": False,
            "kanjidic2": True,
            "jmdict": False,
            "sentences": False,
            "strokeorder": False,
        }
    )
    joined = "\n".join(lines)
    assert "JMdict/EDICT and KANJIDIC dictionary files" in joined
    assert "Electronic Dictionary Research and Development Group" in joined


def test_all_sources_have_license_links() -> None:
    for spec in SOURCES.values():
        assert spec.license_url.startswith("http")
        assert spec.license_label.strip()


def test_build_enabled_providers_order_and_filter() -> None:
    providers = build_enabled_providers(
        {
            "unihan": True,
            "cedict": True,
            "kanjidic2": False,
            "jmdict": True,
            "sentences": True,
            "strokeorder": True,
        }
    )
    assert providers == ("unihan", "jmdict", "cedict", "sentences")
