# Data Sources

The build step expects source files in `data/raw/` by default.

## Required files

- Unihan text files under `data/raw/unihan/` (`Unihan*.txt`)
- `data/raw/kanjidic2.xml`
- `data/raw/jmdict.xml`
- `data/raw/cedict_ts.u8`
- `data/raw/sentences.tsv` (optional; custom sentence examples provider)

## Fetch workflow

Run:

```bash
make fetch-data
```

This script downloads Unihan, CC-CEDICT, KANJIDIC2, and JMdict. EDRDG terms still apply to KANJIDIC2/JMdict.

## Sentence examples workflow

Run:

```bash
make build-sentences
```

This downloads official Tatoeba per-language exports and generates `data/raw/sentences.tsv` for optional sentence examples.
Tatoeba terms and attribution still apply.

## Licensing

See `data/licenses/` for attribution and license notes that must ship with this project.
