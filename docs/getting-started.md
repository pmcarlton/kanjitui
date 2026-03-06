# Install and First Run

## 1) Install

Use Python 3.11+.

```bash
pip install -e .
```

Recommended extras:

```bash
pip install -e .[test,gui]
```

## 2) Build Data (Recommended: in-app Setup)

Launch either mode and open Setup with `Shift+S`.

- Select sources.
- Download.
- Let Setup auto-build the DB.

Storage guidance:

- Typical full lean data footprint is about `300-400 MiB`.
- A reference install (including DB + raw sources) is about `377 MiB`.

## 3) Optional CLI Data Flow

```bash
make fetch-data
```

This downloads configured data sources to `data/raw/` (you can still use setup menus instead).

## 4) Build the DB

```bash
make build-db
```

Equivalent:

```bash
kanjitui --build --data-dir data/raw --db data/db.sqlite
```

## 5) Start the App

TUI:

```bash
kanjitui --db data/db.sqlite
```

GUI:

```bash
kanjigui --db data/db.sqlite
```

## 6) Standalone macOS Package

If you want a standalone app bundle/DMG:

```bash
make package-macos
```

After install to `/Applications`, advanced users can expose the bundled TUI binary:

```bash
ln -sf /Applications/Kanjigui.app/Contents/MacOS/kanjitui /usr/local/bin/kanjitui
```

## First-Startup Flow

On first launch you should see acknowledgements.

- `Shift+S`: open Setup/download menu
- `Shift+A`: reopen acknowledgements later
- `Shift+R`: open Advanced rebuild menu

## Minimal “It Works” Check

1. Launch app.
2. Move with Left/Right.
3. Open search with `/`.
4. Open radicals with `r`.
5. Toggle one overlay (`c`, `s`, or `p`).
6. Save a bookmark with `b`, then open list with `B`.
