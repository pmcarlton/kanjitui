from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from kanjitui.search.normalize import pinyin_numbered_to_marked


LINE_RE = re.compile(r"^(\S+)\s+(\S+)\s+\[(.+?)\]\s+/(.+)/$")


@dataclass(frozen=True)
class CEDICTEntry:
    trad: str
    simp: str
    pinyin_numbered: str
    pinyin_marked: str
    glosses: list[str]


def parse_cedict(path: Path) -> list[CEDICTEntry]:
    out: list[CEDICTEntry] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        m = LINE_RE.match(line)
        if not m:
            continue

        trad = m.group(1)
        simp = m.group(2)
        pinyin_numbered = " ".join(m.group(3).strip().split()).lower()
        glosses = [chunk for chunk in m.group(4).split("/") if chunk]
        out.append(
            CEDICTEntry(
                trad=trad,
                simp=simp,
                pinyin_numbered=pinyin_numbered,
                pinyin_marked=pinyin_numbered_to_marked(pinyin_numbered),
                glosses=glosses,
            )
        )

    return out
