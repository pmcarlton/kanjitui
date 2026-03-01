# spec.md

## Project: Kanji/CJK TUI Explorer (MVP)

### One-line
A fast terminal UI that lets you browse and search a **font-safe subset** of Han characters and view **Japanese + Chinese readings** plus **1–5 example words per language**.

---

## 0. MVP Goals and Non-Goals

### Goals (MVP)
1. Display a single Han character at a time with:
   - Codepoint (`U+XXXX`)
   - Radical + stroke count (when available)
   - **Japanese readings** (on/kun) and brief gloss (if available)
   - **Chinese reading(s)** (pinyin) and brief gloss (if available)
   - **1–5 example words** for JP and CN, ranked "common first"
2. Provide ergonomic **keyboard-only navigation**:
   - next/previous within the current ordering
   - switch JP/CN “focus”
   - search by kana / romaji / pinyin / meaning substring / codepoint / direct char
   - browse by radical
3. Build a **subset** of characters that:
   - are **renderable** in a chosen terminal-compatible font profile (default: Noto Sans Mono CJK)
   - have **at least some attested annotation** (JP or CN reading/meaning/variant)
4. Modular pane system so future features can be added without rewriting the core.

### Non-Goals (MVP)
- Stroke order diagrams, calligraphic forms, handwriting input
- Full sentence corpora or classical vs modern sentences
- Tangut/Khitan integration
- Perfect frequency ranking (we start with heuristic ranking and simple “common” flags)
- Network access at runtime (MVP should be offline after build)

---

## 1. Runtime Model

### Core concept
- The TUI displays a **current character** and a set of **panes** (JP pane, CN pane, Variants/status).
- “Providers” supply data. Providers can be toggled on/off, and new providers can be added later.

### Providers in MVP
- `unihan`: basic properties, variants, radical/strokes where available
- `kanjidic2`: JP readings + meanings + metadata (when present)
- `jmdict`: JP example words (1–5) + reading + gloss
- `cedict`: CN example words (1–5) + pinyin + gloss; also per-char pinyin list via aggregation
- `fontcov`: character set filter via font coverage profile

---

## 2. Data Sources

### Required sources (MVP)
1. **Unicode Unihan Database**
   - Use for: codepoint metadata, radical/strokes, variant relationships, Japanese on/kun when present, Mandarin pinyin, definitions.
   - Format: Unihan text files (from Unihan.zip).
2. **KANJIDIC2 (EDRDG)**
   - Use for: Japanese on/kun readings, English glosses/meanings, stroke count, radicals, frequency/grade fields when present.
   - Format: XML.
3. **JMdict (EDRDG)**
   - Use for: Japanese example words containing the character, with kana reading and gloss.
   - Format: XML.
4. **CC-CEDICT**
   - Use for: Chinese example words containing the character, with trad/simp, pinyin, gloss.
   - Format: text file (UTF-8).

### Optional convenience sources (allowed, not required)
- Pre-simplified JSON builds of JMdict/KANJIDIC2 (only if license compliance is easy and provenance is clear).
- Precomputed font coverage maps for Noto Mono CJK.

### Licensing/attribution (MVP requirement)
- Include an `ABOUT` screen (or `?` help panel) showing:
  - Unihan attribution
  - EDRDG attribution and license notes for KANJIDIC2/JMdict
  - CC-CEDICT attribution and license notes
- Do not bundle data without retaining required license files and attribution in the repo (or in a `data/licenses/` folder).
- Prefer a `make fetch-data` step that downloads upstream sources rather than committing large datasets.

---

## 3. Build Pipeline

### Overview
The project has a **build step** that:
1. fetches data (optional)
2. parses & normalizes
3. computes font-safe subset
4. builds a compact SQLite database + indexes

### Build outputs
- `data/db.sqlite` (or user-configurable path)
- Optional `data/font_profile.json` (cache of font coverage)
- Optional `data/build_report.json` (counts, excluded reasons)

### Character inclusion rule (MVP)
Include a character `C` if:
1. `C` is covered by the chosen font profile **AND**
2. `C` has at least one of:
   - JP reading (from KANJIDIC2 or Unihan)
   - CN reading (from Unihan or aggregated from CEDICT entries)
   - meaning/definition (from KANJIDIC2 or Unihan)
   - variant relation (from Unihan)

