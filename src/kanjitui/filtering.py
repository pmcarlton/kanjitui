from __future__ import annotations

from dataclasses import dataclass, field


TRI_STATE_VALUES = ("any", "yes", "no")


@dataclass(frozen=True)
class FilterOption:
    value: str
    label: str


@dataclass(frozen=True)
class FilterGroupSpec:
    key: str
    label: str
    options: tuple[FilterOption, ...]


@dataclass
class FilterState:
    reading_availability: str = "any"
    jp_reading_type: str = "any"
    cn_complexity: str = "any"
    variant_class: str = "any"
    has_components: str = "any"
    has_phonetic: str = "any"
    stroke_bucket: str = "any"
    frequency_profile: str = "any"
    frequency_band: str = "any"
    has_provenance: str = "any"
    has_sentences: str = "any"
    source_unihan: str = "any"
    source_kanjidic2: str = "any"
    source_cedict: str = "any"

    def to_payload(self) -> dict[str, str]:
        return {
            "reading_availability": self.reading_availability,
            "jp_reading_type": self.jp_reading_type,
            "cn_complexity": self.cn_complexity,
            "variant_class": self.variant_class,
            "has_components": self.has_components,
            "has_phonetic": self.has_phonetic,
            "stroke_bucket": self.stroke_bucket,
            "frequency_profile": self.frequency_profile,
            "frequency_band": self.frequency_band,
            "has_provenance": self.has_provenance,
            "has_sentences": self.has_sentences,
            "source_unihan": self.source_unihan,
            "source_kanjidic2": self.source_kanjidic2,
            "source_cedict": self.source_cedict,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "FilterState":
        state = cls()
        for key in state.to_payload().keys():
            value = payload.get(key)
            if isinstance(value, str) and value:
                setattr(state, key, value)
        return state

    def is_active(self) -> bool:
        return any(value != "any" for value in self.to_payload().values())


@dataclass
class FilterData:
    all_cps: set[int] = field(default_factory=set)
    jp_cps: set[int] = field(default_factory=set)
    cn_cps: set[int] = field(default_factory=set)
    jp_on_cps: set[int] = field(default_factory=set)
    jp_kun_cps: set[int] = field(default_factory=set)
    cn_multi_cps: set[int] = field(default_factory=set)
    variant_simplified_cps: set[int] = field(default_factory=set)
    variant_traditional_cps: set[int] = field(default_factory=set)
    variant_semantic_cps: set[int] = field(default_factory=set)
    variant_compat_cps: set[int] = field(default_factory=set)
    any_variant_cps: set[int] = field(default_factory=set)
    components_cps: set[int] = field(default_factory=set)
    phonetic_cps: set[int] = field(default_factory=set)
    provenance_cps: set[int] = field(default_factory=set)
    sentences_cps: set[int] = field(default_factory=set)
    source_unihan_cps: set[int] = field(default_factory=set)
    source_kanjidic2_cps: set[int] = field(default_factory=set)
    source_cedict_cps: set[int] = field(default_factory=set)
    strokes_by_cp: dict[int, int | None] = field(default_factory=dict)
    frequency_ranks: dict[str, dict[int, int]] = field(default_factory=dict)

    def with_frequency_profile(self, profile: str | None) -> str:
        if profile and profile in self.frequency_ranks:
            return profile
        if self.frequency_ranks:
            return sorted(self.frequency_ranks.keys())[0]
        return "any"


def filter_group_specs(freq_profiles: list[str]) -> list[FilterGroupSpec]:
    profile_options = [FilterOption("any", "Any profile")]
    profile_options.extend(FilterOption(name, name) for name in freq_profiles)
    return [
        FilterGroupSpec(
            key="reading_availability",
            label="Reading Availability",
            options=(
                FilterOption("any", "Any"),
                FilterOption("jp", "Has JP reading"),
                FilterOption("cn", "Has CN reading"),
                FilterOption("jp_or_cn", "Has JP or CN"),
                FilterOption("both", "Has both JP and CN"),
                FilterOption("none", "No readings"),
            ),
        ),
        FilterGroupSpec(
            key="jp_reading_type",
            label="JP Reading Type",
            options=(
                FilterOption("any", "Any"),
                FilterOption("has_on", "Has on"),
                FilterOption("has_kun", "Has kun"),
                FilterOption("on_only", "On only"),
                FilterOption("kun_only", "Kun only"),
                FilterOption("both", "Both on+kun"),
            ),
        ),
        FilterGroupSpec(
            key="cn_complexity",
            label="CN Reading Complexity",
            options=(
                FilterOption("any", "Any"),
                FilterOption("single", "Single pinyin"),
                FilterOption("multi", "Multiple pinyin"),
            ),
        ),
        FilterGroupSpec(
            key="variant_class",
            label="Variant Class",
            options=(
                FilterOption("any", "Any"),
                FilterOption("simplified", "Has simplified variant"),
                FilterOption("traditional", "Has traditional variant"),
                FilterOption("semantic", "Has semantic/specialized variant"),
                FilterOption("compat", "Has compatibility variant"),
                FilterOption("none", "No variants"),
            ),
        ),
        FilterGroupSpec(
            key="has_components",
            label="Components",
            options=(
                FilterOption("any", "Any"),
                FilterOption("yes", "Has components"),
                FilterOption("no", "No components"),
            ),
        ),
        FilterGroupSpec(
            key="has_phonetic",
            label="Phonetic Series",
            options=(
                FilterOption("any", "Any"),
                FilterOption("yes", "Has phonetic-series"),
                FilterOption("no", "No phonetic-series"),
            ),
        ),
        FilterGroupSpec(
            key="stroke_bucket",
            label="Stroke Count",
            options=(
                FilterOption("any", "Any"),
                FilterOption("1-5", "1-5"),
                FilterOption("6-10", "6-10"),
                FilterOption("11-15", "11-15"),
                FilterOption("16+", "16+"),
            ),
        ),
        FilterGroupSpec(
            key="frequency_profile",
            label="Frequency Profile",
            options=tuple(profile_options),
        ),
        FilterGroupSpec(
            key="frequency_band",
            label="Frequency Band",
            options=(
                FilterOption("any", "Any"),
                FilterOption("top500", "Top 500"),
                FilterOption("501-2000", "501-2000"),
                FilterOption("2001+", "2001+"),
                FilterOption("unranked", "Unranked"),
            ),
        ),
        FilterGroupSpec(
            key="has_provenance",
            label="Provenance Rows",
            options=(
                FilterOption("any", "Any"),
                FilterOption("yes", "Has provenance"),
                FilterOption("no", "No provenance"),
            ),
        ),
        FilterGroupSpec(
            key="has_sentences",
            label="Sentence Rows",
            options=(
                FilterOption("any", "Any"),
                FilterOption("yes", "Has sentence examples"),
                FilterOption("no", "No sentence examples"),
            ),
        ),
        FilterGroupSpec(
            key="source_unihan",
            label="Source: Unihan",
            options=(
                FilterOption("any", "Any"),
                FilterOption("yes", "Includes Unihan"),
                FilterOption("no", "Excludes Unihan"),
            ),
        ),
        FilterGroupSpec(
            key="source_kanjidic2",
            label="Source: KANJIDIC2",
            options=(
                FilterOption("any", "Any"),
                FilterOption("yes", "Includes KANJIDIC2"),
                FilterOption("no", "Excludes KANJIDIC2"),
            ),
        ),
        FilterGroupSpec(
            key="source_cedict",
            label="Source: CC-CEDICT",
            options=(
                FilterOption("any", "Any"),
                FilterOption("yes", "Includes CC-CEDICT"),
                FilterOption("no", "Excludes CC-CEDICT"),
            ),
        ),
    ]


def _tri_state_match(value: str, cp: int, cp_set: set[int]) -> bool:
    if value == "any":
        return True
    has = cp in cp_set
    if value == "yes":
        return has
    if value == "no":
        return not has
    return True


def _stroke_bucket_match(bucket: str, strokes: int | None) -> bool:
    if bucket == "any":
        return True
    if strokes is None:
        return False
    if bucket == "1-5":
        return 1 <= strokes <= 5
    if bucket == "6-10":
        return 6 <= strokes <= 10
    if bucket == "11-15":
        return 11 <= strokes <= 15
    if bucket == "16+":
        return strokes >= 16
    return True


def _frequency_match(cp: int, state: FilterState, data: FilterData, default_profile: str | None) -> bool:
    profile = state.frequency_profile
    if profile == "any":
        profile = default_profile or "any"
    if state.frequency_band == "any":
        return True
    if profile == "any" or profile not in data.frequency_ranks:
        return state.frequency_band == "unranked"
    rank = data.frequency_ranks[profile].get(cp)
    if state.frequency_band == "unranked":
        return rank is None
    if rank is None:
        return False
    if state.frequency_band == "top500":
        return rank <= 500
    if state.frequency_band == "501-2000":
        return 501 <= rank <= 2000
    if state.frequency_band == "2001+":
        return rank >= 2001
    return True


def _reading_availability_match(cp: int, state: FilterState, data: FilterData) -> bool:
    mode = state.reading_availability
    has_jp = cp in data.jp_cps
    has_cn = cp in data.cn_cps
    if mode == "any":
        return True
    if mode == "jp":
        return has_jp
    if mode == "cn":
        return has_cn
    if mode == "jp_or_cn":
        return has_jp or has_cn
    if mode == "both":
        return has_jp and has_cn
    if mode == "none":
        return (not has_jp) and (not has_cn)
    return True


def _jp_type_match(cp: int, state: FilterState, data: FilterData) -> bool:
    mode = state.jp_reading_type
    has_on = cp in data.jp_on_cps
    has_kun = cp in data.jp_kun_cps
    if mode == "any":
        return True
    if mode == "has_on":
        return has_on
    if mode == "has_kun":
        return has_kun
    if mode == "on_only":
        return has_on and not has_kun
    if mode == "kun_only":
        return has_kun and not has_on
    if mode == "both":
        return has_on and has_kun
    return True


def _cn_complexity_match(cp: int, state: FilterState, data: FilterData) -> bool:
    mode = state.cn_complexity
    has_cn = cp in data.cn_cps
    is_multi = cp in data.cn_multi_cps
    if mode == "any":
        return True
    if mode == "single":
        return has_cn and not is_multi
    if mode == "multi":
        return is_multi
    return True


def _variant_match(cp: int, state: FilterState, data: FilterData) -> bool:
    mode = state.variant_class
    if mode == "any":
        return True
    if mode == "none":
        return cp not in data.any_variant_cps
    if mode == "simplified":
        return cp in data.variant_simplified_cps
    if mode == "traditional":
        return cp in data.variant_traditional_cps
    if mode == "semantic":
        return cp in data.variant_semantic_cps
    if mode == "compat":
        return cp in data.variant_compat_cps
    return True


def apply_filter_state(
    ordered_cps: list[int],
    state: FilterState,
    data: FilterData,
    default_frequency_profile: str | None = None,
) -> list[int]:
    if not ordered_cps:
        return []
    out: list[int] = []
    for cp in ordered_cps:
        if cp not in data.all_cps:
            continue
        if not _reading_availability_match(cp, state, data):
            continue
        if not _jp_type_match(cp, state, data):
            continue
        if not _cn_complexity_match(cp, state, data):
            continue
        if not _variant_match(cp, state, data):
            continue
        if not _tri_state_match(state.has_components, cp, data.components_cps):
            continue
        if not _tri_state_match(state.has_phonetic, cp, data.phonetic_cps):
            continue
        if not _stroke_bucket_match(state.stroke_bucket, data.strokes_by_cp.get(cp)):
            continue
        if not _frequency_match(cp, state, data, default_frequency_profile):
            continue
        if not _tri_state_match(state.has_provenance, cp, data.provenance_cps):
            continue
        if not _tri_state_match(state.has_sentences, cp, data.sentences_cps):
            continue
        if not _tri_state_match(state.source_unihan, cp, data.source_unihan_cps):
            continue
        if not _tri_state_match(state.source_kanjidic2, cp, data.source_kanjidic2_cps):
            continue
        if not _tri_state_match(state.source_cedict, cp, data.source_cedict_cps):
            continue
        out.append(cp)
    return out
