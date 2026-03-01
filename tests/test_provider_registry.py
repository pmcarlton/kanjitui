import pytest

from kanjitui.providers.registry import default_build_registry


def test_default_registry_names() -> None:
    registry = default_build_registry()
    names = registry.names()
    assert "unihan" in names
    assert "kanjidic2" in names
    assert "jmdict" in names
    assert "cedict" in names
    assert "sentences" in names


def test_registry_resolve_enabled_dedups() -> None:
    registry = default_build_registry()
    enabled = registry.resolve_enabled(("cedict", "cedict", "unihan"))
    assert enabled == ("cedict", "unihan")


def test_registry_unknown_provider_errors() -> None:
    registry = default_build_registry()
    with pytest.raises(KeyError):
        registry.resolve_enabled(("missing",))
