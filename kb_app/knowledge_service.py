"""Domain logic for managing knowledge entries and answering questions."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from .database import Database, dump_json, load_json

WORD_RE = re.compile(r"[\w-]+", flags=re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in WORD_RE.findall(text)]


@dataclass
class KnowledgeEntry:
    id: int
    title: str
    question: str
    answer: str
    tags: list[str]
    created_at: str


class KnowledgeService:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _db(self) -> Database:
        return Database(self.db_path)

    def add_entry(
        self,
        title: str,
        question: str,
        answer: str,
        tags: Optional[Iterable[str]] = None,
    ) -> int:
        tags = tags or []
        with self._db() as database:
            cursor = database.execute(
                """
                INSERT INTO knowledge(title, question, answer, tags)
                VALUES (?, ?, ?, ?)
                """,
                (title, question, answer, dump_json(tags)),
            )
            return int(cursor.lastrowid)

    def list_entries(self) -> List[KnowledgeEntry]:
        with self._db() as database:
            rows = list(
                database.query(
                    "SELECT id, title, question, answer, tags, created_at FROM knowledge ORDER BY created_at DESC"
                )
            )
        return [
            KnowledgeEntry(
                id=row["id"],
                title=row["title"],
                question=row["question"],
                answer=row["answer"],
                tags=load_json(row["tags"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_entry(self, entry_id: int) -> Optional[KnowledgeEntry]:
        with self._db() as database:
            row = next(
                database.query(
                    "SELECT id, title, question, answer, tags, created_at FROM knowledge WHERE id = ?",
                    (entry_id,),
                ),
                None,
            )
        if row is None:
            return None
        return KnowledgeEntry(
            id=row["id"],
            title=row["title"],
            question=row["question"],
            answer=row["answer"],
            tags=load_json(row["tags"]),
            created_at=row["created_at"],
        )

    def update_entry(
        self,
        entry_id: int,
        *,
        title: Optional[str] = None,
        question: Optional[str] = None,
        answer: Optional[str] = None,
        tags: Optional[Iterable[str]] = None,
    ) -> bool:
        current = self.get_entry(entry_id)
        if not current:
            return False
        new_title = title if title is not None else current.title
        new_question = question if question is not None else current.question
        new_answer = answer if answer is not None else current.answer
        new_tags = list(tags) if tags is not None else current.tags
        with self._db() as database:
            database.execute(
                "UPDATE knowledge SET title = ?, question = ?, answer = ?, tags = ? WHERE id = ?",
                (new_title, new_question, new_answer, dump_json(new_tags), entry_id),
            )
        return True

    def delete_entry(self, entry_id: int) -> bool:
        with self._db() as database:
            cursor = database.execute("DELETE FROM knowledge WHERE id = ?", (entry_id,))
            return cursor.rowcount > 0

    def _build_index(self) -> tuple[list[KnowledgeEntry], dict[str, dict[int, int]]]:
        entries = self.list_entries()
        index: dict[str, dict[int, int]] = {}
        for entry in entries:
            tokens = tokenize(entry.question + " " + entry.answer + " " + " ".join(entry.tags))
            for token in tokens:
                index.setdefault(token, {}).setdefault(entry.id, 0)
                index[token][entry.id] += 1
        return entries, index

    def answer(self, question: str, limit: int = 3) -> list[tuple[KnowledgeEntry, float]]:
        entries, index = self._build_index()
        if not entries:
            return []
        query_tokens = tokenize(question)
        scores: dict[int, float] = {entry.id: 0.0 for entry in entries}

        doc_count = len(entries)
        for token in query_tokens:
            docs_with_token = index.get(token)
            if not docs_with_token:
                continue
            idf = math.log((1 + doc_count) / (1 + len(docs_with_token))) + 1
            for entry_id, freq in docs_with_token.items():
                scores[entry_id] += freq * idf

        scored_entries = [
            (next(entry for entry in entries if entry.id == entry_id), score)
            for entry_id, score in scores.items()
            if score > 0
        ]
        scored_entries.sort(key=lambda item: item[1], reverse=True)
        return scored_entries[:limit]
