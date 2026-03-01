#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${1:-data/raw}"
mkdir -p "$OUT_DIR/unihan"

download_file() {
  local dest="$1"
  local url="$2"
  echo "Fetching $(basename "$dest")..."
  curl -L -o "$dest" "$url"
}

download_file "$OUT_DIR/Unihan.zip" "https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip"

if command -v unzip >/dev/null 2>&1; then
  unzip -o "$OUT_DIR/Unihan.zip" -d "$OUT_DIR/unihan" >/dev/null
  echo "Extracted Unihan files into $OUT_DIR/unihan"
else
  echo "unzip not found; extract $OUT_DIR/Unihan.zip manually into $OUT_DIR/unihan"
fi

download_file "$OUT_DIR/cedict_ts.u8.gz" "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz"
if command -v gzip >/dev/null 2>&1; then
  gzip -df "$OUT_DIR/cedict_ts.u8.gz"
elif [[ -f "$OUT_DIR/cedict_ts.u8.gz" ]]; then
  echo "gzip not found; decompress $OUT_DIR/cedict_ts.u8.gz manually to $OUT_DIR/cedict_ts.u8"
fi

echo "Fetching EDRDG sources (KANJIDIC2/JMdict)..."
download_file "$OUT_DIR/kanjidic2.xml.gz" "ftp://ftp.edrdg.org/pub/Nihongo/kanjidic2.xml.gz"
download_file "$OUT_DIR/jmdict.xml.gz" "ftp://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz"

if command -v gzip >/dev/null 2>&1; then
  gzip -df "$OUT_DIR/kanjidic2.xml.gz"
  gzip -df "$OUT_DIR/jmdict.xml.gz"
  if [[ -f "$OUT_DIR/JMdict_e" ]]; then
    mv "$OUT_DIR/JMdict_e" "$OUT_DIR/jmdict.xml"
  fi
elif [[ -f "$OUT_DIR/kanjidic2.xml.gz" || -f "$OUT_DIR/jmdict.xml.gz" ]]; then
  echo "gzip not found; decompress EDRDG .gz files manually:"
  echo "  $OUT_DIR/kanjidic2.xml.gz -> $OUT_DIR/kanjidic2.xml"
  echo "  $OUT_DIR/jmdict.xml.gz -> $OUT_DIR/jmdict.xml"
fi

echo "Fetched all source datasets into $OUT_DIR"
echo "EDRDG attribution and license terms still apply to KANJIDIC2/JMdict."
