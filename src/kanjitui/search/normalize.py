from __future__ import annotations

import re
import unicodedata


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
KANA_RE = re.compile(r"^[\u3040-\u30ffー\s]+$")
HEX_RE = re.compile(r"^(?:U\+)?([0-9A-Fa-f]{4,6})$")
ROMAJI_RE = re.compile(r"^[a-zA-Z\-\s']+$")


ROMAJI_TO_HIRA = {
    "kya": "きゃ",
    "kyu": "きゅ",
    "kyo": "きょ",
    "sha": "しゃ",
    "shu": "しゅ",
    "sho": "しょ",
    "cha": "ちゃ",
    "chu": "ちゅ",
    "cho": "ちょ",
    "nya": "にゃ",
    "nyu": "にゅ",
    "nyo": "にょ",
    "hya": "ひゃ",
    "hyu": "ひゅ",
    "hyo": "ひょ",
    "mya": "みゃ",
    "myu": "みゅ",
    "myo": "みょ",
    "rya": "りゃ",
    "ryu": "りゅ",
    "ryo": "りょ",
    "gya": "ぎゃ",
    "gyu": "ぎゅ",
    "gyo": "ぎょ",
    "ja": "じゃ",
    "ju": "じゅ",
    "jo": "じょ",
    "bya": "びゃ",
    "byu": "びゅ",
    "byo": "びょ",
    "pya": "ぴゃ",
    "pyu": "ぴゅ",
    "pyo": "ぴょ",
    "shi": "し",
    "chi": "ち",
    "tsu": "つ",
    "fu": "ふ",
    "ji": "じ",
    "ka": "か",
    "ki": "き",
    "ku": "く",
    "ke": "け",
    "ko": "こ",
    "sa": "さ",
    "su": "す",
    "se": "せ",
    "so": "そ",
    "ta": "た",
    "te": "て",
    "to": "と",
    "na": "な",
    "ni": "に",
    "nu": "ぬ",
    "ne": "ね",
    "no": "の",
    "ha": "は",
    "hi": "ひ",
    "he": "へ",
    "ho": "ほ",
    "ma": "ま",
    "mi": "み",
    "mu": "む",
    "me": "め",
    "mo": "も",
    "ya": "や",
    "yu": "ゆ",
    "yo": "よ",
    "ra": "ら",
    "ri": "り",
    "ru": "る",
    "re": "れ",
    "ro": "ろ",
    "wa": "わ",
    "wo": "を",
    "ga": "が",
    "gi": "ぎ",
    "gu": "ぐ",
    "ge": "げ",
    "go": "ご",
    "za": "ざ",
    "zu": "ず",
    "ze": "ぜ",
    "zo": "ぞ",
    "da": "だ",
    "de": "で",
    "do": "ど",
    "ba": "ば",
    "bi": "び",
    "bu": "ぶ",
    "be": "べ",
    "bo": "ぼ",
    "pa": "ぱ",
    "pi": "ぴ",
    "pu": "ぷ",
    "pe": "ぺ",
    "po": "ぽ",
    "a": "あ",
    "i": "い",
    "u": "う",
    "e": "え",
    "o": "お",
    "n": "ん",
}

HIRA_TO_ROMAJI = {hira: roma for roma, hira in ROMAJI_TO_HIRA.items()}


PINYIN_MARKS = {
    "a": "āáǎà",
    "e": "ēéěè",
    "i": "īíǐì",
    "o": "ōóǒò",
    "u": "ūúǔù",
    "v": "ǖǘǚǜ",
}

MARK_TO_BASE_TONE: dict[str, tuple[str, int]] = {}
for base, marks in PINYIN_MARKS.items():
    for idx, mark in enumerate(marks, start=1):
        MARK_TO_BASE_TONE[mark] = ("ü" if base == "v" else base, idx)


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def contains_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text))


def parse_codepoint_token(text: str) -> int | None:
    m = HEX_RE.match(text.strip())
    if not m:
        return None
    try:
        return int(m.group(1), 16)
    except ValueError:
        return None


def is_kana_text(text: str) -> bool:
    t = text.strip()
    return bool(t) and bool(KANA_RE.fullmatch(t))


