from __future__ import annotations

import pytest

from yahoo_shopping_mcp.config import Settings, load_settings


MEMORY_ENV_NAMES = (
    "YAHOO_SHOPPING_MCP_MEMORY_MODE",
    "YAHOO_SHOPPING_MCP_MEMORY_SUBJECT_ID",
    "YAHOO_SHOPPING_MCP_MEMORY_REQUIRE_PREVIEW",
    "YAHOO_SHOPPING_MCP_MEMORY_OBSERVATION_TTL_SECONDS",
    "YAHOO_SHOPPING_MCP_MEMORY_MUTATION_TTL_SECONDS",
    "YAHOO_SHOPPING_MCP_MEMORY_MAX_SPACES_PER_QUERY",
    "YAHOO_SHOPPING_MCP_MEMORY_MAX_CLAIM_CANDIDATES",
    "YAHOO_SHOPPING_MCP_MEMORY_MAX_SUBGRAPH_NODES",
    "YAHOO_SHOPPING_MCP_MEMORY_MAX_SUBGRAPH_EDGES",
    "YAHOO_SHOPPING_MCP_MEMORY_MAX_DEPTH",
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
    "NEO4J_DATABASE",
)


@pytest.fixture
def clean_memory_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YAHOO_SHOPPING_APP_ID", "test-appid")
    for name in MEMORY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_memory_is_disabled_by_default(clean_memory_env) -> None:
    settings = load_settings()

    assert settings.memory_mode == "disabled"
    assert settings.memory_subject_id is None
    assert settings.memory_require_preview is True
    assert settings.memory_observation_ttl_seconds == 86400
    assert settings.memory_mutation_ttl_seconds == 3600
    assert settings.memory_max_spaces_per_query == 5
    assert settings.memory_max_claim_candidates == 30
    assert settings.memory_max_subgraph_nodes == 100
    assert settings.memory_max_subgraph_edges == 250
    assert settings.memory_max_depth == 3
    assert settings.neo4j_uri is None
    assert settings.neo4j_user is None
    assert settings.neo4j_password is None
    assert settings.neo4j_database == "neo4j"


