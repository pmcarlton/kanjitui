from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tomllib
from typing import Any


DEFAULT_PROVIDERS: tuple[str, ...] = ("unihan", "kanjidic2", "jmdict", "cedict")


@dataclass(frozen=True)
class AppConfig:
    db_path: Path
    user_db_path: Path
    build: bool
    data_dir: Path
    font: str
    font_profile_out: Path
    build_report_out: Path
    unihan_dir: Path | None
    kanjidic2_xml: Path | None
    jmdict_xml: Path | None
    cedict_txt: Path | None
    providers: tuple[str, ...]
    normalizer: str
    no_font_filter: bool
    verbose: bool
    config_path: Path | None


@dataclass(frozen=True)
class BuildSourcePaths:
    unihan_dir: Path
    kanjidic2_xml: Path
    jmdict_xml: Path
    cedict_txt: Path


class ConfigError(ValueError):
    pass


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ConfigError(f"Invalid boolean value: {value!r}")


def _parse_providers(value: Any) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_PROVIDERS

    raw_items: list[str]
    if isinstance(value, str):
        raw_items = [chunk.strip() for chunk in value.split(",")]
    elif isinstance(value, list):
        raw_items = [str(chunk).strip() for chunk in value]
    else:
        raise ConfigError("providers must be a comma-separated string or list")

    dedup: list[str] = []
    for item in raw_items:
        if not item:
            continue
        if item not in dedup:
            dedup.append(item)

    if not dedup:
        raise ConfigError("providers cannot be empty")

    return tuple(dedup)


def _load_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _get_nested(data: dict[str, Any], *keys: str) -> Any:
    node: Any = data
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _resolve_value(
    *,
    cli: Any,
    env: str | None,
    file_value: Any,
    default: Any,
    parser: Any = None,
) -> Any:
    if cli is not None:
        return parser(cli) if parser else cli

    if env:
        env_value = os.environ.get(env)
        if env_value is not None:
            return parser(env_value) if parser else env_value

    if file_value is not None:
        return parser(file_value) if parser else file_value

    return default


def resolve_app_config(args: Any) -> AppConfig:
    config_path_raw = args.config if args.config is not None else os.environ.get("KANJITUI_CONFIG")
    config_path = Path(config_path_raw) if config_path_raw else None
    file_data: dict[str, Any] = {}
    if config_path is not None:
        file_data = _load_config_file(config_path)

    build_section = _get_nested(file_data, "build") or {}
    app_section = _get_nested(file_data, "app") or {}

    db_path = Path(
        _resolve_value(
            cli=args.db,
            env="KANJITUI_DB",
            file_value=app_section.get("db"),
            default="data/db.sqlite",
        )
    )
    user_db_path = Path(
        _resolve_value(
            cli=args.user_db,
            env="KANJITUI_USER_DB",
            file_value=app_section.get("user_db"),
            default="data/user.sqlite",
        )
    )

    build = bool(
        _resolve_value(
            cli=args.build,
            env="KANJITUI_BUILD",
            file_value=build_section.get("enabled"),
            default=False,
            parser=_parse_bool,
        )
    )

    data_dir = Path(
        _resolve_value(
            cli=args.data_dir,
            env="KANJITUI_DATA_DIR",
            file_value=build_section.get("data_dir"),
            default="data/raw",
        )
    )

    font = str(
        _resolve_value(
            cli=args.font,
            env="KANJITUI_FONT",
            file_value=build_section.get("font"),
            default="Noto Sans Mono CJK",
        )
    )

    font_profile_out = Path(
        _resolve_value(
            cli=args.font_profile_out,
            env="KANJITUI_FONT_PROFILE_OUT",
            file_value=build_section.get("font_profile_out"),
            default="data/font_profile.json",
        )
    )

    build_report_out = Path(
        _resolve_value(
            cli=args.build_report_out,
            env="KANJITUI_BUILD_REPORT_OUT",
            file_value=build_section.get("build_report_out"),
            default="data/build_report.json",
        )
    )

    providers = _resolve_value(
        cli=args.providers,
        env="KANJITUI_PROVIDERS",
        file_value=build_section.get("providers"),
        default=DEFAULT_PROVIDERS,
        parser=_parse_providers,
    )

    no_font_filter = bool(
        _resolve_value(
            cli=args.no_font_filter,
            env="KANJITUI_NO_FONT_FILTER",
            file_value=build_section.get("no_font_filter"),
            default=False,
            parser=_parse_bool,
        )
    )

    normalizer = str(
        _resolve_value(
            cli=args.normalizer,
            env="KANJITUI_NORMALIZER",
            file_value=build_section.get("normalizer"),
            default="default",
        )
    )

    verbose = bool(
        _resolve_value(
            cli=args.verbose,
            env="KANJITUI_VERBOSE",
            file_value=app_section.get("verbose"),
            default=False,
            parser=_parse_bool,
        )
    )

    def _maybe_path(value: Any) -> Path | None:
        if value is None:
            return None
        text = str(value).strip()
        return Path(text) if text else None

    unihan_dir = _maybe_path(
        _resolve_value(
            cli=args.unihan_dir,
            env="KANJITUI_UNIHAN_DIR",
            file_value=build_section.get("unihan_dir"),
            default=None,
        )
    )
    kanjidic2_xml = _maybe_path(
        _resolve_value(
            cli=args.kanjidic2,
            env="KANJITUI_KANJIDIC2",
            file_value=build_section.get("kanjidic2"),
            default=None,
        )
    )
    jmdict_xml = _maybe_path(
        _resolve_value(
            cli=args.jmdict,
            env="KANJITUI_JMDICT",
            file_value=build_section.get("jmdict"),
            default=None,
        )
    )
    cedict_txt = _maybe_path(
        _resolve_value(
            cli=args.cedict,
            env="KANJITUI_CEDICT",
            file_value=build_section.get("cedict"),
            default=None,
        )
    )

    return AppConfig(
        db_path=db_path,
        user_db_path=user_db_path,
        build=build,
        data_dir=data_dir,
        font=font,
        font_profile_out=font_profile_out,
        build_report_out=build_report_out,
        unihan_dir=unihan_dir,
        kanjidic2_xml=kanjidic2_xml,
        jmdict_xml=jmdict_xml,
        cedict_txt=cedict_txt,
        providers=providers,
        normalizer=normalizer,
        no_font_filter=no_font_filter,
        verbose=verbose,
        config_path=config_path,
    )


def resolve_build_paths(config: AppConfig) -> BuildSourcePaths:
    default_unihan = config.data_dir / "unihan"
    if not default_unihan.exists():
        default_unihan = config.data_dir

    return BuildSourcePaths(
        unihan_dir=config.unihan_dir or default_unihan,
        kanjidic2_xml=config.kanjidic2_xml or (config.data_dir / "kanjidic2.xml"),
        jmdict_xml=config.jmdict_xml or (config.data_dir / "jmdict.xml"),
        cedict_txt=config.cedict_txt or (config.data_dir / "cedict_ts.u8"),
    )
