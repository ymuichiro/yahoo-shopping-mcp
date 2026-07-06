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
    tool_response_mode: str = "structured"
    state_dir: Path = Path(".local") / STATE_DIRNAME
    cache_dir: Path = Path(".local") / CACHE_DIRNAME


def load_settings() -> Settings:
    app_id = (os.getenv("YAHOO_SHOPPING_APP_ID") or "").strip()
    if not app_id:
        raise RuntimeError("YAHOO_SHOPPING_APP_ID is required.")

    host = (os.getenv("YAHOO_SHOPPING_MCP_HOST") or DEFAULT_HOST).strip() or DEFAULT_HOST
    port_raw = (os.getenv("YAHOO_SHOPPING_MCP_PORT") or "").strip()
    port = DEFAULT_PORT if not port_raw else int(port_raw)
    base_dir = Path((os.getenv("YAHOO_SHOPPING_MCP_DATA_DIR") or ".local").strip() or ".local").resolve()
    cache_ttl_raw = (os.getenv("YAHOO_SHOPPING_MCP_CACHE_TTL_SECONDS") or "").strip()
    cache_ttl_seconds = DEFAULT_CACHE_TTL_SECONDS if not cache_ttl_raw else int(cache_ttl_raw)
    base_rate_raw = (os.getenv("YAHOO_SHOPPING_MCP_BASE_RATE_SECONDS") or "").strip()
    base_rate_seconds = DEFAULT_BASE_RATE_SECONDS if not base_rate_raw else float(base_rate_raw)
    warning_raw = (os.getenv("YAHOO_SHOPPING_MCP_WARNING_THRESHOLD") or "").strip()
    warning_threshold = DEFAULT_WARNING_THRESHOLD if not warning_raw else int(warning_raw)
    hard_limit_raw = (os.getenv("YAHOO_SHOPPING_MCP_HARD_LIMIT") or "").strip()
    hard_limit = DEFAULT_HARD_LIMIT if not hard_limit_raw else int(hard_limit_raw)
    global_rate_raw = (os.getenv("YAHOO_SHOPPING_MCP_GLOBAL_RATE_LIMIT") or "").strip()
    global_rate_limit = DEFAULT_GLOBAL_RATE_LIMIT if not global_rate_raw else int(global_rate_raw)
    global_window_raw = (os.getenv("YAHOO_SHOPPING_MCP_GLOBAL_WINDOW_SECONDS") or "").strip()
    global_window_seconds = DEFAULT_GLOBAL_WINDOW_SECONDS if not global_window_raw else int(global_window_raw)
    allowed_hosts_raw = (os.getenv("YAHOO_SHOPPING_MCP_ALLOWED_HOSTS") or "").strip()
    allowed_hosts = [item.strip() for item in allowed_hosts_raw.split(",") if item.strip()] or None
    allowed_origins_raw = (os.getenv("YAHOO_SHOPPING_MCP_ALLOWED_ORIGINS") or "").strip()
    allowed_origins = [item.strip() for item in allowed_origins_raw.split(",") if item.strip()] or None
    tool_response_mode = (os.getenv("YAHOO_SHOPPING_MCP_TOOL_RESPONSE_MODE") or "structured").strip().lower()
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
