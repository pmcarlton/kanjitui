from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SentenceEntry:
    cp: int
    lang: str
    text: str
    reading: str
    gloss: str
    source: str
    license: str


def parse_sentences_tsv(path: Path) -> list[SentenceEntry]:
    out: list[SentenceEntry] = []
    if not path.exists():
        return out

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        cp_token, lang, text, reading, gloss, source, license_name = parts[:7]
        cp_token = cp_token.strip()
        if cp_token.lower().startswith("u+"):
            cp_token = cp_token[2:]
        try:
            cp = int(cp_token, 16)
        except ValueError:
            continue
        out.append(
            SentenceEntry(
                cp=cp,
                lang=lang.strip().lower(),
                text=text.strip(),
                reading=reading.strip(),
                gloss=gloss.strip(),
                source=source.strip(),
                license=license_name.strip(),
            )
        )
    return out
