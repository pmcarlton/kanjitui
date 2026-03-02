# Phase H Plan (Shared Filter Menu + Named Presets)

## Scope
1. Add a shared filter state/engine (no new downloads required).
2. Add a filter popup in TUI (`f`) with arrow navigation + space toggle.
3. Add a filter dialog in GUI (`f`) with equivalent filter groups.
4. Persist named filter presets in user DB and support save/load/delete.
5. Keep existing fast toggle (`Shift+N`) as compatibility behavior.

## Filter groups (current-data only)
- Reading availability (JP/CN/both/no-readings)
- JP reading type (on/kun/both/only)
- CN complexity (single vs multi pinyin)
- Variant class (simplified/traditional/semantic/compat/no variants)
- Structure (components/phonetic presence, stroke bucket)
- Frequency (profile + rank band)
- Data coverage (provenance/sentences/source tags)

## Affected modules
- `src/kanjitui/filtering.py` (new)
- `src/kanjitui/db/query.py` (filter metadata query helpers)
- `src/kanjitui/db/user.py` (named preset persistence)
- `src/kanjitui/tui/app.py` (filter overlay + preset interaction)
- `src/kanjitui/gui/state.py`, `src/kanjitui/gui/window.py` (filter dialog + preset interaction)
- tests + README/help updates

## Risks
- UI complexity in TUI overlay/preset flow.
- Potential ordering/filter regressions if state reload paths miss cache refresh.

## Validation
- `python -m compileall -q src tests`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`
- manual smoke: open filter popup, apply filter, save preset, reload preset.
