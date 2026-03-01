from __future__ import annotations

from dataclasses import dataclass

from kanjitui.search import normalize


@dataclass(frozen=True)
class NormalizerPlugin:
    name: str

    def contains_cjk(self, text: str) -> bool:
        return normalize.contains_cjk(text)

    def parse_codepoint_token(self, text: str) -> int | None:
        return normalize.parse_codepoint_token(text)

    def is_kana_text(self, text: str) -> bool:
        return normalize.is_kana_text(text)

    def normalize_kana(self, text: str) -> str:
        return normalize.normalize_kana(text)

    def looks_like_romaji(self, text: str) -> bool:
        return normalize.looks_like_romaji(text)

    def romaji_to_hiragana(self, text: str) -> str:
        return normalize.romaji_to_hiragana(text)

    def looks_like_pinyin(self, text: str) -> bool:
        return normalize.looks_like_pinyin(text)

    def normalize_pinyin_for_search(self, text: str) -> str:
        return normalize.normalize_pinyin_for_search(text)


class StrictNormalizerPlugin(NormalizerPlugin):
    """A stricter profile that requires explicit kana/pinyin patterns."""

    def looks_like_romaji(self, text: str) -> bool:
        token = text.strip()
        if " " in token:
            return False
        return super().looks_like_romaji(token)


_PLUGINS: dict[str, NormalizerPlugin] = {
    "default": NormalizerPlugin(name="default"),
    "strict": StrictNormalizerPlugin(name="strict"),
}


def get_normalizer(name: str | None) -> NormalizerPlugin:
    key = (name or "default").strip().lower()
    try:
        return _PLUGINS[key]
    except KeyError as exc:
        known = ", ".join(sorted(_PLUGINS))
        raise ValueError(f"Unknown normalizer '{name}'. Known: {known}") from exc


def available_normalizers() -> tuple[str, ...]:
    return tuple(sorted(_PLUGINS))