### Font coverage strategy (MVP)
Default profile: Noto Sans Mono CJK (or similarly named depending on OS).
Implement one of:
- **Preferred**: parse font cmap table (TTF/OTF) and compute covered codepoints.
- **Fallback**: bundled static codepoint list for a known font version (documented).
If neither works, allow running without font filtering (warn user).

### Normalization rules (MVP)
- Canonical character key: Unicode scalar value (codepoint integer)
- Store text in NFC.
- Pinyin:
  - store both tone-marked (e.g. `hàn`) and tone-numbered (e.g. `han4`)
  - accept search input in either; normalize for matching
- Romaji:
  - accept Hepburn-ish; convert to kana for matching (best-effort)
- Kana:
  - accept both hiragana and katakana; normalize to hiragana for search

---

## 4. SQLite Schema (MVP)

### Tables

#### `chars`
One row per included character.
- `cp` INTEGER PRIMARY KEY  (Unicode codepoint)
- `ch` TEXT NOT NULL        (actual character)
- `radical` INTEGER NULL
- `strokes` INTEGER NULL
- `sources` TEXT NOT NULL   (bitmask or JSON of which providers had data)

#### `jp_readings`
- `cp` INTEGER (FK -> chars.cp)
- `type` TEXT CHECK(type IN ('on','kun'))
- `reading` TEXT
- `rank` INTEGER NULL

#### `jp_gloss`
- `cp` INTEGER (FK)
- `gloss` TEXT

#### `cn_readings`
- `cp` INTEGER (FK)
- `pinyin_marked` TEXT
- `pinyin_numbered` TEXT
- `rank` INTEGER NULL

#### `cn_gloss`
- `cp` INTEGER (FK)
- `gloss` TEXT

#### `variants`
- `cp` INTEGER (FK)
- `kind` TEXT  (e.g. 'traditional','simplified','zvariant','compat','semantic','specialized')
- `target_cp` INTEGER
- `note` TEXT NULL

#### `jp_words`
Example words containing the character, capped at 5 per cp (enforced at build time).
- `cp` INTEGER (FK)
- `word` TEXT
- `reading_kana` TEXT NULL
- `gloss_en` TEXT NULL
- `rank` INTEGER

#### `cn_words`
Example words containing the character, capped at 5 per cp.
- `cp` INTEGER (FK)
- `trad` TEXT
- `simp` TEXT
- `pinyin_marked` TEXT
- `pinyin_numbered` TEXT
- `gloss_en` TEXT
- `rank` INTEGER

#### `search_index` (optional but recommended)
Denormalized strings for quick LIKE matching.
- `cp` INTEGER (FK)
- `jp_keys` TEXT
- `cn_keys` TEXT
- `gloss_keys` TEXT

### Indexes (minimum)
- `CREATE INDEX idx_jp_reading ON jp_readings(reading);`
- `CREATE INDEX idx_cn_pinyin_num ON cn_readings(pinyin_numbered);`
- `CREATE INDEX idx_gloss ON jp_gloss(gloss);` (or use search_index)
- `CREATE INDEX idx_jp_words_word ON jp_words(word);`
- `CREATE INDEX idx_cn_words_trad ON cn_words(trad);`
- `CREATE INDEX idx_cn_words_simp ON cn_words(simp);`

---

## 5. Example Word Ranking Logic (MVP)

### Japanese (JMdict)
For each character:
1. collect JMdict entries whose written form contains the character
2. score each entry:
   - +100 if JMdict marks it “common” (if available via tags)
   - +20 if word length is 2–3 kanji/kana (prefer compact compounds)
   - +10 if it has a single dominant reading
   - -penalty for very long multi-sense entries (heuristic)
3. sort descending and keep top 5
4. store `word`, primary `reading_kana` (if present), and first English gloss

### Chinese (CC-CEDICT)
For each character:
1. collect CEDICT entries (trad/simp) containing the character
2. score:
   - +50 for shorter words (length 2–3 prioritized)
   - +30 if pinyin is present and well-formed
   - +10 for common-looking entries (optional heuristics; true “common” flags are not standard)
3. sort and keep top 5
4. store trad/simp, pinyin, first gloss chunk

NOTE: These heuristics are explicitly “MVP quality.” Later modules can plug in corpora frequency.

---

## 6. TUI UI/UX Specification (MVP)

