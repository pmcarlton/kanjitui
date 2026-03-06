# macOS Standalone Packaging

This project supports a lean standalone macOS package:

- GUI app bundle (`Kanjigui.app`)
- bundled advanced-user TUI binary inside the app bundle
- no pre-bundled dictionary DB (users download sources and build locally)

## Build

```bash
make package-macos
```

This runs `scripts/package_macos.sh` and produces:

- `dist/Kanjigui.app`
- `dist/Kanjigui-lean-<version>-<arch>.dmg` (default)
- `dist/Kanjigui-lean-<version>-<arch>.dmg.sha256`

## App Layout

Key paths inside the app:

- GUI launcher wrapper: `Kanjigui.app/Contents/MacOS/Kanjigui-launcher`
- GUI executable: `Kanjigui.app/Contents/MacOS/Kanjigui`
- TUI executable: `Kanjigui.app/Contents/MacOS/kanjitui`
- license notices: `Kanjigui.app/Contents/Resources/THIRD_PARTY_NOTICES.md`
- setup size guidance: `Kanjigui.app/Contents/Resources/LEAN_SETUP_SIZE.txt`

## Lean Runtime Paths

The launcher sets default writable paths to:

- `~/Library/Application Support/kanjitui/db.sqlite`
- `~/Library/Application Support/kanjitui/user.sqlite`
- `~/Library/Application Support/kanjitui/raw/`
- `~/Library/Application Support/kanjitui/strokeorder/`

## Expose TUI in Shell (Optional)

After installing to `/Applications`:

```bash
ln -sf /Applications/Kanjigui.app/Contents/MacOS/kanjitui /usr/local/bin/kanjitui
```

## Disk Footprint Guidance

Approximate data footprint for lean setup:

- raw source downloads and extracted files: about `200 MiB`
- built DB: about `100 MiB`
- optional sentence payloads: about `30-40 MiB`
- typical full lean data footprint: about `300-400 MiB`
- reference install in development: about `377 MiB` (`data/`)
