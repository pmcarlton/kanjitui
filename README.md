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
make run
make run-gui
```

Optional sentence build:

```bash
make build-sentences
```

## Documentation

Full manual, key reference, filters, advanced build/font-filter details, and workflows:

- [GitHub Pages docs](https://pmcarlton.github.io/kanjitui/docs/)

## Data Sources and Terms

This project can use data from Unicode Unihan, EDRDG (JMdict/EDICT + KANJIDIC2), CC-CEDICT, Tatoeba (optional), and StrokeOrder/KanjiVG (optional).  
See `THIRD_PARTY_NOTICES.md` and `data/licenses/` for details.
