"""Manage decision histories and comments."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from .database import Database, dump_json, load_json
from .knowledge_service import tokenize


@dataclass
class DecisionHistory:
    id: int
    title: str
    context: str
    steps: str
    outcome: str | None
    tags: list[str]
    created_at: str


@dataclass
class HistoryComment:
    id: int
    history_id: int
    author: str
    comment: str
    rating: int | None
    created_at: str


class HistoryService:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _db(self) -> Database:
        return Database(self.db_path)

    def add_history(
        self,
        title: str,
        context: str,
        steps: str,
        outcome: str | None = None,
        tags: Optional[Iterable[str]] = None,
    ) -> int:
        tags = tags or []
        with self._db() as database:
            cursor = database.execute(
                """
                INSERT INTO decision_history(title, context, steps, outcome, tags)
                VALUES (?, ?, ?, ?, ?)
                """,
                (title, context, steps, outcome, dump_json(tags)),
            )
            return int(cursor.lastrowid)

    def list_histories(self) -> List[DecisionHistory]:
        with self._db() as database:
            rows = list(
                database.query(
                    "SELECT id, title, context, steps, outcome, tags, created_at FROM decision_history ORDER BY created_at DESC"
                )
            )
        return [
            DecisionHistory(
                id=row["id"],
                title=row["title"],
                context=row["context"],
                steps=row["steps"],
                outcome=row["outcome"],
                tags=load_json(row["tags"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def search_histories(self, query: str, limit: int = 10) -> List[DecisionHistory]:
        tokens = tokenize(query)
        if not tokens:
            return []
        histories = self.list_histories()
        scored: list[tuple[DecisionHistory, int]] = []
        for history in histories:
            haystack = " ".join(
                [history.title, history.context, history.steps, history.outcome or "", " ".join(history.tags)]
            ).lower()
            score = sum(haystack.count(token) for token in tokens)
            if score > 0:
                scored.append((history, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return [history for history, _ in scored[:limit]]

    def add_comment(
        self,
        history_id: int,
        author: str,
        comment: str,
        rating: int | None = None,
    ) -> int:
        with self._db() as database:
            cursor = database.execute(
                """
                INSERT INTO history_comments(history_id, author, comment, rating)
                VALUES (?, ?, ?, ?)
                """,
                (history_id, author, comment, rating),
            )
            return int(cursor.lastrowid)

    def list_comments(self, history_id: int) -> List[HistoryComment]:
        with self._db() as database:
            rows = list(
                database.query(
                    "SELECT id, history_id, author, comment, rating, created_at FROM history_comments WHERE history_id = ? ORDER BY created_at DESC",
                    (history_id,),
                )
            )
        return [
            HistoryComment(
                id=row["id"],
                history_id=row["history_id"],
                author=row["author"],
                comment=row["comment"],
                rating=row["rating"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
