"""SQLite persistence layer for the offline knowledge base system."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, Iterator, Optional

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    tags TEXT DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    corpus_id INTEGER
);

CREATE TABLE IF NOT EXISTS decision_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    context TEXT NOT NULL,
    steps TEXT NOT NULL,
    outcome TEXT,
    tags TEXT DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS history_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    history_id INTEGER NOT NULL,
    author TEXT NOT NULL,
    comment TEXT NOT NULL,
    rating INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(history_id) REFERENCES decision_history(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    subject TEXT,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS knowledge_corpora (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    base_path TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS corpus_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corpus_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT,
    content_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(corpus_id) REFERENCES knowledge_corpora(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    corpus_file_id INTEGER NOT NULL,
    knowledge_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    FOREIGN KEY(corpus_file_id) REFERENCES corpus_files(id) ON DELETE CASCADE,
    FOREIGN KEY(knowledge_id) REFERENCES knowledge(id) ON DELETE CASCADE,
    UNIQUE(corpus_file_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_tags ON knowledge(id, tags);
CREATE INDEX IF NOT EXISTS idx_history_tags ON decision_history(id, tags);
CREATE INDEX IF NOT EXISTS idx_history_comments_history ON history_comments(history_id);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_admin_events_created ON admin_events(created_at);
CREATE INDEX IF NOT EXISTS idx_corpus_files_corpus ON corpus_files(corpus_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_corpus ON knowledge(corpus_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_file ON knowledge_chunks(corpus_file_id);
"""


def _apply_migrations(connection: sqlite3.Connection) -> None:
    """Ensure new columns exist when upgrading from older schemas."""

    existing_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(knowledge)").fetchall()
    }
    if "corpus_id" not in existing_columns:
        connection.execute("ALTER TABLE knowledge ADD COLUMN corpus_id INTEGER")
    connection.commit()


def ensure_database(db_path: Path) -> sqlite3.Connection:
    """Create the SQLite database with the required schema if it does not exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(DB_SCHEMA)
    _apply_migrations(connection)
    connection.commit()
    return connection


def load_json(text: str | None) -> list[str]:
    if not text:
        return []
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def dump_json(items: Iterable[str]) -> str:
    return json.dumps([str(item) for item in items], ensure_ascii=False)


def iter_rows(cursor: sqlite3.Cursor) -> Iterator[sqlite3.Row]:
    row = cursor.fetchone()
    while row is not None:
        yield row
        row = cursor.fetchone()


class Database:
    """Simple wrapper around sqlite3 providing typed helpers."""

    def __init__(self, path: Path):
        self.path = path
        self._connection: Optional[sqlite3.Connection] = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = ensure_database(self.path)
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def execute(self, query: str, parameters: Iterable | None = None) -> sqlite3.Cursor:
        cursor = self.connection.cursor()
        cursor.execute(query, tuple(parameters or ()))
        self.connection.commit()
        return cursor

    def query(self, query: str, parameters: Iterable | None = None) -> Iterator[sqlite3.Row]:
        cursor = self.connection.cursor()
        cursor.execute(query, tuple(parameters or ()))
        return iter_rows(cursor)

    def scalar(self, query: str, parameters: Iterable | None = None):
        cursor = self.connection.cursor()
        cursor.execute(query, tuple(parameters or ()))
        row = cursor.fetchone()
        return row[0] if row else None

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
