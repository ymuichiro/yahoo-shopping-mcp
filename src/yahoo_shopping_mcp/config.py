from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from yahoo_shopping_mcp.constants import (
    CACHE_DIRNAME,
    DEFAULT_BASE_RATE_SECONDS,
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_GLOBAL_RATE_LIMIT,
    DEFAULT_GLOBAL_WINDOW_SECONDS,
    DEFAULT_HOST,
    DEFAULT_PORT,
    STATE_DIRNAME,
)

MemoryMode = Literal["disabled", "single_user"]


@dataclass(slots=True)
class Settings:
    app_id: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    base_rate_seconds: float = DEFAULT_BASE_RATE_SECONDS
    global_rate_limit: int = DEFAULT_GLOBAL_RATE_LIMIT
    global_window_seconds: int = DEFAULT_GLOBAL_WINDOW_SECONDS
    allowed_hosts: list[str] | None = None
    allowed_origins: list[str] | None = None
    state_dir: Path = Path(".local") / STATE_DIRNAME
    cache_dir: Path = Path(".local") / CACHE_DIRNAME
    memory_mode: MemoryMode = "disabled"
    memory_subject_id: str | None = None
    memory_require_preview: bool = True
    memory_observation_ttl_seconds: int = 86400
    memory_mutation_ttl_seconds: int = 3600
    memory_max_spaces_per_query: int = 5
    memory_max_claim_candidates: int = 30
    memory_max_subgraph_nodes: int = 100
    memory_max_subgraph_edges: int = 250
    memory_max_depth: int = 3
    neo4j_uri: str | None = None
    neo4j_user: str | None = None
    neo4j_password: str | None = None
    neo4j_database: str = "neo4j"

    def __post_init__(self) -> None:
        if self.memory_mode not in ("disabled", "single_user"):
            raise RuntimeError("memory_mode must be disabled or single_user.")
        if not self.memory_require_preview:
            raise RuntimeError("memory_require_preview must remain true.")
        for name in (
            "memory_observation_ttl_seconds",
            "memory_mutation_ttl_seconds",
            "memory_max_spaces_per_query",
            "memory_max_claim_candidates",
            "memory_max_subgraph_nodes",
            "memory_max_subgraph_edges",
            "memory_max_depth",
        ):
            if getattr(self, name) <= 0:
                raise RuntimeError(f"{name} must be a positive integer.")
        maximums = {
            "memory_max_spaces_per_query": 50,
            "memory_max_claim_candidates": 100,
            "memory_max_subgraph_nodes": 100,
            "memory_max_subgraph_edges": 250,
            "memory_max_depth": 3,
        }
        for name, maximum in maximums.items():
            if getattr(self, name) > maximum:
                raise RuntimeError(f"{name} must be no greater than {maximum}.")
        if self.memory_mode == "single_user":
            missing = [
                name
                for name in ("memory_subject_id", "neo4j_uri", "neo4j_user", "neo4j_password", "neo4j_database")
                if not getattr(self, name)
            ]
            if missing:
                raise RuntimeError(f"single_user memory mode requires: {', '.join(missing)}.")