def katakana_to_hiragana(text: str) -> str:
    out = []
    for ch in text:
        cp = ord(ch)
        if 0x30A1 <= cp <= 0x30F6:
            out.append(chr(cp - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def normalize_kana(text: str) -> str:
    return nfc(katakana_to_hiragana(text.strip()))


def looks_like_romaji(text: str) -> bool:
    t = text.strip()
    return bool(t) and bool(ROMAJI_RE.fullmatch(t))


def romaji_to_hiragana(text: str) -> str:
    s = text.lower().strip().replace(" ", "")
    s = s.replace("-", "")
    out: list[str] = []
    i = 0
    keys = sorted(ROMAJI_TO_HIRA.keys(), key=len, reverse=True)
    while i < len(s):
        if i + 1 < len(s) and s[i] == s[i + 1] and s[i] not in "aeioun":
            out.append("っ")
            i += 1
            continue

        matched = False
        for key in keys:
            if s.startswith(key, i):
                out.append(ROMAJI_TO_HIRA[key])
                i += len(key)
                matched = True
                break
        if matched:
            continue

        # Fallback pass-through keeps best-effort behavior.
        out.append(s[i])
        i += 1
    return "".join(out)


def _lookup_next_romaji(s: str, i: int) -> str | None:
    for size in (2, 1):
        chunk = s[i : i + size]
        if chunk in HIRA_TO_ROMAJI:
            return HIRA_TO_ROMAJI[chunk]
    return None


def _last_vowel(text: str) -> str | None:
    for ch in reversed(text):
        if ch in "aeiou":
            return ch
    return None


def hiragana_to_romaji(text: str) -> str:
    s = normalize_kana(text)
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch.isspace():
            out.append(ch)
            i += 1
            continue

        if ch == "ー":
            if out:
                v = _last_vowel(out[-1])
                if v:
                    out.append(v)
            i += 1
            continue

        if ch == "っ":
            nxt = _lookup_next_romaji(s, i + 1) if i + 1 < len(s) else None
            if nxt:
                out.append(nxt[0])
            i += 1
            continue

        if ch == "ん":
            nxt = _lookup_next_romaji(s, i + 1) if i + 1 < len(s) else None
            if nxt and nxt[0] in "aiueoy":
                out.append("n'")
            else:
                out.append("n")
            i += 1
            continue

        matched = _lookup_next_romaji(s, i)
        if matched is not None:
            out.append(matched)
            i += 2 if i + 1 < len(s) and s[i : i + 2] in HIRA_TO_ROMAJI else 1
            continue

        out.append(ch)
        i += 1
    return "".join(out)


def kana_to_romaji(text: str) -> str:
    return hiragana_to_romaji(text)


def looks_like_pinyin(text: str) -> bool:
    t = text.strip().lower()
    if not t:
        return False
    if re.search(r"[1-5]", t):
        return True
    return any(ch in MARK_TO_BASE_TONE for ch in t)


def pinyin_marked_to_numbered(text: str) -> str:
    tokens = text.strip().split()
    out_tokens: list[str] = []
    for token in tokens:
        tone = 5
        base_chars: list[str] = []
        for ch in token.lower():
            if ch in MARK_TO_BASE_TONE:
                base, tone = MARK_TO_BASE_TONE[ch]
                base_chars.append(base)
            elif ch == "ü":
                base_chars.append("v")
            else:
                base_chars.append(ch)
        syllable = "".join(base_chars)
        if syllable and syllable[-1].isdigit():
            out_tokens.append(syllable)
        else:
            out_tokens.append(f"{syllable}{tone}")
    return " ".join(out_tokens)


def _choose_mark_index(base_syllable: str) -> int:
    idx = base_syllable.find("a")
    if idx >= 0:
        return idx
    idx = base_syllable.find("e")
    if idx >= 0:
        return idx
    ou = base_syllable.find("ou")
    if ou >= 0:
        return ou
    for idx in range(len(base_syllable) - 1, -1, -1):
        if base_syllable[idx] in "iouvü":
            return idx
    return max(len(base_syllable) - 1, 0)


def pinyin_numbered_to_marked(text: str) -> str:
    tokens = text.strip().split()
    out_tokens: list[str] = []
    for token in tokens:
        m = re.match(r"^([a-züv:]+)([1-5])$", token.lower())
        if not m:
            out_tokens.append(token)
            continue
        base = m.group(1).replace("u:", "ü").replace("v", "ü")
        tone = int(m.group(2))
        if tone == 5:
            out_tokens.append(base)
            continue

        idx = _choose_mark_index(base)
        vowel = base[idx]
        lookup = "v" if vowel == "ü" else vowel
        marks = PINYIN_MARKS.get(lookup)
        if not marks:
            out_tokens.append(base)
            continue

        marked = base[:idx] + marks[tone - 1] + base[idx + 1 :]
        out_tokens.append(marked)
    return " ".join(out_tokens)


def normalize_pinyin_for_search(text: str) -> str:
    t = nfc(text.strip().lower().replace("u:", "v"))
    if any(ch in MARK_TO_BASE_TONE for ch in t):
        t = pinyin_marked_to_numbered(t)
    tokens = []
    for token in t.split():
        if token and not token[-1].isdigit():
            tokens.append(f"{token}5")
        else:
            tokens.append(token)
    return " ".join(tokens)
