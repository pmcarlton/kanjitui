from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from kanjitui.providers.cedict import parse_cedict
from kanjitui.providers.jmdict import parse_jmdict
from kanjitui.providers.kanjidic2 import parse_kanjidic2
from kanjitui.providers.sentences import parse_sentences_tsv
from kanjitui.providers.unihan import parse_unihan_dir


PathGetter = Callable[[Any], Path]
Loader = Callable[[Path], Any]


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    path_getter: PathGetter
    loader: Loader
    description: str = ""


class ProviderRegistry:
    def __init__(self, specs: list[ProviderSpec] | None = None) -> None:
        self._specs: dict[str, ProviderSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: ProviderSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"Provider already registered: {spec.name}")
        self._specs[spec.name] = spec

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs.keys()))

    def get(self, name: str) -> ProviderSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            known = ", ".join(self.names())
            raise KeyError(f"Unknown provider '{name}'. Known providers: {known}") from exc

    def resolve_enabled(self, enabled: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
        if enabled is None:
            return self.names()
        resolved: list[str] = []
        for raw in enabled:
            name = raw.strip()
            if not name:
                continue
            _ = self.get(name)
            if name not in resolved:
                resolved.append(name)
        return tuple(resolved)

    def required_paths(self, enabled: tuple[str, ...] | list[str], paths: Any) -> list[Path]:
        required: list[Path] = []
        for name in self.resolve_enabled(enabled):
            spec = self.get(name)
            provider_path = spec.path_getter(paths)
            if provider_path is None:
                raise FileNotFoundError(f"Provider path is not configured for '{name}'")
            required.append(provider_path)
        return required

    def load_selected(self, enabled: tuple[str, ...] | list[str], paths: Any) -> dict[str, Any]:
        loaded: dict[str, Any] = {}
        for name in self.resolve_enabled(enabled):
            spec = self.get(name)
            provider_path = spec.path_getter(paths)
            if provider_path is None:
                raise FileNotFoundError(f"Provider path is not configured for '{name}'")
            loaded[name] = spec.loader(provider_path)
        return loaded


def default_build_registry() -> ProviderRegistry:
    return ProviderRegistry(
        specs=[
            ProviderSpec(
                name="unihan",
                path_getter=lambda p: p.unihan_dir,
                loader=parse_unihan_dir,
                description="Unicode Unihan",
            ),
            ProviderSpec(
                name="kanjidic2",
                path_getter=lambda p: p.kanjidic2_xml,
                loader=parse_kanjidic2,
                description="EDRDG KANJIDIC2",
            ),
            ProviderSpec(
                name="jmdict",
                path_getter=lambda p: p.jmdict_xml,
                loader=parse_jmdict,
                description="EDRDG JMdict",
            ),
            ProviderSpec(
                name="cedict",
                path_getter=lambda p: p.cedict_txt,
                loader=parse_cedict,
                description="CC-CEDICT",
            ),
            ProviderSpec(
                name="sentences",
                path_getter=lambda p: p.sentences_tsv,
                loader=parse_sentences_tsv,
                description="Optional sentence TSV",
            ),
        ]
    )
