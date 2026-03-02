# Third-Party Notices

This project uses data and optional components from third parties.  
This notice is informational and does not replace upstream license terms.

## Data Sources

### Unicode Unihan
- Source: https://www.unicode.org/ucd/
- License/Terms: Unicode Terms of Use
- Reference: https://www.unicode.org/copyright.html
- Local notice: `data/licenses/UNIHAN_LICENSE.txt`

### EDRDG (KANJIDIC2, JMdict)
- Source: https://www.edrdg.org/
- License/Terms: EDRDG license terms and attribution requirements
- Reference: http://www.edrdg.org/edrdg/licence.html
- Local notice: `data/licenses/EDRDG_LICENSE.txt`

### CC-CEDICT
- Source: https://www.mdbg.net/chinese/dictionary?page=cc-cedict
- License/Terms: Creative Commons Attribution-ShareAlike (CC BY-SA)
- Local notice: `data/licenses/CC_CEDICT_LICENSE.txt`

### Tatoeba (optional sentence provider)
- Source: https://tatoeba.org/
- License/Terms: dataset-dependent; commonly CC BY 2.0 FR and/or CC0 subsets
- Project usage note: sentence rows include source/license metadata columns

## Optional Stroke Animation Integration

### StrokeOrder (optional local checkout)
- Source: https://github.com/Svampis/StrokeOrder
- Role: local SVG stroke-order assets used by `kanjitui`/`kanjigui` when available
- Detection: repository clone in `StrokeOrder/` or `KANJITUI_STROKEORDER_DIR`

### KanjiVG (via StrokeOrder assets)
- Source: https://kanjivg.tagaini.net/
- License: CC BY-SA 3.0
- Reference: https://creativecommons.org/licenses/by-sa/3.0/
- Local notice: `data/licenses/KANJIVG_CC_BY_SA_3_LICENSE.txt`

### NanoSVG (in StrokeOrder upstream project)
- Source: https://github.com/memononen/nanosvg
- License: zlib/libpng-style license

## Runtime/Platform Libraries

### PySide6 / Qt (GUI mode only)
- Source: https://doc.qt.io/qtforpython-6/
- License: open-source and commercial options; see upstream terms
- Note: if redistributing binaries with Qt/PySide6, ensure compliance with applicable Qt terms.

### SQLite
- Source: https://www.sqlite.org/
- License: Public domain

### Python
- Source: https://www.python.org/
- License: PSF License

