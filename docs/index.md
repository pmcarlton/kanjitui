# Overview

`kanjitui` and `kanjigui` are two display modes for the same core Han-character explorer:

- `kanjitui`: terminal/curses UI
- `kanjigui`: PySide6 desktop UI

Both modes use the same SQLite database and share the same study features:

- JP/CN readings and glosses
- example words and sentence rows (if available)
- variants graph, components, phonetic series, provenance
- radical browser
- bookmarks, notes, query history, filter presets
- setup/download menus and acknowledgements
- optional stroke-order animation
- optional font-filtered builds to avoid unsupported glyphs

## Core Concept

The app presents a current glyph and a set of related data panels.

- Left/Right move by your current ordering (frequency, radical, reading, or codepoint).
- Up/Down select related glyph candidates from shown word/phonetic data.
- Enter jumps to the selected related glyph.

This supports two common modes of exploration:

- broad browsing by ordering
- local discovery by “related glyph” jumps

## Data Model at a Glance

- Main DB: `data/db.sqlite`
- User DB: `data/user.sqlite`
- Raw source files: `data/raw/`

Source providers are modular and optional. Once built, the app runs offline.

## Read Next

1. [Install and First Run](getting-started.md)
2. [Build and Font Filter](build-font-filter.md)
3. [TUI Menu and Keys](tui-reference.md) or [GUI Menu and Keys](gui-reference.md)

