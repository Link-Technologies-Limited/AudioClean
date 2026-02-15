from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from audioclean.core.models import FileRecord, Fingerprint


SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    blake3 TEXT,
    codec TEXT,
    container TEXT,
    duration REAL,
    bitrate INTEGER,
    sample_rate INTEGER,
    channels INTEGER,
    has_art INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fingerprints (
    file_id INTEGER NOT NULL,
    chromaprint TEXT NOT NULL,
    UNIQUE(file_id),
    FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS matches (
    file_id INTEGER NOT NULL,
    mb_recording_id TEXT,
    confidence REAL,
    chosen INTEGER DEFAULT 0,
    FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS artwork (
    album_id TEXT,
    url TEXT,
    width INTEGER,
    height INTEGER,
    hash TEXT
);

CREATE TABLE IF NOT EXISTS operations (
    op_id TEXT PRIMARY KEY,
    plan_id TEXT,
    op_type TEXT,
    path TEXT,
    new_path TEXT,
    status TEXT
);

CREATE TABLE IF NOT EXISTS group_overrides (
    group_hash TEXT NOT NULL,
    path TEXT NOT NULL,
    action TEXT NOT NULL,
    template TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (group_hash, path)
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_file_by_path(conn: sqlite3.Connection, path: Path) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM files WHERE path = ?", (str(path),)).fetchone()


def upsert_file(conn: sqlite3.Connection, record: FileRecord) -> int:
    existing = get_file_by_path(conn, record.path)
    if existing:
        conn.execute(
            """
            UPDATE files
            SET size=?, mtime=?, blake3=?, codec=?, container=?, duration=?, bitrate=?,
                sample_rate=?, channels=?, has_art=?
            WHERE id=?
            """,
            (
                record.size,
                record.mtime,
                record.blake3,
                record.codec,
                record.container,
                record.duration,
                record.bitrate,
                record.sample_rate,
                record.channels,
                1 if record.has_art else 0,
                existing["id"],
            ),
        )
        return int(existing["id"])

    cur = conn.execute(
        """
        INSERT INTO files (path, size, mtime, blake3, codec, container, duration,
                           bitrate, sample_rate, channels, has_art)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(record.path),
            record.size,
            record.mtime,
            record.blake3,
            record.codec,
            record.container,
            record.duration,
            record.bitrate,
            record.sample_rate,
            record.channels,
            1 if record.has_art else 0,
        ),
    )
    return int(cur.lastrowid)


def upsert_fingerprint(conn: sqlite3.Connection, fingerprint: Fingerprint) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO fingerprints (file_id, chromaprint) VALUES (?, ?)",
        (fingerprint.file_id, fingerprint.chromaprint),
    )


def iter_files(conn: sqlite3.Connection) -> Iterable[sqlite3.Row]:
    return conn.execute("SELECT * FROM files ORDER BY path")


def get_duplicates_by_hash(conn: sqlite3.Connection) -> list[list[sqlite3.Row]]:
    groups: list[list[sqlite3.Row]] = []
    hashes = conn.execute(
        """
        SELECT blake3, COUNT(*) as count
        FROM files
        WHERE blake3 IS NOT NULL
        GROUP BY blake3
        HAVING count > 1
        """
    ).fetchall()
    for row in hashes:
        items = conn.execute("SELECT * FROM files WHERE blake3 = ?", (row["blake3"],)).fetchall()
        groups.append(items)
    return groups


def record_operation(conn: sqlite3.Connection, plan_id: str, op_id: str, op_type: str, path: Path, new_path: Path | None, status: str) -> None:
    conn.execute(
        """
        INSERT INTO operations (op_id, plan_id, op_type, path, new_path, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (op_id, plan_id, op_type, str(path), str(new_path) if new_path else None, status),
    )


def upsert_group_override(
    conn: sqlite3.Connection,
    group_hash: str,
    path: Path,
    action: str,
    template: str | None,
    updated_at: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO group_overrides (group_hash, path, action, template, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (group_hash, str(path), action, template, updated_at),
    )


def delete_group_override(conn: sqlite3.Connection, group_hash: str, path: Path) -> None:
    conn.execute(
        "DELETE FROM group_overrides WHERE group_hash = ? AND path = ?",
        (group_hash, str(path)),
    )


def get_group_overrides(conn: sqlite3.Connection, group_hash: str) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM group_overrides WHERE group_hash = ?",
        (group_hash,),
    ).fetchall()
    return {row["path"]: row for row in rows}
