# Phase B Plan

## Scope
1. Add a 21-character navigation strip at bottom (`[-10..+10]`, current centered/highlighted).
2. Replace radical picker list with a glyph-based 2D table navigated via arrow keys.

## Affected modules
- `src/kanjitui/tui/app.py`
- `src/kanjitui/tui/navigation.py` (new)
- `src/kanjitui/tui/radicals.py` (new)
- tests for navigation strip windowing and radical grid movement.

## Risks
- Rendering overflows on narrow terminals.
- Navigation behavior regressions in radical mode.

## Validation
- Unit tests for strip and grid helpers.
- Manual smoke in TUI run path.
