from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from kanjitui.db.schema import DROP_SQL, SCHEMA_SQL


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="initial_schema", sql=SCHEMA_SQL),
    Migration(
        version=2,
        name="phase_c_provenance",
        sql="""
        CREATE TABLE IF NOT EXISTS field_provenance (
            cp INTEGER NOT NULL,
            field TEXT NOT NULL,
            value TEXT NOT NULL,
            source TEXT NOT NULL,
            confidence REAL NOT NULL,
            FOREIGN KEY(cp) REFERENCES chars(cp)
        );
        CREATE INDEX IF NOT EXISTS idx_field_provenance_cp ON field_provenance(cp);
        CREATE INDEX IF NOT EXISTS idx_field_provenance_field ON field_provenance(field, source);
        """,
    ),
    Migration(
        version=3,
        name="phase_d_analysis_tables",
        sql="""
        CREATE TABLE IF NOT EXISTS components (
            cp INTEGER NOT NULL,
            component_cp INTEGER NOT NULL,
            kind TEXT NOT NULL DEFAULT 'ids',
            source TEXT NOT NULL DEFAULT 'unihan',
            FOREIGN KEY(cp) REFERENCES chars(cp)
        );
        CREATE INDEX IF NOT EXISTS idx_components_cp ON components(cp);

        CREATE TABLE IF NOT EXISTS phonetic_series (
            series_key TEXT NOT NULL,
            cp INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT 'unihan',
            FOREIGN KEY(cp) REFERENCES chars(cp)
        );
        CREATE INDEX IF NOT EXISTS idx_phonetic_series_key ON phonetic_series(series_key);
        CREATE INDEX IF NOT EXISTS idx_phonetic_series_cp ON phonetic_series(cp);

        CREATE TABLE IF NOT EXISTS frequency_scores (
            cp INTEGER NOT NULL,
            profile TEXT NOT NULL,
            score REAL NOT NULL,
            rank INTEGER NOT NULL,
            FOREIGN KEY(cp) REFERENCES chars(cp)
        );
        CREATE INDEX IF NOT EXISTS idx_frequency_profile_rank ON frequency_scores(profile, rank, cp);

        CREATE TABLE IF NOT EXISTS sentences (
            cp INTEGER NOT NULL,
            lang TEXT NOT NULL,
            text TEXT NOT NULL,
            reading TEXT,
            gloss TEXT,
            source TEXT,
            license TEXT,
            rank INTEGER NOT NULL,
            FOREIGN KEY(cp) REFERENCES chars(cp)
        );
        CREATE INDEX IF NOT EXISTS idx_sentences_cp_lang ON sentences(cp, lang, rank);
        """,
    ),
)


def _ensure_meta_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def current_schema_version(conn: sqlite3.Connection) -> int:
    _ensure_meta_table(conn)
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    if row is None:
        return 0
    return int(row[0])


def apply_migrations(conn: sqlite3.Connection, target_version: int | None = None) -> int:
    _ensure_meta_table(conn)
    applied = {
        int(row[0])
        for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    }

    to_apply = []
    for migration in sorted(MIGRATIONS, key=lambda m: m.version):
        if target_version is not None and migration.version > target_version:
            continue
        if migration.version in applied:
            continue
        to_apply.append(migration)

    for migration in to_apply:
        conn.executescript(migration.sql)
        conn.execute(
            "INSERT INTO schema_migrations(version, name) VALUES(?, ?)",
            (migration.version, migration.name),
        )

    return current_schema_version(conn)


def rebuild_schema(conn: sqlite3.Connection, target_version: int | None = None) -> int:
    conn.executescript(DROP_SQL)
    _ensure_meta_table(conn)
    conn.execute("DELETE FROM schema_migrations")
    return apply_migrations(conn, target_version=target_version)