def _positive_int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    value = default if not raw else int(raw)
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value


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
    global_rate_raw = (os.getenv("YAHOO_SHOPPING_MCP_GLOBAL_RATE_LIMIT") or "").strip()
    global_rate_limit = DEFAULT_GLOBAL_RATE_LIMIT if not global_rate_raw else int(global_rate_raw)
    global_window_raw = (os.getenv("YAHOO_SHOPPING_MCP_GLOBAL_WINDOW_SECONDS") or "").strip()
    global_window_seconds = DEFAULT_GLOBAL_WINDOW_SECONDS if not global_window_raw else int(global_window_raw)
    allowed_hosts_raw = (os.getenv("YAHOO_SHOPPING_MCP_ALLOWED_HOSTS") or "").strip()
    allowed_hosts = [item.strip() for item in allowed_hosts_raw.split(",") if item.strip()] or None
    allowed_origins_raw = (os.getenv("YAHOO_SHOPPING_MCP_ALLOWED_ORIGINS") or "").strip()
    allowed_origins = [item.strip() for item in allowed_origins_raw.split(",") if item.strip()] or None
    memory_mode_raw = (os.getenv("YAHOO_SHOPPING_MCP_MEMORY_MODE") or "disabled").strip().lower()
    if memory_mode_raw not in ("disabled", "single_user"):
        raise RuntimeError("YAHOO_SHOPPING_MCP_MEMORY_MODE must be disabled or single_user.")
    memory_mode = cast(MemoryMode, memory_mode_raw)
    memory_subject_id = (os.getenv("YAHOO_SHOPPING_MCP_MEMORY_SUBJECT_ID") or "").strip() or None
    memory_require_preview_raw = (os.getenv("YAHOO_SHOPPING_MCP_MEMORY_REQUIRE_PREVIEW") or "true").strip().lower()
    if memory_require_preview_raw != "true":
        raise RuntimeError("YAHOO_SHOPPING_MCP_MEMORY_REQUIRE_PREVIEW must remain true.")
    memory_observation_ttl_seconds = _positive_int_env(
        "YAHOO_SHOPPING_MCP_MEMORY_OBSERVATION_TTL_SECONDS", 86400
    )
    memory_mutation_ttl_seconds = _positive_int_env("YAHOO_SHOPPING_MCP_MEMORY_MUTATION_TTL_SECONDS", 3600)
    memory_max_spaces_per_query = _positive_int_env("YAHOO_SHOPPING_MCP_MEMORY_MAX_SPACES_PER_QUERY", 5)
    memory_max_claim_candidates = _positive_int_env("YAHOO_SHOPPING_MCP_MEMORY_MAX_CLAIM_CANDIDATES", 30)
    memory_max_subgraph_nodes = _positive_int_env("YAHOO_SHOPPING_MCP_MEMORY_MAX_SUBGRAPH_NODES", 100)
    memory_max_subgraph_edges = _positive_int_env("YAHOO_SHOPPING_MCP_MEMORY_MAX_SUBGRAPH_EDGES", 250)
    memory_max_depth = _positive_int_env("YAHOO_SHOPPING_MCP_MEMORY_MAX_DEPTH", 3)
    neo4j_uri = (os.getenv("NEO4J_URI") or "").strip() or None
    neo4j_user = (os.getenv("NEO4J_USER") or "").strip() or None
    neo4j_password = (os.getenv("NEO4J_PASSWORD") or "").strip() or None
    neo4j_database = (os.getenv("NEO4J_DATABASE") or "neo4j").strip()
    if memory_mode == "single_user":
        missing = [
            name
            for name, value in (
                ("YAHOO_SHOPPING_MCP_MEMORY_SUBJECT_ID", memory_subject_id),
                ("NEO4J_URI", neo4j_uri),
                ("NEO4J_USER", neo4j_user),
                ("NEO4J_PASSWORD", neo4j_password),
                ("NEO4J_DATABASE", neo4j_database),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"single_user memory mode requires: {', '.join(missing)}.")
    return Settings(
        app_id=app_id,
        host=host,
        port=port,
        cache_ttl_seconds=cache_ttl_seconds,
        base_rate_seconds=base_rate_seconds,
        global_rate_limit=global_rate_limit,
        global_window_seconds=global_window_seconds,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
        state_dir=base_dir / STATE_DIRNAME,
        cache_dir=base_dir / CACHE_DIRNAME,
        memory_mode=memory_mode,
        memory_subject_id=memory_subject_id,
        memory_require_preview=True,
        memory_observation_ttl_seconds=memory_observation_ttl_seconds,
        memory_mutation_ttl_seconds=memory_mutation_ttl_seconds,
        memory_max_spaces_per_query=memory_max_spaces_per_query,
        memory_max_claim_candidates=memory_max_claim_candidates,
        memory_max_subgraph_nodes=memory_max_subgraph_nodes,
        memory_max_subgraph_edges=memory_max_subgraph_edges,
        memory_max_depth=memory_max_depth,
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
        neo4j_database=neo4j_database,
    )
