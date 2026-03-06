# kanjitui / kanjigui

[![GitHub Pages](https://img.shields.io/badge/docs-GitHub%20Pages-2ea44f?logo=github)](https://pmcarlton.github.io/kanjitui/)

Keyboard-first Han character explorer with two display modes:
- `kanjitui`: terminal UI
- `kanjigui`: PySide6 desktop UI

## Install

Python 3.11+:

```bash
pip install -e .[gui]
```

## Quick Start (Recommended)

The app now supports menu-driven setup, so manual download/build steps are usually unnecessary.

1. Start either mode:

```bash
kanjitui --db data/db.sqlite
# or
kanjigui --db data/db.sqlite
```

2. On first launch, open Setup with `Shift+S`.
3. Select data sources and run download.
4. Setup automatically rebuilds the DB after downloads.
5. Begin browsing immediately.

Notes:
- `Shift+A` opens acknowledgements/license summary.
- Setup shows terms/license links per source.
- Setup also shows storage guidance. Typical full lean data footprint is about `300-400 MiB` (reference install: `~377 MiB` in `data/`).

## Core Keys

- `Left`/`Right`: move through current order
- `/`: search
- `r`: radical browser
- `1` `2` `3` `4`: toggle JP/CN/Sentences/Variants panes
- `f`: filter menu
- `Shift+S`: setup/download menu
- `?`: help
- `q`: quit

## Optional CLI/Make Flow

For scripted or non-interactive workflows:

```bash
make fetch-data
make build-db
make release-smoke
make run
make run-gui
```

## Standalone macOS App (Lean)

Build a `.app` (and DMG by default) with bundled GUI + advanced-user TUI binary:

```bash
make package-macos
```

Result highlights:

- App bundle: `dist/Kanjigui.app`
- TUI binary inside app: `dist/Kanjigui.app/Contents/MacOS/kanjitui`
- Launcher uses user-writable data paths under:
  - `~/Library/Application Support/kanjitui/db.sqlite`
  - `~/Library/Application Support/kanjitui/raw/`

Optional shell link for advanced users after installing to `/Applications`:

```bash
ln -sf /Applications/Kanjigui.app/Contents/MacOS/kanjitui /usr/local/bin/kanjitui
```

Optional sentence build:

```bash
make build-sentences
```

Optional no-tofu validation (after a font-filtered build):

```bash
make release-smoke DB_PATH=data/db.sqlite FONT_SPEC="/Users/you/Library/Fonts/BabelStoneHan.ttf"
```

## Documentation

Full manual, key reference, filters, advanced build/font-filter details, and workflows:

- [GitHub Pages docs](https://pmcarlton.github.io/kanjitui/docs/)

## Data Sources and Terms

This project can use data from Unicode Unihan, EDRDG (JMdict/EDICT + KANJIDIC2), CC-CEDICT, Tatoeba (optional), and StrokeOrder/KanjiVG (optional).  
See `THIRD_PARTY_NOTICES.md` and `data/licenses/` for details.
