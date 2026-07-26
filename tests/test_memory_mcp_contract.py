from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from yahoo_shopping_mcp.config import Settings
from yahoo_shopping_mcp.server import create_mcp_server


MEMORY_TOOL_NAMES = {
    "get_preference_memory_schema",
    "route_memory_spaces",
    "search_claim_candidates",
    "get_claim_neighborhood",
    "get_preference_graph",
    "preview_preference_memory_update",
    "apply_preference_memory_update",
    "export_preference_memory",
    "delete_preference_memory",
}
MEMORY_RESOURCE_URIS = {
    "memory://yahoo-shopping/schema/v1",
    "memory://yahoo-shopping/instructions/v1",
    "memory://yahoo-shopping/profile/current/summary",
}
PREVIEW_HASH = f"sha256:{'a' * 64}"


class RecordingMemoryRepository:
    def __init__(self, *, fail_route: bool = False) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fail_route = fail_route

    def _record(self, method: str, *args: Any) -> None:
        self.calls.append((method, args))

    def calls_for(self, method: str) -> list[tuple[Any, ...]]:
        return [args for name, args in self.calls if name == method]

    async def initialize(self) -> None:
        self._record("initialize")

    async def close(self) -> None:
        self._record("close")

    async def cleanup_expired(self) -> dict[str, int]:
        self._record("cleanup_expired")
        return {"observations": 0, "mutations": 0}

    async def get_profile_summary(self, subject_id: str) -> dict[str, Any]:
        self._record("get_profile_summary", subject_id)
        return {
            "schema_version": "1.0",
            "profile_revision": 7,
            "spaces": [{"space_id": "spc_display", "space_key": "display_work"}],
            "active_claim_count": 2,
            "active_purchase_intents": [],
            "unresolved_conflicts": [],
            "recent_changes": [],
            "major_claims": [],
        }

    async def route_spaces(self, subject_id: str, query: str, limit: int) -> dict[str, Any]:
        self._record("route_spaces", subject_id, query, limit)
        if self.fail_route:
            raise RuntimeError("MATCH (n) neo4j://internal password=secret")
        return {
            "schema_version": "1.0",
            "profile_revision": 7,
            "spaces": [
                {
                    "space_id": "spc_display",
                    "space_key": "display_work",
                    "name": "Display work",
                    "scores": {"full_text": 1.0, "final": 1.0},
                    "matched_by": ["exact"],
                }
            ],
            "retrieval": {"method": "hybrid", "truncated": False},
        }

    async def search_candidates(self, subject_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self._record("search_candidates", subject_id, request)
        return {
            "profile_revision": 7,
            "candidates": [
                {
                    "node_id": "clm_portable",
                    "node_type": "Claim",
                    "statement": "Prefer portability",
                    "claim_kind": "product_attribute_preference",
                    "scores": {"full_text": 1.0, "final": 1.0},
                    "matched_by": ["exact"],
                    "recommended_role": "possible_update_target",
                }
            ],
            "retrieval": {
                "candidate_count_before_limit": 1,
                "returned_count": 1,
                "truncated": False,
            },
        }

    async def get_neighborhood(self, subject_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self._record("get_neighborhood", subject_id, request)
        return {
            "snapshot_id": "snap_7",
            "profile_revision": 7,
            "nodes": [{"id": "clm_portable", "type": "Claim", "status": "active"}],
            "edges": [],
            "evidence_summary": {"clm_portable": {"supporting_count": 1, "contradicting_count": 0}},
            "retrieval": {"max_depth": request["max_depth"], "truncated": False},
        }

    async def get_graph(self, subject_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self._record("get_graph", subject_id, request)
        return {
            "snapshot_id": "snap_7",
            "profile_revision": 7,
            "nodes": [],
            "edges": [],
            "retrieval": {"max_depth": request["max_depth"], "truncated": False},
        }

    async def preview_mutation(self, subject_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self._record("preview_mutation", subject_id, request)
        return {
            "status": "ready_for_confirmation",
            "mutation_id": "mut_01",
            "preview_hash": PREVIEW_HASH,
            "expires_at": "2026-07-25T14:00:00+09:00",
            "normalized_operations": request["operations"],
            "duplicates": [],
            "conflicts": [],
            "affected_nodes": ["clm_portable"],
            "requires_confirmation": True,
        }

    async def apply_mutation(
        self,
        subject_id: str,
        mutation_id: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        self._record("apply_mutation", subject_id, mutation_id, preview_hash)
        return {
            "status": "applied",
            "previous_revision": 7,
            "new_revision": 8,
            "created_node_ids": [],
            "updated_node_ids": ["clm_portable"],
        }

    async def export_graph(self, subject_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self._record("export_graph", subject_id, request)
        return {"schema_version": "1.0", "profile_revision": 7, "nodes": [], "edges": []}

    async def delete_graph(self, subject_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self._record("delete_graph", subject_id, request)
        return {"status": "deleted", "previous_revision": 7, "new_revision": 8}


def _yahoo_handler(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "totalResultsAvailable": 1,
            "totalResultsReturned": 1,
            "firstResultsPosition": 1,
            "hits": [
                {
                    "code": "item-1",
                    "name": "Portable Monitor",
                    "url": "https://store.shopping.yahoo.co.jp/example/item-1.html",
                    "price": 19800,
                    "inStock": True,
                    "image": {"medium": "https://item-shopping.c.yimg.jp/i/g/example_item-1"},
                    "seller": {"name": "Example Store"},
                }
            ],
        },
    )


@asynccontextmanager
async def _memory_session(
    tmp_path: Path,
    repository: RecordingMemoryRepository,
) -> AsyncIterator[ClientSession]:
    settings = Settings(
        app_id="test-appid",
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
        memory_mode="single_user",
        memory_subject_id="fixed-subject",
        memory_max_spaces_per_query=2,
        memory_max_claim_candidates=3,
        memory_max_subgraph_nodes=10,
        memory_max_subgraph_edges=20,
        memory_max_depth=2,
        neo4j_uri="neo4j://unused:7687",
        neo4j_user="neo4j",
        neo4j_password="unused",
    )
    upstream_transport = httpx.MockTransport(_yahoo_handler)
    async with httpx.AsyncClient(transport=upstream_transport) as upstream_client:
        app = create_mcp_server(
            settings,
            http_client=upstream_client,
            memory_repository=repository,
        ).streamable_http_app()
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
                async with streamable_http_client("http://127.0.0.1:8000/mcp", http_client=client) as (
                    read_stream,
                    write_stream,
                    _,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        yield session


def _schema_values(value: object) -> set[object]:
    if isinstance(value, dict):
        values = set(value.get("enum", []))
        if "const" in value:
            values.add(value["const"])
        for child in value.values():
            values.update(_schema_values(child))
        return values
    if isinstance(value, list):
        return set().union(*(_schema_values(child) for child in value))
    return set()


@pytest.mark.anyio
async def test_single_user_registers_exact_memory_surface_and_fixed_ontology(tmp_path) -> None:
    repository = RecordingMemoryRepository()

    async with _memory_session(tmp_path, repository) as session:
        tools = await session.list_tools()
        resources = await session.list_resources()
        schema_resource = await session.read_resource("memory://yahoo-shopping/schema/v1")
        instructions_resource = await session.read_resource("memory://yahoo-shopping/instructions/v1")
        profile_resource = await session.read_resource("memory://yahoo-shopping/profile/current/summary")

    tool_map = {tool.name: tool for tool in tools.tools}
    memory_resources = {
        str(resource.uri) for resource in resources.resources if str(resource.uri).startswith("memory://")
    }
    assert set(tool_map) - {"search_products"} == MEMORY_TOOL_NAMES
    assert len(MEMORY_TOOL_NAMES) == 9
    assert memory_resources == MEMORY_RESOURCE_URIS
    assert len(memory_resources) == 3

    schema_document = json.loads(schema_resource.contents[0].text)
    assert schema_document["schema_version"] == "1.0"
    assert "Claim" in schema_document["node_types"]
    assert "product_attribute_preference" in schema_document["claim_kinds"]
    assert "explicit_statement" in schema_document["evidence_kinds"]
    assert "add_evidence" in schema_document["mutation_operations"]
    assert any(item["relation"] == "DEPENDS_ON" for item in schema_document["relations"])
    assert "route_memory_spaces" in instructions_resource.contents[0].text
    assert "Preview" in instructions_resource.contents[0].text
    assert json.loads(profile_resource.contents[0].text)["profile_revision"] == 7
    assert repository.calls_for("get_profile_summary") == [("fixed-subject",)]

    candidate_values = _schema_values(tool_map["search_claim_candidates"].inputSchema)
    neighborhood_values = _schema_values(tool_map["get_claim_neighborhood"].inputSchema)
    preview_values = _schema_values(tool_map["preview_preference_memory_update"].inputSchema)
    assert {"Claim", "PreferenceRule", "Context", "active", "retired"}.issubset(candidate_values)
    assert {"DEPENDS_ON", "CONFLICTS_WITH", "SUPERSEDES", "PREFERS", "OVER"}.issubset(
        neighborhood_values
    )
    assert {
        "create_node",
        "add_edge",
        "add_evidence",
        "retire_node",
        "product_attribute_preference",
        "explicit_statement",
    }.issubset(preview_values)


@pytest.mark.anyio
async def test_staged_reads_delegate_fixed_subject_and_enforce_runtime_bounds(tmp_path) -> None:
    repository = RecordingMemoryRepository()

    async with _memory_session(tmp_path, repository) as session:
        route = await session.call_tool(
            "route_memory_spaces",
            {"query": "portable monitor", "task": "memory_update", "limit": 2},
        )
        search = await session.call_tool(
            "search_claim_candidates",
            {
                "query": "prefer portability",
                "space_ids": ["spc_display"],
                "node_types": ["Claim", "Context"],
                "status": ["active"],
                "limit": 3,
            },
        )
        neighborhood = await session.call_tool(
            "get_claim_neighborhood",
            {
                "root_node_ids": ["clm_portable"],
                "relations": ["TARGETS", "DEPENDS_ON"],
                "max_depth": 2,
                "max_nodes": 10,
                "max_edges": 20,
            },
        )
        route_over_limit = await session.call_tool(
            "route_memory_spaces",
            {"query": "portable monitor", "limit": 3},
        )
        neighborhood_over_limit = await session.call_tool(
            "get_claim_neighborhood",
            {
                "root_node_ids": ["clm_portable"],
                "max_depth": 2,
                "max_nodes": 11,
                "max_edges": 20,
            },
        )

    assert route.isError is False
    assert search.isError is False
    assert neighborhood.isError is False
    assert repository.calls_for("route_spaces") == [
        ("fixed-subject", "portable monitor", 2),
    ]
    search_subject, search_request = repository.calls_for("search_candidates")[0]
    assert search_subject == "fixed-subject"
    assert search_request["space_ids"] == ["spc_display"]
    assert search_request["node_types"] == ["Claim", "Context"]
    assert search_request["limit"] == 3
    neighborhood_subject, neighborhood_request = repository.calls_for("get_neighborhood")[0]
    assert neighborhood_subject == "fixed-subject"
    assert neighborhood_request["max_depth"] == 2
    assert neighborhood_request["max_nodes"] == 10
    assert neighborhood_request["max_edges"] == 20
    assert route_over_limit.isError is True
    assert "memory_limit_exceeded" in route_over_limit.content[0].text
    assert neighborhood_over_limit.isError is True
    assert "memory_limit_exceeded" in neighborhood_over_limit.content[0].text


@pytest.mark.anyio
async def test_preview_apply_results_match_and_invalid_confirmation_or_schema_are_rejected(tmp_path) -> None:
    repository = RecordingMemoryRepository()
    operation = {
        "operation": "retire_node",
        "target_node_id": "clm_portable",
        "expected_revision": 7,
    }

    async with _memory_session(tmp_path, repository) as session:
        tools = await session.list_tools()
        preview = await session.call_tool(
            "preview_preference_memory_update",
            {
                "schema_version": "1.0",
                "base_revision": 7,
                "context_snapshot_id": "snap_7",
                "idempotency_key": "preview-1",
                "operations": [operation],
            },
        )
        apply = await session.call_tool(
            "apply_preference_memory_update",
            {
                "mutation_id": "mut_01",
                "preview_hash": PREVIEW_HASH,
                "confirmation": True,
            },
        )
        apply_without_confirmation = await session.call_tool(
            "apply_preference_memory_update",
            {
                "mutation_id": "mut_01",
                "preview_hash": PREVIEW_HASH,
                "confirmation": False,
            },
        )
        invalid_schema = await session.call_tool(
            "preview_preference_memory_update",
            {
                "schema_version": "2.0",
                "base_revision": 7,
                "context_snapshot_id": "snap_7",
                "idempotency_key": "preview-2",
                "operations": [operation],
            },
        )
        delete_without_confirmation = await session.call_tool(
            "delete_preference_memory",
            {
                "scope": "nodes",
                "node_ids": ["clm_portable"],
                "mode": "retire",
                "confirmation": False,
                "idempotency_key": "delete-1",
            },
        )

    assert preview.isError is False
    assert json.loads(preview.content[0].text) == preview.structuredContent
    assert preview.structuredContent["preview_svg"].startswith("<svg ")
    assert "Review and explicitly confirm before Apply." in preview.structuredContent["preview_svg"]
    assert apply.isError is False
    assert json.loads(apply.content[0].text) == apply.structuredContent
    assert repository.calls_for("preview_mutation") == [
        (
            "fixed-subject",
            {
                "schema_version": "1.0",
                "base_revision": 7,
                "context_snapshot_id": "snap_7",
                "idempotency_key": "preview-1",
                "operations": [operation],
            },
        )
    ]
    assert repository.calls_for("apply_mutation") == [
        ("fixed-subject", "mut_01", PREVIEW_HASH),
    ]
    apply_tool = next(tool for tool in tools.tools if tool.name == "apply_preference_memory_update")
    assert apply_tool.inputSchema["properties"]["confirmation"]["const"] is True
    assert apply_without_confirmation.isError is True
    assert "memory_confirmation_required" in apply_without_confirmation.content[0].text
    assert invalid_schema.isError is True
    assert "memory_schema_version_mismatch" in invalid_schema.content[0].text
    assert delete_without_confirmation.isError is True
    assert "memory_confirmation_required" in delete_without_confirmation.content[0].text


@pytest.mark.anyio
async def test_repository_failure_is_sanitized_and_product_search_still_succeeds(tmp_path) -> None:
    repository = RecordingMemoryRepository(fail_route=True)

    async with _memory_session(tmp_path, repository) as session:
        memory_result = await session.call_tool(
            "route_memory_spaces",
            {"query": "portable monitor", "limit": 2},
        )
        search_result = await session.call_tool(
            "search_products",
            {"query": "portable monitor", "results": 1},
        )

    assert memory_result.isError is True
    assert "Agentic Memory repository is temporarily unavailable." in memory_result.content[0].text
    assert "MATCH" not in memory_result.content[0].text
    assert "password" not in memory_result.content[0].text
    assert "neo4j://" not in memory_result.content[0].text
    assert search_result.isError is False
    assert json.loads(search_result.content[0].text)["results"][0]["title"] == "Portable Monitor"
