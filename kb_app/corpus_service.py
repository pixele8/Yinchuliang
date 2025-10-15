"""Services for managing knowledge corpora and bulk ingestion."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .database import Database
from .knowledge_service import KnowledgeService

SUPPORTED_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".rst",
    ".json",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".csv",
    ".tsv",
    ".log",
}


@dataclass
class KnowledgeCorpus:
    id: int
    name: str
    base_path: Optional[str]
    description: Optional[str]
    created_at: str


@dataclass
class CorpusFile:
    id: int
    corpus_id: int
    file_name: str
    file_path: Optional[str]
    content_hash: str
    created_at: str


@dataclass
class IngestReport:
    corpus_id: int
    files_processed: int
    chunks_created: int
    skipped: list[str]


def _chunk_text(text: str, *, chunk_size: int = 800, overlap: int = 80) -> list[str]:
    """Split large bodies of text into overlapping windows."""

    if not text:
        return []
    paragraphs = [block.strip() for block in text.splitlines() if block.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]

    chunks: list[str] = []
    buffer: list[str] = []
    for para in paragraphs:
        buffer.append(para)
        joined = "\n".join(buffer)
        if len(joined) >= chunk_size:
            chunks.append(joined)
            # start a new buffer with overlap from the end of the chunk
            if overlap > 0:
                tail = joined[-overlap:]
                buffer = [tail]
            else:
                buffer = []
    if buffer:
        chunks.append("\n".join(buffer))
    return chunks


class CorpusService:
    """High level service for corpus management and ingestion."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._knowledge_service = KnowledgeService(db_path)

    def _db(self) -> Database:
        return Database(self.db_path)

    # ------------------------------------------------------------------
    # Corpus CRUD operations
    # ------------------------------------------------------------------
    def create_corpus(
        self,
        name: str,
        *,
        base_path: Optional[Path] = None,
        description: str | None = None,
    ) -> int:
        with self._db() as database:
            cursor = database.execute(
                """
                INSERT INTO knowledge_corpora(name, base_path, description)
                VALUES (?, ?, ?)
                """,
                (name, str(base_path) if base_path else None, description),
            )
            return int(cursor.lastrowid)

    def ensure_corpus(
        self,
        name: str,
        *,
        base_path: Optional[Path] = None,
        description: str | None = None,
    ) -> KnowledgeCorpus:
        existing = self.get_corpus_by_name(name)
        if existing:
            if base_path and base_path.as_posix() != (existing.base_path or ""):
                self.update_corpus(existing.id, base_path=base_path)
            return existing
        corpus_id = self.create_corpus(
            name,
            base_path=base_path,
            description=description or "",
        )
        corpus = self.get_corpus(corpus_id)
        assert corpus is not None
        return corpus

    def update_corpus(
        self,
        corpus_id: int,
        *,
        name: Optional[str] = None,
        base_path: Optional[Path] = None,
        description: Optional[str] = None,
    ) -> None:
        fields = []
        values: list[object] = []
        if name is not None:
            fields.append("name = ?")
            values.append(name)
        if base_path is not None:
            fields.append("base_path = ?")
            values.append(str(base_path))
        if description is not None:
            fields.append("description = ?")
            values.append(description)
        if not fields:
            return
        values.append(corpus_id)
        with self._db() as database:
            database.execute(
                f"UPDATE knowledge_corpora SET {', '.join(fields)} WHERE id = ?",
                values,
            )

    def delete_corpus(self, corpus_id: int) -> bool:
        with self._db() as database:
            cursor = database.execute(
                "DELETE FROM knowledge_corpora WHERE id = ?",
                (corpus_id,),
            )
            return cursor.rowcount > 0

    def list_corpora(self) -> list[KnowledgeCorpus]:
        with self._db() as database:
            rows = list(
                database.query(
                    "SELECT id, name, base_path, description, created_at FROM knowledge_corpora ORDER BY created_at DESC"
                )
            )
        return [
            KnowledgeCorpus(
                id=row["id"],
                name=row["name"],
                base_path=row["base_path"],
                description=row["description"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_corpus(self, corpus_id: int) -> Optional[KnowledgeCorpus]:
        with self._db() as database:
            row = next(
                database.query(
                    "SELECT id, name, base_path, description, created_at FROM knowledge_corpora WHERE id = ?",
                    (corpus_id,),
                ),
                None,
            )
        if row is None:
            return None
        return KnowledgeCorpus(
            id=row["id"],
            name=row["name"],
            base_path=row["base_path"],
            description=row["description"],
            created_at=row["created_at"],
        )

    def get_corpus_by_name(self, name: str) -> Optional[KnowledgeCorpus]:
        with self._db() as database:
            row = next(
                database.query(
                    "SELECT id, name, base_path, description, created_at FROM knowledge_corpora WHERE name = ?",
                    (name,),
                ),
                None,
            )
        if row is None:
            return None
        return KnowledgeCorpus(
            id=row["id"],
            name=row["name"],
            base_path=row["base_path"],
            description=row["description"],
            created_at=row["created_at"],
        )

    # ------------------------------------------------------------------
    # File management
    # ------------------------------------------------------------------
    def list_files(self, corpus_id: int) -> list[CorpusFile]:
        with self._db() as database:
            rows = list(
                database.query(
                    "SELECT id, corpus_id, file_name, file_path, content_hash, created_at FROM corpus_files WHERE corpus_id = ? ORDER BY created_at DESC",
                    (corpus_id,),
                )
            )
        return [
            CorpusFile(
                id=row["id"],
                corpus_id=row["corpus_id"],
                file_name=row["file_name"],
                file_path=row["file_path"],
                content_hash=row["content_hash"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _remove_file_chunks(self, corpus_file_id: int) -> None:
        with self._db() as database:
            database.execute(
                "DELETE FROM knowledge WHERE id IN (SELECT knowledge_id FROM knowledge_chunks WHERE corpus_file_id = ?)",
                (corpus_file_id,),
            )
            database.execute(
                "DELETE FROM corpus_files WHERE id = ?",
                (corpus_file_id,),
            )

    def _register_file(
        self,
        corpus_id: int,
        file_path: Path,
        *,
        content_hash: str,
    ) -> int:
        with self._db() as database:
            row = next(
                database.query(
                    "SELECT id, content_hash FROM corpus_files WHERE corpus_id = ? AND file_path = ?",
                    (corpus_id, file_path.as_posix()),
                ),
                None,
            )
        if row is not None:
            file_id = int(row["id"])
            stored_hash = row["content_hash"]
            if stored_hash == content_hash:
                return file_id
            self._remove_file_chunks(file_id)

        with self._db() as database:
            cursor = database.execute(
                """
                INSERT INTO corpus_files(corpus_id, file_name, file_path, content_hash)
                VALUES (?, ?, ?, ?)
                """,
                (
                    corpus_id,
                    file_path.name,
                    file_path.as_posix(),
                    content_hash,
                ),
            )
            return int(cursor.lastrowid)

    def _save_chunks(
        self,
        corpus_file_id: int,
        chunks: Sequence[str],
        *,
        corpus_id: int,
        title_prefix: str,
    ) -> int:
        created = 0
        for index, chunk in enumerate(chunks):
            entry_id = self._knowledge_service.add_entry(
                title=f"{title_prefix} - 段落 {index + 1}",
                question=chunk,
                answer=chunk,
                tags=[],
                corpus_id=corpus_id,
            )
            with self._db() as database:
                database.execute(
                    """
                    INSERT OR REPLACE INTO knowledge_chunks(corpus_file_id, knowledge_id, chunk_index)
                    VALUES (?, ?, ?)
                    """,
                    (corpus_file_id, entry_id, index),
                )
            created += 1
        return created

    def ingest_paths(
        self,
        corpus_id: int,
        paths: Iterable[Path],
        *,
        chunk_size: int = 800,
        overlap: int = 80,
    ) -> IngestReport:
        processed = 0
        chunks_created = 0
        skipped: list[str] = []

        for path in paths:
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix not in SUPPORTED_TEXT_SUFFIXES:
                skipped.append(path.name)
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                try:
                    text = path.read_text(encoding="gbk")
                except Exception:  # pragma: no cover - fallback branch
                    skipped.append(path.name)
                    continue
            if suffix == ".json":
                try:
                    data = json.loads(text)
                    if isinstance(data, (list, dict)):
                        text = json.dumps(data, ensure_ascii=False, indent=2)
                except json.JSONDecodeError:
                    pass
            if not text.strip():
                skipped.append(path.name)
                continue

            hash_value = hashlib.sha1(text.encode("utf-8")).hexdigest()
            corpus_file_id = self._register_file(corpus_id, path.resolve(), content_hash=hash_value)
            chunks = _chunk_text(text, chunk_size=chunk_size, overlap=overlap)
            if not chunks:
                skipped.append(path.name)
                self._remove_file_chunks(corpus_file_id)
                continue
            created = self._save_chunks(
                corpus_file_id,
                chunks,
                corpus_id=corpus_id,
                title_prefix=path.stem,
            )
            processed += 1
            chunks_created += created

        return IngestReport(
            corpus_id=corpus_id,
            files_processed=processed,
            chunks_created=chunks_created,
            skipped=skipped,
        )

    def ingest_directory(
        self,
        corpus_id: int,
        directory: Path,
        *,
        chunk_size: int = 800,
        overlap: int = 80,
        recursive: bool = True,
    ) -> IngestReport:
        if not directory.exists() or not directory.is_dir():
            raise FileNotFoundError(f"知识库路径不存在: {directory}")

        paths: list[Path] = []
        iterator = directory.rglob("*") if recursive else directory.glob("*")
        for item in iterator:
            if item.is_file():
                paths.append(item)
        return self.ingest_paths(
            corpus_id,
            paths,
            chunk_size=chunk_size,
            overlap=overlap,
        )
