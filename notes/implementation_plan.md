# MVP Implementation Plan

## Scope
Implement a Python-based `kanjitui` application with:
- Offline SQLite build pipeline from Unihan, KANJIDIC2, JMdict, and CC-CEDICT.
- Font-coverage filtering (font cmap preferred, fallback to disabled filter with warning).
- Search + browse TUI for JP/CN readings, glosses, and example words.
- Parser unit tests and integration DB test with sample fixtures.

## Affected Modules
- `src/kanjitui/providers/`: source-specific parsers + font coverage module.
- `src/kanjitui/db/`: schema, build pipeline, query helpers.
- `src/kanjitui/search/`: normalization and query classification/execution.
- `src/kanjitui/tui/`: curses app and overlays (search/help/radical browser).
- `src/kanjitui/cli.py`: command-line entry points and build/run orchestration.
- `tests/`: parser tests and integration build/query test.
- `README.md`, `data/README.md`, `data/licenses/*`: usage and attribution docs.

## Data Format Changes
- New SQLite schema (`chars`, `jp_readings`, `jp_gloss`, `cn_readings`, `cn_gloss`, `variants`, `jp_words`, `cn_words`, `search_index`).
- Build report JSON (optional) and optional font profile JSON output.
- Normalized fields:
  - NFC text storage
  - pinyin stored as marked + numbered
  - kana normalized to hiragana for search keys

## Risks
- XML format variance in JMdict/KANJIDIC2; mitigated with defensive parsing.
- Font detection portability; mitigated with optional `fontTools` and graceful fallback.
- Ranking quality for example words is heuristic; documented as MVP behavior.
- Large datasets may impact build time/memory; mitigated with deterministic incremental processing and capped example sets.

## Validation
- `pytest` for parser and integration tests.
- `python -m kanjitui --help` smoke check.
- `python -m kanjitui --build --data-dir tests/fixtures --db /tmp/kanjitui_test.sqlite` smoke check.

## Assumptions
- Python 3.11+ environment.
- Runtime TUI implemented with stdlib `curses` for portability and minimal dependencies.
- Manual placement is acceptable for EDRDG data if automated fetch is unavailable.
