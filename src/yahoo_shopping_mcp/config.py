from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from yahoo_shopping_mcp.constants import (
    CACHE_DIRNAME,
    DEFAULT_BASE_RATE_SECONDS,
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_GLOBAL_RATE_LIMIT,
    DEFAULT_GLOBAL_WINDOW_SECONDS,
    DEFAULT_HARD_LIMIT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_WARNING_THRESHOLD,
    STATE_DIRNAME,
)


@dataclass(slots=True)
class Settings:
    app_id: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    base_rate_seconds: float = DEFAULT_BASE_RATE_SECONDS
    warning_threshold: int = DEFAULT_WARNING_THRESHOLD
    hard_limit: int = DEFAULT_HARD_LIMIT
    global_rate_limit: int = DEFAULT_GLOBAL_RATE_LIMIT
    global_window_seconds: int = DEFAULT_GLOBAL_WINDOW_SECONDS
    allowed_hosts: list[str] | None = None
    allowed_origins: list[str] | None = None
    state_dir: Path = Path(".local") / STATE_DIRNAME
    cache_dir: Path = Path(".local") / CACHE_DIRNAME


def _get_env(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _parse_csv_env(name: str) -> list[str] | None:
    raw = _get_env(name)
    if not raw:
        return None
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or None


def _parse_int_env(name: str, default: int) -> int:
    raw = _get_env(name)
    return int(raw) if raw is not None else default


def _parse_float_env(name: str, default: float) -> float:
    raw = _get_env(name)
    return float(raw) if raw is not None else default


def load_settings() -> Settings:
    app_id = _get_env("YAHOO_SHOPPING_APP_ID")
    if not app_id:
        raise RuntimeError("YAHOO_SHOPPING_APP_ID is required.")

    host = _get_env("YAHOO_SHOPPING_MCP_HOST") or DEFAULT_HOST
    port = _parse_int_env("YAHOO_SHOPPING_MCP_PORT", DEFAULT_PORT)
    base_dir = Path(_get_env("YAHOO_SHOPPING_MCP_DATA_DIR") or ".local").resolve()
    cache_ttl_seconds = _parse_int_env("YAHOO_SHOPPING_MCP_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS)
    base_rate_seconds = _parse_float_env("YAHOO_SHOPPING_MCP_BASE_RATE_SECONDS", DEFAULT_BASE_RATE_SECONDS)
    warning_threshold = _parse_int_env("YAHOO_SHOPPING_MCP_WARNING_THRESHOLD", DEFAULT_WARNING_THRESHOLD)
    hard_limit = _parse_int_env("YAHOO_SHOPPING_MCP_HARD_LIMIT", DEFAULT_HARD_LIMIT)
    global_rate_limit = _parse_int_env("YAHOO_SHOPPING_MCP_GLOBAL_RATE_LIMIT", DEFAULT_GLOBAL_RATE_LIMIT)
    global_window_seconds = _parse_int_env(
        "YAHOO_SHOPPING_MCP_GLOBAL_WINDOW_SECONDS", DEFAULT_GLOBAL_WINDOW_SECONDS
    )
    allowed_hosts = _parse_csv_env("YAHOO_SHOPPING_MCP_ALLOWED_HOSTS")
    allowed_origins = _parse_csv_env("YAHOO_SHOPPING_MCP_ALLOWED_ORIGINS")

    return Settings(
        app_id=app_id,
        host=host,
        port=port,
        cache_ttl_seconds=cache_ttl_seconds,
        base_rate_seconds=base_rate_seconds,
        warning_threshold=warning_threshold,
        hard_limit=hard_limit,
        global_rate_limit=global_rate_limit,
        global_window_seconds=global_window_seconds,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
        state_dir=base_dir / STATE_DIRNAME,
        cache_dir=base_dir / CACHE_DIRNAME,
    )
