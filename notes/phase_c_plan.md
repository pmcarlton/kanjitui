# Phase C Plan

## Scope
1. Per-field provenance/confidence storage and display toggle.
2. Variant graph traversal/query and TUI overlay.
3. Normalization plugin architecture in search pipeline.
4. Export commands for character detail and query results (JSON/CSV).

## Affected Modules
- DB migrations/build/query
- Search normalization/query/engine
- CLI argument handling
- TUI overlays and key routing

## Validation
- Unit tests for migration/versioning remain green.
- New tests for normalizer plugin selection and export output formats.
- Integration smoke: build fixtures, export query, export char.
