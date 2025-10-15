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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

CREATE INDEX IF NOT EXISTS idx_knowledge_tags ON knowledge(id, tags);
CREATE INDEX IF NOT EXISTS idx_history_tags ON decision_history(id, tags);
CREATE INDEX IF NOT EXISTS idx_history_comments_history ON history_comments(history_id);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_admin_events_created ON admin_events(created_at);
"""


def ensure_database(db_path: Path) -> sqlite3.Connection:
    """Create the SQLite database with the required schema if it does not exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(DB_SCHEMA)
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
