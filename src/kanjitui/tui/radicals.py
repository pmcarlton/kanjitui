from __future__ import annotations

import unicodedata


def kangxi_radical_glyph(radical_number: int) -> str:
    if 1 <= radical_number <= 214:
        return chr(0x2F00 + radical_number - 1)
    return "?"


def all_kangxi_radical_numbers() -> list[int]:
    return list(range(1, 215))


def kangxi_radical_base_char(radical_number: int) -> str:
    glyph = kangxi_radical_glyph(radical_number)
    if glyph == "?":
        return "?"
    return unicodedata.normalize("NFKC", glyph)


def kangxi_radical_english_name(radical_number: int) -> str:
    glyph = kangxi_radical_glyph(radical_number)
    if glyph == "?":
        return "Unknown"
    name = unicodedata.name(glyph, "Unknown")
    prefix = "KANGXI RADICAL "
    if name.startswith(prefix):
        name = name[len(prefix) :]
    return name.title()
