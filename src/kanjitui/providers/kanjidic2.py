from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from kanjitui.models import CharAnnotations


def parse_kanjidic2(path: Path) -> dict[int, CharAnnotations]:
    tree = ET.parse(path)
    root = tree.getroot()
    out: dict[int, CharAnnotations] = {}

    for char_elem in root.findall("character"):
        literal = (char_elem.findtext("literal") or "").strip()
        if not literal:
            continue
        cp = ord(literal)
        record = CharAnnotations(cp=cp, ch=literal)
        record.sources.add("kanjidic2")

        misc = char_elem.find("misc")
        if misc is not None:
            stroke_text = misc.findtext("stroke_count")
            if stroke_text and stroke_text.isdigit():
                record.strokes = int(stroke_text)
            freq_text = misc.findtext("freq")
            if freq_text and freq_text.isdigit():
                record.freq = int(freq_text)

        radical = char_elem.find("radical")
        if radical is not None:
            for rad_value in radical.findall("rad_value"):
                if rad_value.attrib.get("rad_type") == "classical":
                    text = (rad_value.text or "").strip()
                    if text.isdigit():
                        record.radical = int(text)
                        break

        rmgroup = char_elem.find("reading_meaning/rmgroup")
        if rmgroup is not None:
            for reading in rmgroup.findall("reading"):
                text = (reading.text or "").strip()
                r_type = reading.attrib.get("r_type")
                if not text:
                    continue
                if r_type == "ja_on":
                    record.jp_on.append(text)
                elif r_type == "ja_kun":
                    record.jp_kun.append(text)

            for meaning in rmgroup.findall("meaning"):
                if meaning.attrib.get("m_lang"):
                    continue
                text = (meaning.text or "").strip()
                if text:
                    record.jp_gloss.append(text)

        record.jp_on = sorted(set(record.jp_on))
        record.jp_kun = sorted(set(record.jp_kun))
        record.jp_gloss = sorted(set(record.jp_gloss))
        out[cp] = record

    return out
