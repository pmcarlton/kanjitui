from __future__ import annotations

import unicodedata

JP_DESCRIPTIVE_NAMES: dict[int, str] = {
    8: "なべぶた",
    9: "にんべん",
    12: "はちがしら",
    13: "けいがまえ",
    15: "にすい",
    18: "りっとう",
    20: "つつみがまえ",
    22: "はこがまえ",
    23: "かくしがまえ",
    26: "ふしづくり",
    27: "がんだれ",
    30: "くちへん",
    31: "くにがまえ",
    32: "つちへん",
    38: "おんなへん",
    40: "うかんむり",
    44: "しかばね",
    47: "まがりかわ",
    50: "はばへん",
    53: "まだれ",
    54: "いんにょう",
    60: "ぎょうにんべん",
    61: "りっしんべん",
    63: "とだれ",
    64: "てへん",
    66: "ぼくづくり",
    69: "おのづくり",
    72: "にちへん",
    74: "つきへん",
    75: "きへん",
    78: "がつへん",
    85: "さんずい",
    86: "ひへん",
    93: "うしへん",
    94: "けものへん",
    96: "たまへん",
    102: "たへん",
    104: "やまいだれ",
    109: "めへん",
    111: "やへん",
    112: "いしへん",
    113: "しめすへん",
    115: "のぎへん",
    116: "あなかんむり",
    118: "たけかんむり",
    119: "こめへん",
    120: "いとへん",
    130: "にくづき",
    137: "ふねへん",
    140: "くさかんむり",
    141: "とらがしら",
    142: "むしへん",
    145: "ころもへん",
    149: "ごんべん",
    153: "むじなへん",
    154: "かいへん",
    157: "あしへん",
    159: "くるまへん",
    162: "しんにょう",
    163: "おおざと",
    164: "とりへん",
    167: "かねへん",
    169: "もんがまえ",
    170: "こざとへん",
    173: "あめかんむり",
    177: "かわへん",
    181: "おおがい",
    184: "しょくへん",
    187: "うまへん",
    195: "うおへん",
    196: "とりへん",
}

CN_DESCRIPTIVE_NAMES: dict[int, str] = {
    8: "京字头",
    9: "单人旁",
    12: "八字头",
    13: "同字框",
    15: "两点水",
    18: "立刀旁",
    20: "包字头",
    22: "匚字框",
    23: "匸字框",
    26: "单耳旁",
    27: "厂字旁",
    30: "口字旁",
    31: "国字框",
    32: "提土旁",
    38: "女字旁",
    40: "宝盖头",
    44: "尸字头",
    53: "广字旁",
    54: "建之底",
    57: "弓字旁",
    60: "双人旁",
    61: "竖心旁",
    64: "提手旁",
    66: "反文旁",
    74: "月字旁",
    85: "三点水",
    86: "火字旁",
    94: "反犬旁",
    96: "王字旁",
    104: "病字旁",
    109: "目字旁",
    112: "石字旁",
    113: "示字旁",
    115: "禾木旁",
    116: "穴宝盖",
    118: "竹字头",
    119: "米字旁",
    120: "绞丝旁",
    130: "肉月旁",
    140: "草字头",
    141: "虎字头",
    142: "虫字旁",
    145: "衣字旁",
    149: "言字旁",
    154: "贝字旁",
    159: "车字旁",
    162: "走之底",
    163: "右耳旁",
    167: "金字旁",
    169: "门字框",
    170: "左耳旁",
    173: "雨字头",
    181: "页字旁",
    184: "食字旁",
    187: "马字旁",
    195: "鱼字旁",
    196: "鸟字旁",
}


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


def kangxi_radical_jp_name(radical_number: int) -> str | None:
    return JP_DESCRIPTIVE_NAMES.get(radical_number)


def kangxi_radical_cn_name(radical_number: int) -> str | None:
    return CN_DESCRIPTIVE_NAMES.get(radical_number)
