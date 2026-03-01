from __future__ import annotations


def kangxi_radical_glyph(radical_number: int) -> str:
    if 1 <= radical_number <= 214:
        return chr(0x2F00 + radical_number - 1)
    return "?"


def all_kangxi_radical_numbers() -> list[int]:
    return list(range(1, 215))
