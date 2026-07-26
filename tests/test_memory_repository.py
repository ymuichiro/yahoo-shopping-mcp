from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from yahoo_shopping_mcp.memory.canonicalization import canonical_key
from yahoo_shopping_mcp.memory.enums import NodeType
from yahoo_shopping_mcp.memory.errors import MemoryError, MemoryErrorKind
from yahoo_shopping_mcp.memory.neo4j_repository import (
    _SCHEMA_QUERIES,
    Neo4jPreferenceGraphRepository,
    _normalize_and_preflight,
    _preview_result,
    _public_properties,
)


def _node(node_id: str, node_type: str, **properties: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "node_type": node_type,
        "properties": {
            "id": node_id,
            "subject_id": "fixed-subject",
            "schema_version": "1.0",
            "status": "active",
            "revision": 0,
            **properties,
        },
    }


def _edge(source: str, relation: str, target: str) -> dict[str, str]:
    return {"source": source, "relation": relation, "target": target}


@pytest.fixture
def existing_graph() -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    nodes = [
        _node("rul_mobile", "PreferenceRule", summary="Prefer portability"),
        _node("ctx_mobile", "Context", name="Mobile work"),
        _node(
            "clm_portable",
            "Claim",
            claim_kind="product_attribute_preference",
            statement="Prefer portability",
        ),
        _node(
            "clm_screen",
            "Claim",
            claim_kind="product_attribute_preference",
            statement="Prefer a large screen",
        ),
        _node("evd_existing", "Evidence", evidence_kind="explicit_statement"),
        _node("src_existing", "Source", source_kind="conversation"),
    ]
    edges = [
        _edge("rul_mobile", "WHEN", "ctx_mobile"),
        _edge("rul_mobile", "PREFERS", "clm_portable"),
        _edge("rul_mobile", "OVER", "clm_screen"),
        _edge("rul_mobile", "SUPPORTED_BY", "evd_existing"),
        _edge("evd_existing", "HAS_SOURCE", "src_existing"),
    ]
    return nodes, edges


def _add_evidence_request() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "base_revision": 7,
        "context_snapshot_id": "snap_7_abc",
        "idempotency_key": "preview-1",
        "operations": [
            {
                "operation": "add_evidence",
                "target_node_id": "rul_mobile",
                "evidence": {
                    "client_ref": "evidence-1",
                    "evidence_kind": "explicit_statement",
                    "summary": "The user explicitly prefers portability.",
                    "observed_at": "2026-07-25T13:00:00+09:00",
                    "source": {
                        "client_ref": "source-1",
                        "source_kind": "conversation",
                        "source_ref": "current-message",
                    },
                },
            }
        ],
    }


def test_valid_add_evidence_normalizes_without_mutating_active_graph(existing_graph) -> None:
    nodes, edges = existing_graph
    before_nodes, before_edges = deepcopy(nodes), deepcopy(edges)

    patch, preview, affected = _normalize_and_preflight(
        "fixed-subject",
        _add_evidence_request(),
        nodes,
        edges,
    )

    assert nodes == before_nodes
    assert edges == before_edges
    assert [item["operation"] for item in patch["operations"]] == [
        "create_node",
        "create_node",
        "add_edge",
        "add_edge",
    ]
    assert preview[0]["operation"] == "add_evidence"
    assert set(preview[0]["assigned_client_refs"]) == {"evidence-1", "source-1"}
    assert "rul_mobile" in affected
    assert all(item["properties"]["subject_id"] == "fixed-subject" for item in patch["operations"][:2])


def test_preflight_caps_confidence_from_evidence_kind(existing_graph) -> None:
    nodes, edges = existing_graph
    nodes[0]["properties"]["confidence"] = 1.0

    patch, _, _ = _normalize_and_preflight(
        "fixed-subject",
        _add_evidence_request(),
        nodes,
        edges,
    )

    confidence_update = next(
        item
        for item in patch["operations"]
        if item["operation"] == "update_node_properties"
        and item["target_node_id"] == "rul_mobile"
    )
    assert confidence_update["properties"]["confidence"] == 0.95


def test_duplicate_edge_and_depends_on_cycle_are_rejected(existing_graph) -> None:
    nodes, edges = existing_graph
    duplicate = {
        **_add_evidence_request(),
        "operations": [
            {
                "operation": "add_edge",
                "source": {"node_id": "rul_mobile"},
                "relation": "PREFERS",
                "target": {"node_id": "clm_portable"},
            }
        ],
    }
    with pytest.raises(MemoryError) as duplicate_error:
        _normalize_and_preflight("fixed-subject", duplicate, nodes, edges)
    assert duplicate_error.value.kind == MemoryErrorKind.DUPLICATE_DETECTED

    edges.append(_edge("clm_portable", "DEPENDS_ON", "clm_screen"))
    cycle = {
        **_add_evidence_request(),
        "operations": [
            {
                "operation": "add_edge",
                "source": {"node_id": "clm_screen"},
                "relation": "DEPENDS_ON",
                "target": {"node_id": "clm_portable"},
            }
        ],
    }
    with pytest.raises(MemoryError) as cycle_error:
        _normalize_and_preflight("fixed-subject", cycle, nodes, edges)
    assert cycle_error.value.kind == MemoryErrorKind.CYCLE_DETECTED


