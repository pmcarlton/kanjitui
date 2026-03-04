#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python3}"
DB_PATH="${DB_PATH:-data/db.sqlite}"
FONT_SPEC="${FONT_SPEC:-}"
QUICK=0
RUN_DOCS=1

usage() {
  cat <<'EOF'
Usage: scripts/release_smoke.sh [options]

Options:
  --quick            Run a reduced pytest subset.
  --no-docs          Skip mkdocs build check.
  --db PATH          DB path for export/no-tofu checks (default: data/db.sqlite).
  --font SPEC        Font name/path for no-tofu check (optional).
  --help             Show this help.

Environment overrides:
  PYTHON, DB_PATH, FONT_SPEC

Examples:
  scripts/release_smoke.sh
  scripts/release_smoke.sh --db data/db.sqlite --font "/Users/me/Library/Fonts/BabelStoneHan.ttf"
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick)
      QUICK=1
      shift
      ;;
    --no-docs)
      RUN_DOCS=0
      shift
      ;;
    --db)
      DB_PATH="$2"
      shift 2
      ;;
    --font)
      FONT_SPEC="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

run_step() {
  echo
  echo "==> $1"
  shift
  "$@"
}

echo "release_smoke configuration:"
echo "  PYTHON=${PYTHON}"
echo "  DB_PATH=${DB_PATH}"
echo "  FONT_SPEC=${FONT_SPEC:-<none>}"
echo "  QUICK=${QUICK}"
echo "  RUN_DOCS=${RUN_DOCS}"

if ! "$PYTHON" -m pytest --version >/dev/null 2>&1; then
  CANDIDATES=(".venv/bin/python" ".venv-release/bin/python" "python3")
  FOUND=""
  for cand in "${CANDIDATES[@]}"; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -m pytest --version >/dev/null 2>&1; then
      FOUND="$cand"
      break
    fi
  done
  if [[ -n "$FOUND" ]]; then
    echo "${PYTHON} lacks pytest; falling back to ${FOUND}"
    PYTHON="$FOUND"
  else
    echo "pytest is unavailable for ${PYTHON}. Install test deps or create a venv with test dependencies." >&2
    exit 2
  fi
fi

mapfile -t PY_FILES < <(rg --files src scripts tests -g '*.py')
if [[ "${#PY_FILES[@]}" -eq 0 ]]; then
  echo "No Python files found for compile check." >&2
  exit 2
fi
run_step "Compile Python files" "$PYTHON" -m py_compile "${PY_FILES[@]}"

if [[ "$QUICK" -eq 1 ]]; then
  run_step "Run quick pytest subset" env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$PYTHON" -m pytest -q \
    tests/test_filtering.py \
    tests/test_related_nav.py \
    tests/test_tui_navigation.py \
    tests/test_gui_state.py \
    tests/test_setup_resources.py
else
  run_step "Run full pytest suite" env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$PYTHON" -m pytest -q
fi

if [[ "$RUN_DOCS" -eq 1 ]]; then
  if ! command -v mkdocs >/dev/null 2>&1; then
    echo "mkdocs not found; install it or pass --no-docs." >&2
    exit 2
  fi
  run_step "Build docs" mkdocs build -q -d /tmp/kanjitui_docs_smoke
fi

if [[ -f "$DB_PATH" ]]; then
  CHAR_OUT="/tmp/kanjitui_smoke_char.json"
  QUERY_OUT="/tmp/kanjitui_smoke_query.json"
  run_step "DB export smoke (char)" env PYTHONPATH=src "$PYTHON" -m kanjitui --db "$DB_PATH" --export-char 漢 --export-format json --export-out "$CHAR_OUT"
  run_step "DB export smoke (query)" env PYTHONPATH=src "$PYTHON" -m kanjitui --db "$DB_PATH" --export-query 漢 --export-format json --export-out "$QUERY_OUT"
  run_step "Validate export artifacts" "$PYTHON" -c '
import json
import sys
from pathlib import Path

char_out = Path(sys.argv[1])
query_out = Path(sys.argv[2])
for path in (char_out, query_out):
    if not path.exists():
        raise SystemExit(f"Missing export artifact: {path}")
    if path.stat().st_size <= 1:
        raise SystemExit(f"Export artifact is empty: {path}")

char_payload = json.loads(char_out.read_text(encoding="utf-8"))
query_payload = json.loads(query_out.read_text(encoding="utf-8"))
cp = char_payload.get("cp")
if not isinstance(cp, int):
    raise SystemExit("Char export missing expected cp field")
if not isinstance(query_payload, list):
    raise SystemExit("Query export is not a JSON list")
if not query_payload:
    raise SystemExit("Query export returned zero rows for control query")
print(f"validated exports: char cp=U+{cp:04X}, query rows={len(query_payload)}")
' "$CHAR_OUT" "$QUERY_OUT"
else
  echo
  echo "==> DB export/no-tofu checks skipped: DB not found at $DB_PATH"
fi

if [[ -n "$FONT_SPEC" ]]; then
  if [[ ! -f "$DB_PATH" ]]; then
    echo "No-tofu check requested but DB not found at $DB_PATH" >&2
    exit 2
  fi
  run_step "No-tofu check (font coverage vs chars table)" env PYTHONPATH=src "$PYTHON" -c '
import sqlite3
import sys
from pathlib import Path
from kanjitui.providers.fontcov import compute_font_coverage_with_path

db_path = Path(sys.argv[1])
font_spec = sys.argv[2]

coverage, font_path, error = compute_font_coverage_with_path(font_spec)
if coverage is None:
    print(f"Failed to compute font coverage for {font_spec!r}: {error}", file=sys.stderr)
    sys.exit(1)

conn = sqlite3.connect(db_path)
rows = conn.execute("SELECT cp FROM chars").fetchall()
conn.close()

missing = [cp for (cp,) in rows if cp not in coverage]
print(f"Resolved font: {font_path}")
print(f"DB chars: {len(rows)}")
print(f"Font covered chars in DB: {len(rows) - len(missing)}")
if missing:
    sample = ", ".join(f"U+{cp:04X}" for cp in missing[:20])
    print(f"Missing in font coverage: {len(missing)} (sample: {sample})", file=sys.stderr)
    print(
        "Rebuild DB with this same font filter enabled, then rerun no-tofu check.",
        file=sys.stderr,
    )
    sys.exit(1)
print("No-tofu check passed: all DB chars are covered by the font.")
' "$DB_PATH" "$FONT_SPEC"
fi

echo
echo "release_smoke: PASS"
