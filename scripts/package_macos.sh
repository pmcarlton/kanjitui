#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is macOS-only."
  exit 1
fi

APP_NAME="${APP_NAME:-Kanjigui}"
VENV_DIR="${VENV_DIR:-.venv-release}"
PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-.pyinstaller}"
MAKE_DMG="${MAKE_DMG:-1}"
SIGN_ADHOC="${SIGN_ADHOC:-1}"
ARCH_TAG="${ARCH_TAG:-$(uname -m)}"

VERSION="${VERSION:-$(python3 - <<'PY'
from pathlib import Path
import tomllib
project = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']
print(project['version'])
PY
)}"

echo "Packaging ${APP_NAME} v${VERSION} (${ARCH_TAG})"

echo "Preparing release virtualenv: ${VENV_DIR}"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip setuptools wheel build pyinstaller
python -m pip install -e ".[gui]"

echo "Cleaning previous packaging outputs"
rm -rf build dist "$PYINSTALLER_CONFIG_DIR"

echo "Building GUI app bundle"
PYINSTALLER_CONFIG_DIR="$PYINSTALLER_CONFIG_DIR" pyinstaller \
  --noconfirm --clean --windowed --name "$APP_NAME" \
  --add-data "LICENSE:." \
  --add-data "THIRD_PARTY_NOTICES.md:." \
  --add-data "data/licenses:data/licenses" \
  --add-data "StrokeOrder/kanji:StrokeOrder/kanji" \
  "$VENV_DIR/bin/kanjigui"

echo "Building standalone TUI binary"
PYINSTALLER_CONFIG_DIR="$PYINSTALLER_CONFIG_DIR" pyinstaller \
  --noconfirm --clean --console --onefile --name kanjitui \
  "$VENV_DIR/bin/kanjitui"

APP_BUNDLE="dist/${APP_NAME}.app"
MACOS_DIR="${APP_BUNDLE}/Contents/MacOS"
RES_DIR="${APP_BUNDLE}/Contents/Resources"

if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "Build failed: missing app bundle at $APP_BUNDLE"
  exit 2
fi

cp -f dist/kanjitui "${MACOS_DIR}/kanjitui"
chmod +x "${MACOS_DIR}/kanjitui"

LAUNCHER_NAME="${APP_NAME}-launcher"
cat > "${MACOS_DIR}/${LAUNCHER_NAME}" <<EOF
#!/bin/bash
set -euo pipefail
APP_ROOT="\$(cd "\$(dirname "\$0")/.." && pwd)"
GUI_BIN="\$APP_ROOT/MacOS/${APP_NAME}"
CLI_BIN="\$APP_ROOT/MacOS/kanjitui"
SUPPORT_DIR="\$HOME/Library/Application Support/kanjitui"
mkdir -p "\$SUPPORT_DIR/raw" "\$SUPPORT_DIR/strokeorder"
export KANJITUI_DATA_DIR="\$SUPPORT_DIR/raw"
export KANJITUI_STROKEORDER_DIR="\$SUPPORT_DIR/strokeorder"
if [[ "\${1:-}" == "--cli" ]]; then
  shift
  exec "\$CLI_BIN" --db "\$SUPPORT_DIR/db.sqlite" --user-db "\$SUPPORT_DIR/user.sqlite" "\$@"
fi
exec "\$GUI_BIN" --db "\$SUPPORT_DIR/db.sqlite" --user-db "\$SUPPORT_DIR/user.sqlite" "\$@"
EOF
chmod +x "${MACOS_DIR}/${LAUNCHER_NAME}"
plutil -replace CFBundleExecutable -string "$LAUNCHER_NAME" "${APP_BUNDLE}/Contents/Info.plist"

cat > "${RES_DIR}/LEAN_SETUP_SIZE.txt" <<'EOF'
Lean setup disk guidance (approximate):
- Source downloads + extracted raw data: ~200 MiB
- Built SQLite DB: ~100 MiB
- Optional sentence payloads can add ~30-40 MiB
- Typical full data footprint: ~300-400 MiB
- Reference install size from development machine: ~377 MiB (data/)
EOF

if [[ "$SIGN_ADHOC" == "1" ]]; then
  echo "Applying ad-hoc code signature"
  codesign --force --deep --sign - "$APP_BUNDLE"
  codesign --verify --deep --strict "$APP_BUNDLE"
fi

if [[ "$MAKE_DMG" == "1" ]]; then
  DMG_PATH="dist/${APP_NAME}-lean-${VERSION}-${ARCH_TAG}.dmg"
  echo "Creating DMG: ${DMG_PATH}"
  hdiutil create -volname "${APP_NAME}" -srcfolder "$APP_BUNDLE" -ov -format UDZO "$DMG_PATH"
  shasum -a 256 "$DMG_PATH" | tee "${DMG_PATH}.sha256"
fi

echo
echo "Package complete."
echo "GUI launcher: ${APP_BUNDLE}/Contents/MacOS/${LAUNCHER_NAME}"
echo "Advanced-user TUI binary: ${APP_BUNDLE}/Contents/MacOS/kanjitui"
echo "After copying to /Applications, shell-link example:"
echo "  ln -sf /Applications/${APP_NAME}.app/Contents/MacOS/kanjitui /usr/local/bin/kanjitui"
echo "Disk guidance file: ${RES_DIR}/LEAN_SETUP_SIZE.txt"
