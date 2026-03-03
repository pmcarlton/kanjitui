# TODO

## Backlog

- [ ] Advanced setting: include structural-only Unihan characters (large DB mode)
  - Why: Some valid CJK ideographs (for example `U+20572` `𠕲`) are present in Unihan and supported by fonts, but currently excluded because they lack the annotation fields required by the default inclusion rule.
  - UX: Add an opt-in toggle under Advanced Settings in both `kanjitui` and `kanjigui`.
  - Behavior when enabled:
    - Include Unihan-only characters that have structural metadata (at minimum radical and/or stroke count) even if they have no JP/CN reading/gloss/variant/component rows.
    - Mark these rows as low-information in UI (for example, "structural-only").
  - Parser extension:
    - Consider parsing Unihan `kJapanese` as a fallback JP reading source for coverage expansion.
  - Tradeoff:
    - Expected substantial DB growth (roughly up to ~2x versus default).
  - Default:
    - Keep OFF for Lean/default setup.
