# Phase A Groundwork Plan

## Scope
Implement foundational infrastructure for upcoming feature waves:
1. DB migration framework
2. Typed config layering (defaults + config file + env + CLI)
3. Provider registry scaffolding
4. TUI input routing abstraction

## Affected Modules
- `src/kanjitui/db/`: migrations + schema bootstrap wiring
- `src/kanjitui/providers/`: provider registry
- `src/kanjitui/config.py`: centralized configuration resolution
- `src/kanjitui/cli.py`: use typed config and provider selection
- `src/kanjitui/tui/`: router abstraction integrated into key dispatch
- `tests/`: new unit tests for migration/config/registry/router

## Data Format / Compatibility
- Add `schema_migrations` table for versioned schema management.
- Keep all existing data tables and columns unchanged in migration v1.
- Build path remains deterministic; DB rebuild still supported.

## Risks
- CLI regression from changed defaults precedence.
- Migration behavior on pre-existing DBs without version table.
- Over-refactoring TUI key handling could alter key semantics.

## Validation
- Unit tests for config precedence, migration apply/rebuild, provider registry, key router dispatch.
- Existing parser/integration tests must still pass.
- CLI smoke checks for `--help` and build using fixtures.
