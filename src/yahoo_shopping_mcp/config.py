from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import TypeVar

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

T = TypeVar("T")


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
    tool_response_mode: str = "structured"
    state_dir: Path = Path(".local") / STATE_DIRNAME
    cache_dir: Path = Path(".local") / CACHE_DIRNAME


def _env(name: str, default: T, cast: Callable[[str], T] = lambda value: value) -> T:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    return default if not value else cast(value)


def load_settings() -> Settings:
    app_id = _env("YAHOO_SHOPPING_APP_ID", "")
    if not app_id:
        raise RuntimeError("YAHOO_SHOPPING_APP_ID is required.")

    host = _env("YAHOO_SHOPPING_MCP_HOST", DEFAULT_HOST)
    port = _env("YAHOO_SHOPPING_MCP_PORT", DEFAULT_PORT, int)
    base_dir = Path(_env("YAHOO_SHOPPING_MCP_DATA_DIR", ".local")).resolve()
    cache_ttl_seconds = _env("YAHOO_SHOPPING_MCP_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS, int)
    base_rate_seconds = _env("YAHOO_SHOPPING_MCP_BASE_RATE_SECONDS", DEFAULT_BASE_RATE_SECONDS, float)
    warning_threshold = _env("YAHOO_SHOPPING_MCP_WARNING_THRESHOLD", DEFAULT_WARNING_THRESHOLD, int)
    hard_limit = _env("YAHOO_SHOPPING_MCP_HARD_LIMIT", DEFAULT_HARD_LIMIT, int)
    global_rate_limit = _env("YAHOO_SHOPPING_MCP_GLOBAL_RATE_LIMIT", DEFAULT_GLOBAL_RATE_LIMIT, int)
    global_window_seconds = _env("YAHOO_SHOPPING_MCP_GLOBAL_WINDOW_SECONDS", DEFAULT_GLOBAL_WINDOW_SECONDS, int)
    allowed_hosts = _env(
        "YAHOO_SHOPPING_MCP_ALLOWED_HOSTS",
        None,
        lambda value: [item.strip() for item in value.split(",") if item.strip()] or None,
    )
    allowed_origins = _env(
        "YAHOO_SHOPPING_MCP_ALLOWED_ORIGINS",
        None,
        lambda value: [item.strip() for item in value.split(",") if item.strip()] or None,
    )
    tool_response_mode = _env("YAHOO_SHOPPING_MCP_TOOL_RESPONSE_MODE", "structured").lower()
    if tool_response_mode not in {"structured", "chatgpt"}:
        raise RuntimeError("YAHOO_SHOPPING_MCP_TOOL_RESPONSE_MODE must be one of: structured, chatgpt.")

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
        tool_response_mode=tool_response_mode,
        state_dir=base_dir / STATE_DIRNAME,
        cache_dir=base_dir / CACHE_DIRNAME,
    )
