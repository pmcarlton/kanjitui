from __future__ import annotations

import argparse
from pathlib import Path

from kanjitui.config import resolve_app_config, resolve_build_paths


def _args(**overrides: object) -> argparse.Namespace:
    defaults = {
        "config": None,
        "db": None,
        "user_db": None,
        "build": None,
        "data_dir": None,
        "font": None,
        "providers": None,
        "normalizer": None,
        "font_profile_out": None,
        "build_report_out": None,
        "unihan_dir": None,
        "kanjidic2": None,
        "jmdict": None,
        "cedict": None,
        "sentences": None,
        "no_font_filter": None,
        "verbose": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_resolve_app_config_precedence(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "kanjitui.toml"
    config_path.write_text(
        """
[app]
db = "from_file.sqlite"

[build]
enabled = true
providers = ["unihan", "cedict"]
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("KANJITUI_DB", "from_env.sqlite")
    cfg = resolve_app_config(_args(config=str(config_path), db="from_cli.sqlite"))

    assert cfg.db_path == Path("from_cli.sqlite")
    assert cfg.build is True
    assert cfg.providers == ("unihan", "cedict")


def test_resolve_build_paths_uses_data_dir_defaults(tmp_path: Path) -> None:
    (tmp_path / "unihan").mkdir()
    cfg = resolve_app_config(_args(data_dir=str(tmp_path)))
    paths = resolve_build_paths(cfg)

    assert paths.unihan_dir == tmp_path / "unihan"
    assert paths.kanjidic2_xml == tmp_path / "kanjidic2.xml"
    assert paths.jmdict_xml == tmp_path / "jmdict.xml"
    assert paths.cedict_txt == tmp_path / "cedict_ts.u8"
    assert paths.sentences_tsv == tmp_path / "sentences.tsv"


def test_providers_cli_parses_csv() -> None:
    cfg = resolve_app_config(_args(providers="unihan,cedict"))
    assert cfg.providers == ("unihan", "cedict")


def test_normalizer_default_is_set() -> None:
    cfg = resolve_app_config(_args())
    assert cfg.normalizer == "default"
