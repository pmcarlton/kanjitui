# Agents.md

## Purpose
This repository is built with an “agentic” workflow: work autonomously, keep changes safe and reviewable, and optimize for iteration and clarity.

---

## Operating Principles

### 1) Plan before coding
- Before implementing a feature, write a short plan in the PR/commit message or in `notes/` (if needed).
- Identify:
  - affected modules
  - data format changes
  - risks (performance, breaking behavior, licensing)
  - how to validate success

### 2) Make no breaking changes by default
- Backwards compatibility is the default.
- If a breaking change is unavoidable:
  - isolate it to a single commit
  - document it clearly in `CHANGELOG.md` and `README.md`
  - provide a migration step (e.g., rebuild DB) and a clear error message

### 3) Small, reviewable commits
- Git commit **each major change**.
- Each commit must:
  - build successfully
  - have a meaningful message (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`)
  - avoid mixing unrelated changes

### 4) Prefer modularity over cleverness
- Keep parsing, normalization, DB building, and UI separate.
- New data sources should be implemented as providers/modules, not entangled into UI code.
- Avoid premature optimization, but keep data structures straightforward and indexable.

### 5) Ask disambiguating questions when necessary
Ask questions only when ambiguity materially affects correctness or would cause rework. Examples:
- Which font should be the default coverage profile on macOS/Linux?
- Should “romaji search” accept Kunrei-shiki variants or only Hepburn?
- Preferred TUI framework (Textual vs curses vs ratatui) if multiple are viable.

If blocked and a reasonable default exists, proceed with the default and document the assumption.

---

## Quality Bar

### Functional expectations
- App runs offline once DB is built.
- Missing data never crashes the UI.
- Search and browse remain responsive (target: <50ms per navigation step on a typical laptop).
- Clear help screen and keybindings.

### Testing expectations (minimum viable)
- Unit tests for each parser:
  - can parse a small sample file
  - produces expected fields for a few known characters
- Integration test:
  - build DB from sample inputs
  - query DB for a known character and validate output shape

### Logging
- Use structured logging where appropriate.
- Runtime UI should show concise errors; full trace goes to logs only.

---

## Repository Hygiene

### Data and licensing
- Do not commit large upstream datasets unless explicitly required.
- Prefer `make fetch-data` / `scripts/fetch_data.*` that downloads sources.
- Preserve and display required attributions and license texts.
- Keep a `data/licenses/` directory containing:
  - Unihan license/terms (as applicable)
  - EDRDG license text for KANJIDIC2/JMdict
  - CC-CEDICT license text

### Configuration
- Provide sensible defaults but allow overrides via:
  - CLI flags
  - environment variables
  - config file (optional, later)

### Documentation
- Keep `README.md` current with:
  - install instructions
  - how to build DB
  - how to run TUI
  - keybindings and search syntax
- Add “known limitations” section for MVP.

---

## Implementation Guidelines

### Architecture
- `src/` (or equivalent) should separate:
  - `providers/` (unihan, kanjidic2, jmdict, cedict, fontcov)
  - `db/` (schema, migrations, queries)
  - `tui/` (layout, panes, input handling)
  - `search/` (parsing user input, normalization, query building)

### Performance and safety
- Never block the UI thread on heavy IO.
- Cache current character record and prefetch adjacent records when browsing.
- Limit search results displayed; show count.

### Determinism
- Build output must be deterministic given the same inputs.
- Ranking heuristics should be stable (no randomness unless seeded and documented).

---

## Definition of Done (per feature)
A feature is “done” when:
1. Implemented with minimal coupling
2. Covered by at least one test (unit or integration)
3. Documented (README/help if user-visible)
4. Committed as a coherent unit with a clear message

---

## Communication Style for the Agent
- Be direct and specific.
- When uncertain, state assumptions explicitly.
- Prefer concrete examples (e.g., `U+6F22`, `han4`, `かんじ`).
- Avoid long debates; converge on implementable defaults and iterate.

---