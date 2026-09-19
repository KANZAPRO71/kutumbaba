"""Cached memory/open-loop embedding vectors (same SQLite file as user memory)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from persona_ai.memory.models import DEFAULT_USER_ID
from persona_ai.memory.store import default_memory_db_path

RefKind = str  # "memory" | "open_loop"

_store: SQLiteEmbeddingStore | None = None


class SQLiteEmbeddingStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path or default_memory_db_path())
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=DELETE")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_vectors (
                    ref_kind TEXT NOT NULL,
                    ref_id TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT 'local',
                    dim INTEGER NOT NULL,
                    vector_json TEXT NOT NULL,
                    text_fp TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (ref_kind, ref_id, user_id)
                )
                """
            )
            conn.commit()

    def get(
        self,
        ref_kind: RefKind,
        ref_id: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[float] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT vector_json FROM memory_vectors
                WHERE ref_kind = ? AND ref_id = ? AND user_id = ?
                """,
                (ref_kind, ref_id, user_id),
            ).fetchone()
        if row is None:
            return None
        raw = json.loads(row[0])
        if not isinstance(raw, list):
            return None
        return [float(x) for x in raw]

    def put(
        self,
        ref_kind: RefKind,
        ref_id: str,
        vector: list[float],
        *,
        text_fp: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> None:
        from datetime import datetime, timezone

        payload = json.dumps(vector, ensure_ascii=False)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_vectors
                    (ref_kind, ref_id, user_id, dim, vector_json, text_fp, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ref_kind, ref_id, user_id) DO UPDATE SET
                    dim = excluded.dim,
                    vector_json = excluded.vector_json,
                    text_fp = excluded.text_fp,
                    updated_at = excluded.updated_at
                """,
                (ref_kind, ref_id, user_id, len(vector), payload, text_fp, now),
            )
            conn.commit()

    def delete_all(self, user_id: str = DEFAULT_USER_ID) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM memory_vectors WHERE user_id = ?", (user_id,))
            conn.commit()
            return int(cur.rowcount)

    def close(self) -> None:
        try:
            with self._connect() as conn:
                conn.commit()
        except Exception:
            pass


def get_embedding_store() -> SQLiteEmbeddingStore:
    global _store
    if _store is None:
        _store = SQLiteEmbeddingStore()
    return _store


def reset_embedding_store() -> None:
    global _store
    if _store is not None:
        try:
            _store.close()
        except Exception:
            pass
    _store = None


def text_fingerprint(text: str) -> str:
    import hashlib

    normalized = " ".join((text or "").split()).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
