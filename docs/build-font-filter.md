# Build and Font Filter

Font filtering is the main way to avoid tofu glyphs.

## Standard Build

```bash
kanjitui --build --data-dir data/raw --db data/db.sqlite
```

## Build with Font Filter (CLI)

```bash
kanjitui --build --data-dir data/raw --db data/db.sqlite --font "Noto Sans CJK JP"
```

You can also use a direct font file path:

```bash
kanjitui --build --data-dir data/raw --db data/db.sqlite --font "/Users/you/Library/Fonts/BabelStoneHan.ttf"
```

## Build from Setup / Advanced Menus

- Setup (`Shift+S`): optional checkbox for auto-build with font filter.
- Advanced (`Shift+R`): manual rebuild with explicit font spec.

## Critical Rule for Tofu Avoidance

Build against the same font family the UI actually renders with.

- For TUI, this means your terminal font/fallback profile.
- For GUI, this means the GUI font selection (`--ui-font` or env).

If render font and build font differ, tofu can still appear.

## Error Handling Behavior

- If the font cannot be resolved, filtered rebuild fails with a clear error.
- If font coverage tooling is missing, rebuild tells you to install `fonttools`.

## Verifying Filter Effect

Look at build summary lines:

- `included=...`
- `excluded_font=...`

A nonzero `excluded_font` means filtering actively excluded unsupported glyphs.