### Layout (terminal)
Single screen with:
- Header line: character + codepoint + order + position
- Body: panes stacked (JP pane, CN pane), each collapsible
- Footer/status line: active mode hints and last message

Example (conceptual):
- Header: `漢  U+6F22  radical 85  strokes 13   [JP focus]  (123/9123)  order: freq`
- JP pane:
  - `JP readings: on: カン  kun: (none)`
  - `JP gloss: China; Han`
  - `JP words:`
    - `1 漢字  かんじ  Chinese character`
    - `2 漢方  かんぽう  Chinese herbal medicine`
- CN pane:
  - `CN readings: hàn (han4)`
  - `CN gloss: Han people; Han dynasty`
  - `CN words:`
    - `1 漢字 / 汉字  hànzì  Chinese character`

### Panes (MVP)
- JP pane (toggle key: `1`)
- CN pane (toggle key: `2`)
- Variants line (toggle key: `v`)
- Help overlay (toggle key: `?`)

### Keybindings (MVP)

#### Navigation
- `Right` / `j` / `Down`: next character
- `Left` / `k` / `Up`: previous character
- `Home`: first character in current ordering
- `End`: last character in current ordering

#### Focus / ordering
- `Tab`: toggle focus JP <-> CN (affects which pane is highlighted and which reading-order browse is used if enabled)
- `O`: cycle ordering:
  1) frequency/order from KANJIDIC2 if available else codepoint
  2) radical order (radical, strokes, codepoint)
  3) reading order (JP if JP focus; CN if CN focus)
  4) codepoint order

#### Search / jump
- `/`: open search prompt
  - accepts: direct character paste, `U+6F22`, hex `6F22`, kana, romaji, pinyin, meaning substring
- `Enter` on search results: jump
- `Esc`: close search overlay

#### Radical browser
- `r`: open radical picker overlay
  - list radicals (number + glyph if available)
  - choose radical -> optional stroke subfilter -> list matching characters
  - Enter to jump

#### Panes
- `1`: toggle JP pane
- `2`: toggle CN pane
- `v`: toggle variants display
- `?`: help
- `q`: quit

### Search behavior (MVP)
- If input contains a CJK character: exact match by char
- If matches `U+` prefix or hex: match codepoint
- If input looks like kana: match jp_readings and jp_words reading_kana and jp_words.word
- If input looks like romaji: best-effort convert to kana, then match as above
- If input looks like pinyin (tone numbers or tone marks): normalize to numbered; match cn_readings + cn_words pinyin + cn_words trad/simp
- Otherwise: meaning substring search across JP/CN gloss (or search_index)

### Search results
- Scrollable list of matches with a compact preview:
  - `漢 U+6F22  JP: カン  CN: han4  gloss: Han; China`
- Limit to first N results (e.g. 200), show count.

---

## 7. Error Handling and Fallbacks

- If DB is missing: show a friendly error and suggest running `make build-db` or `app --build`.
- If font profile missing: run without font filter (warn once) OR prompt user to select a font profile.
- If a character lacks JP words or CN words: show “(no examples found)” line.
- If readings missing on one side: still show the other side.
- Always keep navigation stable (never crash on missing fields).

---

## 8. CLI Interface (MVP)

### Commands
- `kanjitui` (default) runs the TUI reading `data/db.sqlite` or `$KANJITUI_DB`
- `kanjitui --db path/to/db.sqlite`
- `kanjitui --build` (optional) builds DB from local data directory
- `kanjitui --font "Noto Sans Mono CJK JP"` (optional) selects font for coverage
- `kanjitui --version`, `--help`

---

## 9. Deliverables (MVP)

- A working TUI with keybindings above
- A reproducible build step creating SQLite DB
- Minimal documentation:
  - `README.md`: install, build-db, run, keybindings
  - `data/README.md`: how to fetch sources; licensing notes
- Tests (minimum):
  - parser sanity tests for each source
  - db round-trip test for a handful of known characters

---

## 10. Future Modules (not in MVP, but architecture should allow)
- Sentences provider (modern + classical with emoji markers)
- Corpus frequency provider (BCCWJ, Wikipedia, SUBTLEX, etc.)
- Phonetic-series navigation
- Expanded variant graph traversal and visualization
- Korean readings module
- User notes / bookmarking / spaced repetition hooks