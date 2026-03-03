# TUI Menu and Keys

## Global Navigation

- `Left` / `Right` / `j` / `k`: move current glyph in active ordering
- `Up` / `Down`: move related glyph selection by row
- `Shift+Left` / `Shift+Right`: move related glyph selection within current row
- `Home` / `End`: first/last glyph in active ordering
- `Enter`: jump to selected related glyph
- `Tab`: cycle panel focus (`JP` -> `CN` -> `Variants`)
- `q`: quit

If panel focus is `Variants`, `Up/Down/Enter` operate on variant selection instead.

## Main Toggles and Commands

- `1`: show/hide JP panel
- `2`: show/hide CN panel
- `3`: show/hide sentence panel
- `4`: show/hide variants panel
- `O`: cycle ordering (`freq`, `radical`, `reading`, `codepoint`)
- `F`: cycle frequency profile
- `m`: toggle JP kana/romaji display
- `N`: toggle quick “hide no-reading”
- `/`: open search
- `r`: open radical browser
- `f`: open filter menu
- `c`: components overlay
- `s`: phonetic-series overlay
- `p`: provenance overlay
- `u`: user workspace overlay
- `t`: stroke-order popup (when available)
- `i`: open glyph page at CCAMC
- `?`: help overlay
- `Shift+S`: Setup/download menu
- `Shift+R`: Advanced rebuild menu
- `Shift+A`: acknowledgements

## Search Overlay

- Type query text directly
- `Enter`: run search, or jump to selected result
- `Up` / `Down`: result selection
- `Shift+Up` / `Shift+Down` or `Home` / `End`: top/bottom
- `Esc`: close

## Radical Browser

Grid mode:

- arrows: move radical cell
- `Enter`: choose radical
- `Esc`: close

Results mode:

- `Up` / `Down`: select glyph in results
- `[` / `]`: stroke-count filter step
- `Enter`: jump
- `Backspace`: back to radical grid

## Filter Menu

- `Up` / `Down`: move option
- `Shift+Up` / `Shift+Down`: jump filter group
- `Space` / `Enter`: apply selected option
- `w`: save preset
- `p`: preset mode
- `x`: delete selected preset
- `c`: clear all filters
- `Esc`: close

## Bookmarks and Notes

- `b`: toggle bookmark on current glyph
- `B`: open bookmark picker
- in picker: `x` delete selected bookmark, `Enter` jump
- `n`: per-glyph note editor
- `g`: global note editor
- note editor save: `Ctrl+S`

## Setup Menu (`Shift+S`)

- `Up` / `Down`: move row
- `Space` / `Enter` / `1..9`: toggle source row
- `f`: toggle setup auto-build font filter
- `d`: download selected
- `a`: select all
- `n`: clear selection
- `Esc`: close

## Advanced Rebuild (`Shift+R`)

- `Up` / `Down`: move item
- `Space` / `Enter`: toggle/activate selected item
- `f`: toggle font filter
- `e`: edit font spec
- `d` or `x`: run rebuild
- `Esc`: close

