from __future__ import annotations

import time
from pathlib import Path

from yahoo_shopping_mcp.models import GlobalRateLimitPayload
from yahoo_shopping_mcp.storage import SQLiteStateStore, StoredRateLimitExceededError

GLOBAL_WINDOW_KEY = "global"


class GlobalRateLimitError(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Global rate limit exceeded. Retry after {retry_after} seconds.")
        self.retry_after = retry_after


class GlobalRateLimiter:
    def __init__(self, state_dir: Path, *, limit: int, window_seconds: int) -> None:
        self._state_store = SQLiteStateStore(state_dir)
        self._limit = limit
        self._window_seconds = window_seconds

    def consume(self) -> GlobalRateLimitPayload:
        try:
            return self._state_store.consume_global_rate_limit(
                key=GLOBAL_WINDOW_KEY,
                limit=self._limit,
                window_seconds=self._window_seconds,
                now=int(time.time()),
            )
        except StoredRateLimitExceededError as exc:
            raise GlobalRateLimitError(retry_after=exc.retry_after) from exc
