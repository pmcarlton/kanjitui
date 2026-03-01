# Data Sources

The build step expects source files in `data/raw/` by default.

## Required files

- Unihan text files under `data/raw/unihan/` (`Unihan*.txt`)
- `data/raw/kanjidic2.xml`
- `data/raw/jmdict.xml`
- `data/raw/cedict_ts.u8`

## Fetch workflow

Run:

```bash
make fetch-data
```

This script downloads Unihan, CC-CEDICT, KANJIDIC2, and JMdict. EDRDG terms still apply to KANJIDIC2/JMdict.

## Licensing

See `data/licenses/` for attribution and license notes that must ship with this project.
