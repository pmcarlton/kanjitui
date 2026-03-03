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

## 2) Fetch Source Data

```bash
make fetch-data
```

This downloads configured data sources to `data/raw/`.

## 3) Build the DB

```bash
make build-db
```

Equivalent:

```bash
kanjitui --build --data-dir data/raw --db data/db.sqlite
```

## 4) Start the App

TUI:

```bash
kanjitui --db data/db.sqlite
```

GUI:

```bash
kanjigui --db data/db.sqlite
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