@pytest.mark.parametrize("mode", ["multi_user", "invalid"])
def test_memory_rejects_unsupported_modes(clean_memory_env, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv("YAHOO_SHOPPING_MCP_MEMORY_MODE", mode)

    with pytest.raises(RuntimeError, match="must be disabled or single_user"):
        load_settings()


def test_memory_preview_cannot_be_disabled(clean_memory_env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YAHOO_SHOPPING_MCP_MEMORY_REQUIRE_PREVIEW", "false")

    with pytest.raises(RuntimeError, match="must remain true"):
        load_settings()


@pytest.mark.parametrize(
    "name",
    [
        "YAHOO_SHOPPING_MCP_MEMORY_OBSERVATION_TTL_SECONDS",
        "YAHOO_SHOPPING_MCP_MEMORY_MUTATION_TTL_SECONDS",
        "YAHOO_SHOPPING_MCP_MEMORY_MAX_SPACES_PER_QUERY",
        "YAHOO_SHOPPING_MCP_MEMORY_MAX_CLAIM_CANDIDATES",
        "YAHOO_SHOPPING_MCP_MEMORY_MAX_SUBGRAPH_NODES",
        "YAHOO_SHOPPING_MCP_MEMORY_MAX_SUBGRAPH_EDGES",
        "YAHOO_SHOPPING_MCP_MEMORY_MAX_DEPTH",
    ],
)
@pytest.mark.parametrize("value", ["0", "-1"])
def test_memory_ttls_and_limits_must_be_positive(
    clean_memory_env,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match="must be a positive integer"):
        load_settings()


@pytest.mark.parametrize(
    ("name", "value", "maximum"),
    [
        ("YAHOO_SHOPPING_MCP_MEMORY_MAX_SPACES_PER_QUERY", "51", 50),
        ("YAHOO_SHOPPING_MCP_MEMORY_MAX_CLAIM_CANDIDATES", "101", 100),
        ("YAHOO_SHOPPING_MCP_MEMORY_MAX_SUBGRAPH_NODES", "101", 100),
        ("YAHOO_SHOPPING_MCP_MEMORY_MAX_SUBGRAPH_EDGES", "251", 250),
        ("YAHOO_SHOPPING_MCP_MEMORY_MAX_DEPTH", "4", 3),
    ],
)
def test_memory_output_limits_have_repository_safe_maxima(
    clean_memory_env,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    maximum: int,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=f"no greater than {maximum}"):
        load_settings()


@pytest.mark.parametrize(
    "missing_name",
    [
        "YAHOO_SHOPPING_MCP_MEMORY_SUBJECT_ID",
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
    ],
)
def test_single_user_mode_requires_fixed_subject_and_neo4j_credentials(
    clean_memory_env,
    monkeypatch: pytest.MonkeyPatch,
    missing_name: str,
) -> None:
    required = {
        "YAHOO_SHOPPING_MCP_MEMORY_SUBJECT_ID": "local-default",
        "NEO4J_URI": "neo4j://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "test-password",
    }
    monkeypatch.setenv("YAHOO_SHOPPING_MCP_MEMORY_MODE", "single_user")
    for name, value in required.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(missing_name)

    with pytest.raises(RuntimeError, match=missing_name):
        load_settings()


def test_loads_valid_single_user_environment(clean_memory_env, monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "YAHOO_SHOPPING_MCP_MEMORY_MODE": "single_user",
        "YAHOO_SHOPPING_MCP_MEMORY_SUBJECT_ID": "local-default",
        "YAHOO_SHOPPING_MCP_MEMORY_REQUIRE_PREVIEW": "true",
        "YAHOO_SHOPPING_MCP_MEMORY_OBSERVATION_TTL_SECONDS": "7200",
        "YAHOO_SHOPPING_MCP_MEMORY_MUTATION_TTL_SECONDS": "600",
        "YAHOO_SHOPPING_MCP_MEMORY_MAX_SPACES_PER_QUERY": "4",
        "YAHOO_SHOPPING_MCP_MEMORY_MAX_CLAIM_CANDIDATES": "20",
        "YAHOO_SHOPPING_MCP_MEMORY_MAX_SUBGRAPH_NODES": "80",
        "YAHOO_SHOPPING_MCP_MEMORY_MAX_SUBGRAPH_EDGES": "160",
        "YAHOO_SHOPPING_MCP_MEMORY_MAX_DEPTH": "2",
        "NEO4J_URI": "neo4j://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "test-password",
        "NEO4J_DATABASE": "preferences",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = load_settings()

    assert settings.memory_mode == "single_user"
    assert settings.memory_subject_id == "local-default"
    assert settings.memory_require_preview is True
    assert settings.memory_observation_ttl_seconds == 7200
    assert settings.memory_mutation_ttl_seconds == 600
    assert settings.memory_max_spaces_per_query == 4
    assert settings.memory_max_claim_candidates == 20
    assert settings.memory_max_subgraph_nodes == 80
    assert settings.memory_max_subgraph_edges == 160
    assert settings.memory_max_depth == 2
    assert settings.neo4j_uri == "neo4j://localhost:7687"
    assert settings.neo4j_user == "neo4j"
    assert settings.neo4j_password == "test-password"
    assert settings.neo4j_database == "preferences"


def test_accepts_valid_direct_single_user_settings() -> None:
    settings = Settings(
        app_id="test-appid",
        memory_mode="single_user",
        memory_subject_id="local-default",
        neo4j_uri="neo4j://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="test-password",
    )

    assert settings.memory_mode == "single_user"
    assert settings.memory_subject_id == "local-default"
    assert settings.memory_require_preview is True
