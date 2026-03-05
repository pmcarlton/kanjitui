# Release Checklist (Beta -> 1.0)

This checklist defines release gates for each checkpoint from beta hardening to `1.0`.

Primary goals:

- prevent early abandonment (especially startup lag, hangs, tofu glyphs)
- keep TUI and GUI behavior aligned
- catch edge-case breakage before tagging releases

## 1.0 Hardening Stack (Working List)

- [x] Visible `Show startup on launch` toggle in settings (TUI + GUI).
- [x] Recent-query UX in user overlay:
  - space-separated display
  - selectable
  - `Delete` removes selected query
  - `Enter` jumps via selected query
  - `c` clears history
- [ ] Cleanup legacy/dead persisted keys (including old `font_warning_dismissed_*` flags).
- [ ] Surface reading-filter scope in ambiguous contexts.
- [ ] Modal-state hardening pass for hidden/scattered persistent states.

## Global Gates (Every Checkpoint)

All checkpoints must satisfy these baseline gates:

1. TUI/GUI parity for shared actions (search, nav, filters, overlays, bookmarks).
2. No crash on missing optional data; show concise UI message and continue.
3. Performance guardrails checked against baseline (startup + nav).
4. License/attribution overlays remain accurate for enabled sources.
5. Filter-empty state is explicit ("all glyphs filtered out"), not a DB-missing message.

## 0.1.1 Beta Patch: Stability + No-Tofu Guarantee

Required outcomes:

1. Rebuild with font coverage filter works with both font name and absolute font path.
2. Font-filtered DB excludes unsupported glyphs consistently.
3. Cold start and browse performance stay within target range.
4. Long browsing sessions do not hang.

Exit tests:

1. Rebuild via TUI and GUI advanced/setup flow succeeds.
2. `make release-smoke DB_PATH=<db> FONT_SPEC=<font>` passes.
3. 30-minute manual browse soak in both modes has no freeze/crash.

Edge/conflict checks:

1. Missing font path or unresolved font family.
2. Terminal font differs from rebuild filter font (warn clearly).
3. Rebuild interruption/retry is recoverable.

## 0.2 Beta: Study Loop v1 (Bookmark Reveal)

Required outcomes:

1. In bookmark navigation mode, `Right` reveals readings, `Left` reveals gloss.
2. `Up`/`Down` moves bookmark selection, `Enter` jumps.
3. Only one study/bookmark overlay is active at a time.

Exit tests:

1. Identical key semantics in TUI and GUI.
2. Correct handling of JP-only, CN-only, both, and no-reading entries.
3. No stale reveal text after rapid selection changes.

Edge/conflict checks:

1. Behavior when phonetic/variant overlays are open.
2. Interaction with "hide no-reading" filter.

## 0.2.1 Beta Patch: Named Bookmark Sets

Required outcomes:

1. Create/switch/delete named sets.
2. Exactly one active set at a time.
3. Import/export is deterministic and stable.

Exit tests:

1. Roundtrip import/export preserves order and metadata.
2. Active set persists across restart.
3. Invalid import files fail with clear message and no data loss.

Edge/conflict checks:

1. Imported codepoints missing in current DB.
2. Deleting active set while bookmark overlay is open.

## 0.3 Beta: Language-Targeted Example Routing

Required outcomes:

1. JP-only mode prioritizes JP examples.
2. CN-only mode prioritizes CN examples.
3. Both mode shows mixed policy consistently.

Exit tests:

1. Routing correctness with JP-only, CN-only, mixed, and missing corpora states.
2. Fallback messaging is accurate and actionable.

## 0.4 Beta: Filter UX Maturity

Required outcomes:

1. Stable composable filters (joyo/grade/traditional/simplified/has-words/etc).
2. Saved named presets are reliable.
3. Clear filtered-empty state messaging.

Exit tests:

1. Single and pairwise filter combination checks.
2. Preset save/load/delete survives restart.
3. When current glyph is filtered out, cursor advances to next valid glyph.

Edge/conflict checks:

1. Contradictory filter combinations.
2. Filter changes while overlays are open.

## 0.5 Beta: Modal/Focus Coherence

Required outcomes:

1. Active input context is obvious via consistent visual treatment.
2. Overlay toggle keys close same overlay in both modes.
3. Up/Down ownership is deterministic (e.g., phonetic overlay vs related panel).

Exit tests:

1. Modal transition matrix passes (open/close from each valid state).
2. No accidental key leakage to hidden/inactive overlays.

## 0.9 RC: Packaging + Setup Reliability

Required outcomes:

1. First-run setup can download/extract/build automatically.
2. Setup shows meaningful progress and retry behavior.
3. Source acknowledgements and license links are available in-app.

Exit tests:

1. Fresh-install path to first glyph works without manual rescue.
2. Retry/fallback on blocked hosts or unavailable resources.
3. Re-running setup after partial success is idempotent.

## 1.0 Stable

Required outcomes:

1. No open P0/P1 issues.
2. Full end-to-end acceptance pass in TUI and GUI.
3. Documentation, key reference, and known limitations are current.

Exit tests:

1. Release smoke passes twice on clean worktree.
2. Manual acceptance checklist passes on target platform.

## Automated Baseline Check

Use the smoke script for every checkpoint:

```bash
make release-smoke
```

Optional no-tofu verification against a specific DB/font:

```bash
make release-smoke DB_PATH=data/db.sqlite FONT_SPEC="/Users/you/Library/Fonts/BabelStoneHan.ttf"
```

The no-tofu check asserts that every codepoint in `chars` exists in the selected font's coverage map.
