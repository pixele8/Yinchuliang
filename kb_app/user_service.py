"""Services for managing local user accounts and admin events."""
from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .database import Database


@dataclass
class User:
    id: int
    username: str
    is_admin: bool
    is_active: bool
    created_at: str


@dataclass
class AdminEvent:
    id: int
    actor: str
    action: str
    subject: Optional[str]
    details: Optional[str]
    created_at: str


class UserService:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _db(self) -> Database:
        return Database(self.db_path)

    # ------------------------------------------------------------------
    # password helpers
    def _hash_password(self, password: str, salt: bytes) -> str:
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return digest.hex()

    def _generate_salt(self) -> bytes:
        return os.urandom(16)

    def _get_credentials(self, username: str) -> tuple[str, bytes] | None:
        with self._db() as database:
            row = next(
                database.query(
                    "SELECT password_hash, salt FROM users WHERE username = ?",
                    (username,),
                ),
                None,
            )
        if row is None:
            return None
        return row["password_hash"], bytes.fromhex(row["salt"])

    # ------------------------------------------------------------------
    # user operations
    def register_user(self, username: str, password: str, *, is_admin: bool = False) -> int:
        salt = self._generate_salt()
        password_hash = self._hash_password(password, salt)
        with self._db() as database:
            try:
                cursor = database.execute(
                    """
                    INSERT INTO users(username, password_hash, salt, is_admin)
                    VALUES (?, ?, ?, ?)
                    """,
                    (username, password_hash, salt.hex(), 1 if is_admin else 0),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("用户名已存在") from exc
            return int(cursor.lastrowid)

    def authenticate(self, username: str, password: str) -> bool:
        user = self.get_user(username)
        if not user or not user.is_active:
            return False
        credentials = self._get_credentials(username)
        if credentials is None:
            return False
        expected, salt = credentials
        candidate = self._hash_password(password, salt)
        return candidate == expected

    def list_users(self) -> List[User]:
        with self._db() as database:
            rows = list(
                database.query(
                    "SELECT id, username, is_admin, is_active, created_at FROM users ORDER BY created_at DESC"
                )
            )
        return [
            User(
                id=row["id"],
                username=row["username"],
                is_admin=bool(row["is_admin"]),
                is_active=bool(row["is_active"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_user(self, username: str) -> Optional[User]:
        with self._db() as database:
            row = next(
                database.query(
                    "SELECT id, username, is_admin, is_active, created_at FROM users WHERE username = ?",
                    (username,),
                ),
                None,
            )
        if row is None:
            return None
        return User(
            id=row["id"],
            username=row["username"],
            is_admin=bool(row["is_admin"]),
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
        )

    def set_admin(self, username: str, is_admin: bool) -> None:
        with self._db() as database:
            database.execute(
                "UPDATE users SET is_admin = ? WHERE username = ?",
                (1 if is_admin else 0, username),
            )

    def set_active(self, username: str, is_active: bool) -> None:
        with self._db() as database:
            database.execute(
                "UPDATE users SET is_active = ? WHERE username = ?",
                (1 if is_active else 0, username),
            )

    def reset_password(self, username: str, new_password: str) -> None:
        salt = self._generate_salt()
        password_hash = self._hash_password(new_password, salt)
        with self._db() as database:
            database.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
                (password_hash, salt.hex(), username),
            )

    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        user = self.get_user(username)
        if not user or not user.is_active:
            return False
        credentials = self._get_credentials(username)
        if credentials is None:
            return False
        expected, salt = credentials
        if self._hash_password(old_password, salt) != expected:
            return False
        new_salt = self._generate_salt()
        new_hash = self._hash_password(new_password, new_salt)
        with self._db() as database:
            database.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
                (new_hash, new_salt.hex(), username),
            )
        return True

    # ------------------------------------------------------------------
    # admin support
    def record_admin_action(
        self,
        actor: str,
        action: str,
        subject: Optional[str] = None,
        details: Optional[str] = None,
    ) -> int:
        with self._db() as database:
            cursor = database.execute(
                """
                INSERT INTO admin_events(actor, action, subject, details)
                VALUES (?, ?, ?, ?)
                """,
                (actor, action, subject, details),
            )
            return int(cursor.lastrowid)

    def list_admin_events(self, limit: int = 20) -> List[AdminEvent]:
        with self._db() as database:
            rows = list(
                database.query(
                    "SELECT id, actor, action, subject, details, created_at FROM admin_events ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            )
        return [
            AdminEvent(
                id=row["id"],
                actor=row["actor"],
                action=row["action"],
                subject=row["subject"],
                details=row["details"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def summary(self) -> dict[str, int]:
        with self._db() as database:
            knowledge_count = int(database.scalar("SELECT COUNT(*) FROM knowledge") or 0)
            history_count = int(database.scalar("SELECT COUNT(*) FROM decision_history") or 0)
            comment_count = int(database.scalar("SELECT COUNT(*) FROM history_comments") or 0)
            user_count = int(database.scalar("SELECT COUNT(*) FROM users") or 0)
            admin_count = int(database.scalar("SELECT COUNT(*) FROM users WHERE is_admin = 1") or 0)
            active_count = int(database.scalar("SELECT COUNT(*) FROM users WHERE is_active = 1") or 0)
        return {
            "knowledge": knowledge_count,
            "histories": history_count,
            "comments": comment_count,
            "users": user_count,
            "admins": admin_count,
            "active_users": active_count,
        }

    # ------------------------------------------------------------------
    # helper for admin bulk operations
    def require_existing_user(self, username: str) -> User:
        user = self.get_user(username)
        if not user:
            raise ValueError(f"用户 {username} 不存在")
        return user


__all__ = ["UserService", "User", "AdminEvent"]
