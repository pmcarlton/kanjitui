# Search, Filters, and Data Features

## Search Syntax

Supported query styles:

- character: `漢`
- codepoint: `U+6F22` or `6F22`
- kana: `かんじ`, `カンジ`
- romaji: `kanji`
- pinyin: `hàn`, `han4`
- gloss substring: `Chinese character`

## Ordering and Discovery

Orderings:

- frequency
- radical
- reading
- codepoint

Related glyph selection sources:

- JP words in current panel
- CN words in current panel
- phonetic-series rows when phonetic overlay is shown

## Structural Tools

- radical browser with selectable grid and optional stroke subfilter
- variants graph panel (with jump)
- components overlay
- phonetic series overlay (with pinyin where available)
- provenance overlay

## User Study Features

- bookmarks
- per-glyph notes
- global notes
- recent query memory
- named filter presets in user DB

## Filters

Filter menu supports grouped criteria and preset storage.

Includes quick “hide no-reading” behavior scoped by language visibility/reading sort mode.

## Sentences and Words

- JP/CN example words are shown if dictionary rows exist.
- sentence rows are shown if `sentences` provider data is built.
- sentence display language set follows visible JP/CN panel state.

## Export

CLI export supports both character and query output:

```bash
kanjitui --db data/db.sqlite --export-char U+6F22 --export-format json
kanjitui --db data/db.sqlite --export-query han4 --export-format csv
```

## Setup and Data Providers

In-app setup can download:

- Unicode Unihan
- CC-CEDICT
- EDRDG KANJIDIC2
- EDRDG JMdict
- optional Tatoeba-derived `sentences.tsv`
- optional StrokeOrder assets

Acknowledgements and license links are available from startup/setup overlays.