def test_duplicate_canonical_claim_and_incomplete_active_claim_are_rejected(existing_graph) -> None:
    nodes, edges = existing_graph
    nodes[2]["properties"]["canonical_key"] = canonical_key(
        subject_id="fixed-subject",
        node_type=NodeType.CLAIM,
        kind="product_attribute_preference",
        subject="Prefer portability",
    )
    duplicate = {
        **_add_evidence_request(),
        "operations": [
            {
                "operation": "create_node",
                "node": {
                    "node_type": "Claim",
                    "client_ref": "claim-1",
                    "claim_kind": "product_attribute_preference",
                    "statement": "Prefer portability",
                },
            }
        ],
    }
    with pytest.raises(MemoryError) as duplicate_error:
        _normalize_and_preflight("fixed-subject", duplicate, nodes, edges)
    assert duplicate_error.value.kind == MemoryErrorKind.DUPLICATE_DETECTED

    incomplete = deepcopy(duplicate)
    incomplete["operations"][0]["node"]["statement"] = "Prefer low weight"
    incomplete["operations"][0]["node"]["status"] = "active"
    with pytest.raises(MemoryError) as integrity_error:
        _normalize_and_preflight("fixed-subject", incomplete, nodes, edges)
    assert integrity_error.value.kind == MemoryErrorKind.VALIDATION_ERROR
    assert "TARGETS" in integrity_error.value.message


def test_active_rule_cannot_target_retired_claim(existing_graph) -> None:
    nodes, edges = existing_graph
    nodes[3]["properties"]["status"] = "retired"
    request = {
        **_add_evidence_request(),
        "operations": [
            {
                "operation": "add_edge",
                "source": {"node_id": "rul_mobile"},
                "relation": "PREFERS",
                "target": {"node_id": "clm_screen"},
            }
        ],
    }
    with pytest.raises(MemoryError) as error:
        _normalize_and_preflight("fixed-subject", request, nodes, edges)
    assert error.value.kind == MemoryErrorKind.VALIDATION_ERROR
    assert "inactive Claim" in error.value.message


def test_missing_subject_node_and_schema_mismatch_are_rejected(existing_graph) -> None:
    nodes, edges = existing_graph
    missing = {
        **_add_evidence_request(),
        "operations": [
            {
                "operation": "retire_node",
                "target_node_id": "other-subject-node",
            }
        ],
    }
    with pytest.raises(MemoryError) as missing_error:
        _normalize_and_preflight("fixed-subject", missing, nodes, edges)
    assert missing_error.value.kind == MemoryErrorKind.NOT_FOUND

    schema = {**_add_evidence_request(), "schema_version": "2.0"}
    with pytest.raises(MemoryError) as schema_error:
        _normalize_and_preflight("fixed-subject", schema, nodes, edges)
    assert schema_error.value.kind == MemoryErrorKind.SCHEMA_VERSION_MISMATCH


def test_claim_update_rebuilds_server_owned_search_and_canonical_fields(existing_graph) -> None:
    nodes, edges = existing_graph
    request = {
        **_add_evidence_request(),
        "operations": [
            {
                "operation": "update_node_properties",
                "target_node_id": "clm_portable",
                "expected_revision": 0,
                "update": {
                    "node_type": "Claim",
                    "statement": "Prefer very lightweight products",
                },
            }
        ],
    }

    patch, _, _ = _normalize_and_preflight("fixed-subject", request, nodes, edges)
    properties = patch["operations"][0]["properties"]

    assert properties["search_text"] == "Prefer very lightweight products"
    assert properties["canonical_key"] == canonical_key(
        subject_id="fixed-subject",
        node_type=NodeType.CLAIM,
        kind="product_attribute_preference",
        subject="Prefer very lightweight products",
    )


def test_preview_result_rejects_expiry_and_public_output_redacts_internal_fields() -> None:
    future = datetime.now(UTC) + timedelta(minutes=5)
    stored = {
        "status": "pending",
        "expires_at": future,
        "preview_result_json": '{"status":"ready_for_confirmation"}',
    }
    assert _preview_result(stored) == {"status": "ready_for_confirmation"}

    stored["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(MemoryError) as error:
        _preview_result(stored)
    assert error.value.kind == MemoryErrorKind.MUTATION_EXPIRED

    assert _public_properties(
        {
            "statement": "Prefer portability",
            "subject_id": "fixed-subject",
            "source_ref": "current-message",
            "embedding": [1.0],
            "normalized_patch_json": "secret",
        }
    ) == {"statement": "Prefer portability"}


class _Eager:
    records: list[Any] = []


class _Driver:
    def __init__(self) -> None:
        self.verified = False
        self.closed = False
        self.queries: list[tuple[str, dict[str, Any]]] = []

    async def verify_connectivity(self) -> None:
        self.verified = True

    async def execute_query(
        self,
        query: str,
        *,
        parameters_: dict[str, Any],
        database_: str,
    ) -> _Eager:
        assert database_ == "neo4j"
        self.queries.append((query, parameters_))
        return _Eager()

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_initialize_uses_only_fixed_schema_queries() -> None:
    driver = _Driver()
    repository = Neo4jPreferenceGraphRepository(
        uri="neo4j://unused",
        user="neo4j",
        password="unused",
        driver=driver,  # type: ignore[arg-type]
    )

    await repository.initialize()
    await repository.close()

    assert driver.verified is True
    assert driver.closed is True
    assert [query for query, _ in driver.queries] == list(_SCHEMA_QUERIES)
    assert all(parameters == {} for _, parameters in driver.queries)
    assert any("mutation_idempotency_unique" in query for query in _SCHEMA_QUERIES)
    assert any("FULLTEXT INDEX memory_space_search" in query for query in _SCHEMA_QUERIES)
    assert all("$subject_id" not in query for query in _SCHEMA_QUERIES)
