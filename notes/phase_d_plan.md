# Phase D Plan

## Scope
1. Components + phonetic-series data model and TUI overlays.
2. Frequency profile table and ordering controls.
3. Sentence examples provider/table/pane.
4. Advanced radical browser stroke subfilter.

## Affected modules
- `providers/unihan.py`, new `providers/sentences.py`, provider registry
- DB migrations/build/query
- CLI/config for optional sentences input
- TUI keybindings/panes/ordering/radical flow

## Validation
- Unit tests for sentences parser and frequency/radical query helpers.
- Existing integration tests remain green.
- Smoke builds with and without optional sentences file.
