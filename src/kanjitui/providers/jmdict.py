from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


COMMON_TAG_PREFIXES = ("news1", "ichi1", "spec1", "spec2", "gai1")


@dataclass(frozen=True)
class JMDictEntry:
    words: list[str]
    readings: list[str]
    glosses: list[str]
    common: bool


def _is_common(tags: list[str]) -> bool:
    return any(tag.startswith(COMMON_TAG_PREFIXES) for tag in tags)


def parse_jmdict(path: Path) -> list[JMDictEntry]:
    tree = ET.parse(path)
    root = tree.getroot()
    out: list[JMDictEntry] = []

    for entry in root.findall("entry"):
        words: list[str] = []
        readings: list[str] = []
        tags: list[str] = []
        glosses: list[str] = []

        for k_ele in entry.findall("k_ele"):
            keb = (k_ele.findtext("keb") or "").strip()
            if keb:
                words.append(keb)
            for ke_pri in k_ele.findall("ke_pri"):
                text = (ke_pri.text or "").strip()
                if text:
                    tags.append(text)

        for r_ele in entry.findall("r_ele"):
            reb = (r_ele.findtext("reb") or "").strip()
            if reb:
                readings.append(reb)
            for re_pri in r_ele.findall("re_pri"):
                text = (re_pri.text or "").strip()
                if text:
                    tags.append(text)

        for sense in entry.findall("sense"):
            for gloss in sense.findall("gloss"):
                lang = gloss.attrib.get("{http://www.w3.org/XML/1998/namespace}lang")
                if lang and lang != "eng":
                    continue
                text = (gloss.text or "").strip()
                if text:
                    glosses.append(text)

        if not words:
            words = readings[:]
        if not words:
            continue

        out.append(
            JMDictEntry(
                words=sorted(set(words)),
                readings=sorted(set(readings)),
                glosses=glosses,
                common=_is_common(tags),
            )
        )

    return out
