from __future__ import annotations

SCHEMA_SQL = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS chars (
    cp INTEGER PRIMARY KEY,
    ch TEXT NOT NULL,
    radical INTEGER NULL,
    strokes INTEGER NULL,
    freq INTEGER NULL,
    sources TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jp_readings (
    cp INTEGER NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('on','kun')),
    reading TEXT NOT NULL,
    rank INTEGER NULL,
    FOREIGN KEY(cp) REFERENCES chars(cp)
);

CREATE TABLE IF NOT EXISTS jp_gloss (
    cp INTEGER NOT NULL,
    gloss TEXT NOT NULL,
    FOREIGN KEY(cp) REFERENCES chars(cp)
);

CREATE TABLE IF NOT EXISTS cn_readings (
    cp INTEGER NOT NULL,
    pinyin_marked TEXT NOT NULL,
    pinyin_numbered TEXT NOT NULL,
    rank INTEGER NULL,
    FOREIGN KEY(cp) REFERENCES chars(cp)
);

CREATE TABLE IF NOT EXISTS cn_gloss (
    cp INTEGER NOT NULL,
    gloss TEXT NOT NULL,
    FOREIGN KEY(cp) REFERENCES chars(cp)
);

CREATE TABLE IF NOT EXISTS variants (
    cp INTEGER NOT NULL,
    kind TEXT NOT NULL,
    target_cp INTEGER NOT NULL,
    note TEXT NULL,
    FOREIGN KEY(cp) REFERENCES chars(cp)
);

CREATE TABLE IF NOT EXISTS jp_words (
    cp INTEGER NOT NULL,
    word TEXT NOT NULL,
    reading_kana TEXT NULL,
    gloss_en TEXT NULL,
    rank INTEGER NOT NULL,
    FOREIGN KEY(cp) REFERENCES chars(cp)
);

CREATE TABLE IF NOT EXISTS cn_words (
    cp INTEGER NOT NULL,
    trad TEXT NOT NULL,
    simp TEXT NOT NULL,
    pinyin_marked TEXT NOT NULL,
    pinyin_numbered TEXT NOT NULL,
    gloss_en TEXT NOT NULL,
    rank INTEGER NOT NULL,
    FOREIGN KEY(cp) REFERENCES chars(cp)
);

CREATE TABLE IF NOT EXISTS search_index (
    cp INTEGER NOT NULL,
    jp_keys TEXT,
    cn_keys TEXT,
    gloss_keys TEXT,
    FOREIGN KEY(cp) REFERENCES chars(cp)
);

CREATE INDEX IF NOT EXISTS idx_jp_reading ON jp_readings(reading);
CREATE INDEX IF NOT EXISTS idx_cn_pinyin_num ON cn_readings(pinyin_numbered);
CREATE INDEX IF NOT EXISTS idx_gloss ON jp_gloss(gloss);
CREATE INDEX IF NOT EXISTS idx_jp_words_word ON jp_words(word);
CREATE INDEX IF NOT EXISTS idx_cn_words_trad ON cn_words(trad);
CREATE INDEX IF NOT EXISTS idx_cn_words_simp ON cn_words(simp);
CREATE INDEX IF NOT EXISTS idx_chars_rad_strokes ON chars(radical, strokes, cp);
CREATE INDEX IF NOT EXISTS idx_chars_freq ON chars(freq, cp);
CREATE INDEX IF NOT EXISTS idx_search_gloss ON search_index(gloss_keys);
"""


DROP_SQL = """
DROP TABLE IF EXISTS build_meta;
DROP TABLE IF EXISTS sentences;
DROP TABLE IF EXISTS frequency_scores;
DROP TABLE IF EXISTS phonetic_series;
DROP TABLE IF EXISTS components;
DROP TABLE IF EXISTS field_provenance;
DROP TABLE IF EXISTS search_index;
DROP TABLE IF EXISTS cn_words;
DROP TABLE IF EXISTS jp_words;
DROP TABLE IF EXISTS variants;
DROP TABLE IF EXISTS cn_gloss;
DROP TABLE IF EXISTS cn_readings;
DROP TABLE IF EXISTS jp_gloss;
DROP TABLE IF EXISTS jp_readings;
DROP TABLE IF EXISTS chars;
"""
