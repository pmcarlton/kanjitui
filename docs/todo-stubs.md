# TODO Stubs

This page mirrors current `todo.md` backlog items as documentation stubs.

## Stub: Advanced Setting for Structural-Only Unihan Characters

Source: `todo.md`

Status: stub.

### Goal

Add an advanced opt-in mode to include low-information but structurally valid ideographs that are currently excluded by default inclusion rules.

### Why

Some codepoints are in Unihan and supported by fonts but are excluded because they lack current annotation minima.  
Example: `U+20572` `𠕲`.

### Planned UX

- Add toggle in Advanced settings in both `kanjitui` and `kanjigui`.
- Keep default OFF for lean mode.

### Planned Behavior

- Include Unihan-only rows with structural metadata (radical and/or stroke count).
- Mark as low-information in UI.

### Parser Extension (Planned)

- Evaluate fallback parsing of Unihan `kJapanese` for JP reading expansion.

### Tradeoff

- Substantial DB growth expected (up to roughly 2x vs default).

