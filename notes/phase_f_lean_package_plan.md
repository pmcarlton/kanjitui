# Phase F Plan (Lean Package Setup + Acknowledgements)

## Scope
1. Add first-start startup page with acknowledgements.
2. Add setup menu (`Shift+S`) to select/download data sources in-app.
3. Add acknowledgements overlay (`Shift+A`) available at any time.
4. Bundle/use StrokeOrder data from runtime package paths when available.
5. Keep TUI and GUI behavior aligned.

## Affected Modules
- `src/kanjitui/setup_resources.py` (new source catalog + download helpers + runtime path resolution)
- `src/kanjitui/tui/app.py` (startup/setup/ack overlays, keybindings, no-DB startup flow)
- `src/kanjitui/gui/window.py` + `src/kanjitui/gui/main.py` (setup dialog, overlays, startup flow)
- `src/kanjitui/cli.py` (allow startup without prebuilt DB)
- `src/kanjitui/db/user.py` (first-start persistent flag)
- `src/kanjitui/strokeorder.py` (packaged resource path detection)
- `README.md`, tests

## Data / Compatibility
- Backward compatible DB shape for main content DB.
- User DB gains `user_flags` table for persistent first-start behavior.
- No required migration action for users; table auto-creates in user DB.

## Risks
- Download endpoints may change or fail intermittently.
- Synchronous downloads can block UI while setup is running.
- Packaged-resource path detection may vary across bundle layouts.

## Validation
- `python -m compileall -q src tests`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`
- TUI smoke with empty DB path, startup page, `Shift+S` open/close, quit.
