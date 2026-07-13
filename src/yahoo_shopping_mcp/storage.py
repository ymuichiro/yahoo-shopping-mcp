from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from yahoo_shopping_mcp.models import CachedResponse, GlobalRateLimitPayload

STATE_DB_FILENAME = "state.sqlite3"


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp_file:
        json.dump(payload, temp_file, ensure_ascii=False, separators=(",", ":"))
        temp_name = temp_file.name
    Path(temp_name).replace(path)


class StoredRateLimitExceededError(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Stored rate limit exceeded. Retry after {retry_after} seconds.")
        self.retry_after = retry_after


class SQLiteStateStore:
    def __init__(self, state_dir: Path) -> None:
        self._path = state_dir / STATE_DB_FILENAME
        state_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def consume_global_rate_limit(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
        now: int,
    ) -> GlobalRateLimitPayload:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT window_started_at, count FROM global_rate_limit_windows WHERE key = ?",
                    (key,),
                ).fetchone()
                if row is None or now >= int(row["window_started_at"]) + window_seconds:
                    window_started_at = now
                    count = 0
                else:
                    window_started_at = int(row["window_started_at"])
                    count = int(row["count"])

                if count >= limit:
                    reset_at = window_started_at + window_seconds
                    raise StoredRateLimitExceededError(retry_after=max(reset_at - now, 1))

                count += 1
                conn.execute(
                    """
                    INSERT INTO global_rate_limit_windows (key, window_started_at, count)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        window_started_at = excluded.window_started_at,
                        count = excluded.count
                    """,
                    (key, window_started_at, count),
                )
            except Exception:
                conn.rollback()
                raise
            conn.commit()
            return GlobalRateLimitPayload(
                limit=limit,
                remaining=max(limit - count, 0),
                window_seconds=window_seconds,
                reset_at=window_started_at + window_seconds,
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS global_rate_limit_windows (
                    key TEXT PRIMARY KEY,
                    window_started_at INTEGER NOT NULL,
                    count INTEGER NOT NULL
                )
                """
            )

class CacheStore:
    def __init__(self, cache_dir: Path, ttl_seconds: int) -> None:
        self._cache_dir = cache_dir
        self._ttl_seconds = ttl_seconds
        cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, key: str) -> Path:
        return self._cache_dir / f"{key}.json"

    def make_key(self, payload: dict) -> str:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def get(self, payload: dict) -> dict | None:
        path = self._cache_path(self.make_key(payload))
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as handle:
            cached = CachedResponse.model_validate(json.load(handle))
        if cached.expires_at <= time.time():
            path.unlink(missing_ok=True)
            return None
        return cached.payload

    def set(self, payload: dict, response: dict) -> None:
        key = self.make_key(payload)
        cached = CachedResponse(expires_at=time.time() + self._ttl_seconds, payload=response)
        atomic_write_json(self._cache_path(key), cached.model_dump())
