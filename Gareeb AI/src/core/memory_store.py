#!/usr/bin/env python3
"""
Persistent memory store for MJ AI (FR-08).

SQLite-backed storage for conversation history, user preferences and recent
task history. All data stays local by default.
"""

from __future__ import annotations

import time
import json
import sqlite3
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List
from core.app_paths import data_path


SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    steps_json TEXT,
    created_at REAL NOT NULL,
    finished_at REAL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, created_at);
"""


class MemoryStore:
    """
    Local SQLite memory for MJ AI.

    Thread-safe: every operation opens its own connection so workers and the
    UI thread can both use it safely.
    """

    def __init__(self, db_path: str = "data/myai.db",
                 max_conversations: int = 100,
                 max_messages_per_conversation: int = 1000,
                 cleanup_days: int = 30,
                 auto_cleanup: bool = True):
        self.logger = logging.getLogger(__name__)
        self.db_path = data_path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.max_conversations = max_conversations
        self.max_messages_per_conversation = max_messages_per_conversation
        self.cleanup_days = cleanup_days
        self.auto_cleanup = auto_cleanup

        self._local = threading.local()
        self._init_schema()

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        try:
            conn = self._connect()
            conn.executescript(SCHEMA)
            conn.commit()
            self.logger.info(f"Memory store ready at {self.db_path}")
        except Exception as exc:
            self.logger.error(f"Failed to initialize memory store: {exc}")
            raise

    @classmethod
    def from_config(cls, config_manager) -> "MemoryStore":
        cfg = config_manager.get_memory_config()
        return cls(
            db_path=cfg.database_path,
            max_conversations=cfg.max_conversations,
            max_messages_per_conversation=cfg.max_messages_per_conversation,
            cleanup_days=cfg.cleanup_days,
            auto_cleanup=cfg.auto_cleanup,
        )

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------
    def create_conversation(self, title: str = "New conversation") -> int:
        conn = self._connect()
        now = time.time()
        cur = conn.execute(
            "INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)",
            (title, now, now),
        )
        conn.commit()
        return int(cur.lastrowid)

    def add_message(self, conversation_id: int, role: str, content: str) -> int:
        conn = self._connect()
        now = time.time()
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, now),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        conn.commit()

        if self.auto_cleanup:
            self._trim_conversation(conversation_id)

        return int(cur.lastrowid)

    def _trim_conversation(self, conversation_id: int) -> None:
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        count = row["c"] if row else 0
        if count > self.max_messages_per_conversation:
            conn.execute(
                "DELETE FROM messages WHERE id IN ("
                " SELECT id FROM messages WHERE conversation_id = ?"
                " ORDER BY id ASC LIMIT ?)",
                (conversation_id, count - self.max_messages_per_conversation),
            )
            conn.commit()

    def get_messages(self, conversation_id: int,
                     limit: Optional[int] = None) -> List[Dict[str, Any]]:
        conn = self._connect()
        if limit:
            rows = conn.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
            rows = list(reversed(rows))
        else:
            rows = conn.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_context(self, conversation_id: int, max_messages: int = 20) -> List[Dict[str, str]]:
        """Return recent messages in [{'role':..,'content':..}] form for the model."""
        msgs = self.get_messages(conversation_id, limit=max_messages)
        return [{"role": m["role"], "content": m["content"]} for m in msgs]

    def list_conversations(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def rename_conversation(self, conversation_id: int, title: str) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (title, conversation_id),
        )
        conn.commit()

    def delete_conversation(self, conversation_id: int) -> bool:
        conn = self._connect()
        cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        conn.commit()
        return cur.rowcount > 0

    def clear_history(self) -> int:
        """Delete all conversations and messages. Returns rows removed."""
        conn = self._connect()
        cur = conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM conversations")
        conn.commit()
        return cur.rowcount

    def _trim_conversation_count(self) -> None:
        conn = self._connect()
        row = conn.execute("SELECT COUNT(*) AS c FROM conversations").fetchone()
        count = row["c"] if row else 0
        if count > self.max_conversations:
            rows = conn.execute(
                "SELECT id FROM conversations ORDER BY updated_at ASC LIMIT ?",
                (count - self.max_conversations,),
            ).fetchall()
            for r in rows:
                conn.execute("DELETE FROM conversations WHERE id = ?", (r["id"],))
            conn.commit()

    def cleanup_old(self) -> int:
        """Remove conversations older than the retention window."""
        if not self.auto_cleanup:
            return 0
        cutoff = time.time() - self.cleanup_days * 86400
        conn = self._connect()
        cur = conn.execute(
            "DELETE FROM conversations WHERE updated_at < ?", (cutoff,)
        )
        conn.commit()
        removed = cur.rowcount
        if removed:
            self.logger.info(f"Memory cleanup removed {removed} old conversations")
        return removed

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------
    def set_preference(self, key: str, value: Any) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, json.dumps(value), time.time()),
        )
        conn.commit()

    def get_preference(self, key: str, default: Any = None) -> Any:
        conn = self._connect()
        row = conn.execute(
            "SELECT value FROM preferences WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return default

    def all_preferences(self) -> Dict[str, Any]:
        conn = self._connect()
        rows = conn.execute("SELECT key, value FROM preferences").fetchall()
        out: Dict[str, Any] = {}
        for r in rows:
            try:
                out[r["key"]] = json.loads(r["value"])
            except (json.JSONDecodeError, TypeError):
                out[r["key"]] = r["value"]
        return out

    # ------------------------------------------------------------------
    # Task history
    # ------------------------------------------------------------------
    def record_task(self, description: str, status: str,
                    steps: Optional[list] = None,
                    finished: bool = False) -> int:
        conn = self._connect()
        now = time.time()
        cur = conn.execute(
            "INSERT INTO tasks (description, status, steps_json, created_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (description, status, json.dumps(steps or []), now, now if finished else None),
        )
        conn.commit()
        return int(cur.lastrowid)

    def update_task(self, task_id: int, status: str,
                    steps: Optional[list] = None, finished: bool = False) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE tasks SET status = ?, steps_json = COALESCE(?, steps_json), "
            "finished_at = CASE WHEN ? THEN ? ELSE finished_at END WHERE id = ?",
            (status, json.dumps(steps) if steps is not None else None,
             1 if finished else 0, time.time(), task_id),
        )
        conn.commit()

    def recent_tasks(self, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, description, status, created_at, finished_at FROM tasks "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            raw = conn.execute(
                "SELECT steps_json FROM tasks WHERE id = ?", (r["id"],)
            ).fetchone()
            try:
                item["steps"] = json.loads(raw["steps_json"]) if raw and raw["steps_json"] else []
            except (json.JSONDecodeError, TypeError):
                item["steps"] = []
            out.append(item)
        return out

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    def vacuum(self) -> None:
        try:
            conn = self._connect()
            conn.execute("VACUUM")
        except Exception as exc:
            self.logger.warning(f"VACUUM failed: {exc}")

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    def stats(self) -> Dict[str, Any]:
        conn = self._connect()
        conv = conn.execute("SELECT COUNT(*) AS c FROM conversations").fetchone()["c"]
        msgs = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
        prefs = conn.execute("SELECT COUNT(*) AS c FROM preferences").fetchone()["c"]
        tasks = conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]
        size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "conversations": conv,
            "messages": msgs,
            "preferences": prefs,
            "tasks": tasks,
            "db_bytes": size,
        }
