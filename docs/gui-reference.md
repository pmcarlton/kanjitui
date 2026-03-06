# GUI Menu and Keys

`kanjigui` mirrors `kanjitui` logic, with desktop windows for overlays and a large current glyph display.

## Global Navigation

- `Left` / `Right` / `j` / `k`: move current glyph in active ordering
- `Up` / `Down`: move related glyph selection by row
- `Shift+Left` / `Shift+Right`: move related selection within row
- `Home` / `End`: first/last glyph in active ordering
- `Enter`: jump to selected related glyph
- `Tab`: cycle focus (`JP` -> `CN` -> `Variants`)
- `q`: close app

If focus is `Variants`, `Up/Down/Enter` control variants selection/jump.

## Main Keys

- `1`, `2`, `3`, `4`: panel visibility toggles
- `O`: ordering cycle
- `F`: frequency profile cycle
- `m`: JP kana/romaji toggle
- `N`: hide no-reading toggle
- `/`: search dialog
- `r`: radical browser dialog
- `f`: filter dialog
- `c`, `s`, `p`, `u`, `?`, `A`: overlay windows
- `Shift+S`: Setup dialog
- `Shift+R`: Advanced rebuild dialog
- `t`: stroke-order window (when available)
- `i`: open CCAMC glyph page
- `b`: bookmark toggle
- `B`: bookmark list dialog
- `n`: per-glyph note dialog
- `g`: global note dialog

## Overlay Close Behavior

Overlays close with:

- `Esc`
- the same key that opened them (for example `s` closes phonetic overlay)

Startup overlay closes on any non-modifier key.

## Panel Scrolling Behavior

- Panel text widgets are auto-sized to content.
- Per-panel internal scrollbars are disabled.
- If total content exceeds viewport, scroll the left panel stack area.

## GUI-Specific Notes

- You can set UI font with `--ui-font`.
- Large glyph display is independent from panel text formatting.
- Keyboard-first operation is fully supported; mouse is optional.
- Setup (`Shift+S`) includes per-selection storage estimates and full-lean footprint guidance.
