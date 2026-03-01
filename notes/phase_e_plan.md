# Phase E Plan

## Scope
1. User workspace persistence in separate user DB:
   - bookmarks
   - notes
   - saved queries
2. TUI actions for user workspace management.
3. CC-oriented image links panel with browser open action.

## Affected modules
- `src/kanjitui/db/user.py` (new)
- `src/kanjitui/cli.py`, `src/kanjitui/tui/app.py`
- `src/kanjitui/tui/imagelinks.py` (new)
- tests for user DB and image link generation

## Validation
- Unit tests for user store CRUD and image link generation.
- Existing integration tests remain green.
