# kanjitui

Terminal explorer for a font-safe subset of Han characters with Japanese and Chinese readings, glosses, and example words.

## Install

1. Create a Python 3.11+ environment.
2. Install the package in editable mode:

```bash
pip install -e .
```

Optional extras:

```bash
pip install -e .[build,test]
```

## Fetch Data

```bash
make fetch-data
```

This downloads Unihan, CC-CEDICT, KANJIDIC2, and JMdict into `data/raw/`.
EDRDG attribution and license terms still apply to KANJIDIC2/JMdict.

## Build Database

```bash
make build-db
```

Equivalent CLI:

```bash
kanjitui --build --data-dir data/raw --db data/db.sqlite
```

You can limit build sources with:

```bash
kanjitui --build --providers unihan,kanjidic2,jmdict,cedict
```

## Run TUI

```bash
make run
```

Equivalent CLI:

```bash
kanjitui --db data/db.sqlite
```

## Keybindings

- `Right`/`Down`/`j`: next character
- `Left`/`Up`/`k`: previous character
- `Home`/`End`: first/last in ordering
- `Tab`: switch JP/CN focus
- `O`: cycle ordering (`freq` -> `radical` -> `reading` -> `codepoint`)
- `/`: search overlay
- `r`: radical browser overlay
- `1`: toggle JP pane
- `2`: toggle CN pane
- `v`: toggle variants line
- `?`: help/attribution overlay
- `q`: quit

## Search Syntax

- direct character: `漢`
- codepoint: `U+6F22` or `6F22`
- kana: `かんじ` or `カンジ`
- romaji (best effort): `kanji`
- pinyin (tone marks or numbers): `hàn`, `han4`
- meaning substring: `Chinese character`

## Data Layout

- `data/db.sqlite`: built SQLite database
- `data/user.sqlite`: user metadata database (groundwork for future features)
- `data/font_profile.json`: optional coverage cache
- `data/build_report.json`: build counts and exclusions

## Configuration

Config precedence is `CLI > environment > config file > defaults`.

Optional TOML config example:

```toml
[app]
db = "data/db.sqlite"
user_db = "data/user.sqlite"
verbose = false

[build]
enabled = false
data_dir = "data/raw"
font = "Noto Sans Mono CJK"
providers = ["unihan", "kanjidic2", "jmdict", "cedict"]
no_font_filter = false
font_profile_out = "data/font_profile.json"
build_report_out = "data/build_report.json"
```

Run with:

```bash
kanjitui --config path/to/kanjitui.toml
```

## Known Limitations (MVP)

- Radical browser currently selects by radical number only (no stroke subfilter yet).
- Romaji conversion uses a lightweight Hepburn-ish mapping.
- Example-word ranking uses heuristics (not corpus frequencies).
- If font coverage cannot be computed, build can run with no font filter.
