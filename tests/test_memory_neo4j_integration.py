from __future__ import annotations

import os
from uuid import uuid4

import pytest
from neo4j import AsyncGraphDatabase

from yahoo_shopping_mcp.memory.errors import MemoryError, MemoryErrorKind
from yahoo_shopping_mcp.memory.models import PreviewMutationRequest
from yahoo_shopping_mcp.memory.neo4j_repository import Neo4jPreferenceGraphRepository


pytestmark = pytest.mark.skipif(
    not os.getenv("NEO4J_TEST_URI"),
    reason="Set NEO4J_TEST_URI, NEO4J_TEST_USER, and NEO4J_TEST_PASSWORD for integration tests.",
)


@pytest.mark.anyio
async def test_neo4j_preview_apply_reads_export_delete_and_subject_isolation() -> None:
    uri = os.environ["NEO4J_TEST_URI"]
    user = os.getenv("NEO4J_TEST_USER", "neo4j")
    password = os.environ["NEO4J_TEST_PASSWORD"]
    database = os.getenv("NEO4J_TEST_DATABASE", "neo4j")
    subject_id = f"integration-{uuid4().hex}"
    other_subject_id = f"integration-{uuid4().hex}"
    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    repository = Neo4jPreferenceGraphRepository(
        uri=uri,
        user=user,
        password=password,
        database=database,
        driver=driver,
    )

    try:
        await repository.initialize()
        initial = await repository.get_neighborhood(
            subject_id,
            {
                "root_node_ids": ["missing-root"],
                "relations": ["TARGETS"],
                "max_depth": 1,
                "max_nodes": 10,
                "max_edges": 10,
                "include_evidence_summary": True,
            },
        )
        request = PreviewMutationRequest.model_validate(
            {
                "schema_version": "1.0",
                "base_revision": 0,
                "context_snapshot_id": initial["snapshot_id"],
                "idempotency_key": f"preview-{uuid4().hex}",
                "operations": [
                    {
                        "operation": "create_node",
                        "node": {
                            "node_type": "Concept",
                            "client_ref": "concept-1",
                            "concept_kind": "product_attribute",
                            "name": "Lightweight",
                        },
                    },
                    {
                        "operation": "create_node",
                        "node": {
                            "node_type": "MemorySpace",
                            "client_ref": "space-1",
                            "space_key": "mobile_work",
                            "name": "Mobile work",
                            "summary": "Portable work preferences",
                            "keywords": ["portable", "weight"],
                        },
                    },
                    {
                        "operation": "create_node",
                        "node": {
                            "node_type": "Claim",
                            "client_ref": "claim-1",
                            "claim_kind": "product_attribute_preference",
                            "statement": "Prefer lightweight products",
                            "status": "active",
                        },
                    },
                    {
                        "operation": "add_edge",
                        "source": {"client_ref": "claim-1"},
                        "relation": "TARGETS",
                        "target": {"client_ref": "concept-1"},
                    },
                    {
                        "operation": "assign_space",
                        "node": {"client_ref": "claim-1"},
                        "space": {"client_ref": "space-1"},
                    },
                    {
                        "operation": "add_evidence",
                        "target_client_ref": "claim-1",
                        "evidence": {
                            "client_ref": "evidence-1",
                            "evidence_kind": "explicit_statement",
                            "summary": "The user explicitly prefers lightweight products.",
                            "observed_at": "2026-07-25T13:00:00+09:00",
                            "source": {
                                "client_ref": "source-1",
                                "source_kind": "conversation",
                                "source_ref": "integration-message",
                            },
                        },
                    },
                ],
            }
        )

        preview = await repository.preview_mutation(
            subject_id,
            request.model_dump(mode="json", exclude_none=True),
        )
        assert preview["status"] == "ready_for_confirmation"
        assert (await repository.get_profile_summary(subject_id))["active_claim_count"] == 0

        applied = await repository.apply_mutation(
            subject_id,
            preview["mutation_id"],
            preview["preview_hash"],
        )
        assert applied["new_revision"] == 1
        assert (
            await repository.apply_mutation(
                subject_id,
                preview["mutation_id"],
                preview["preview_hash"],
            )
        ) == applied

        profile = await repository.get_profile_summary(subject_id)
        assert profile["profile_revision"] == 1
        assert profile["active_claim_count"] == 1
        assert (await repository.route_spaces(subject_id, "portable lightweight", 5))["spaces"]
        candidates = await repository.search_candidates(
            subject_id,
            {
                "query": "Prefer lightweight products",
                "node_types": ["Claim"],
                "status": ["active"],
                "space_ids": [],
                "limit": 20,
            },
        )
        assert candidates["candidates"][0]["statement"] == "Prefer lightweight products"

        claim_id = next(node_id for node_id in applied["created_node_ids"] if node_id.startswith("clm_"))
        source_id = next(node_id for node_id in applied["created_node_ids"] if node_id.startswith("src_"))
        neighborhood = await repository.get_neighborhood(
            subject_id,
            {
                "root_node_ids": [claim_id],
                "relations": ["TARGETS", "BELONGS_TO", "SUPPORTED_BY", "HAS_SOURCE"],
                "max_depth": 3,
                "max_nodes": 20,
                "max_edges": 30,
                "include_evidence_summary": True,
            },
        )
        assert neighborhood["is_local_graph"] is True
        assert len(neighborhood["nodes"]) == 5
        assert neighborhood["retrieval"]["truncated"] is False
        assert (await repository.export_graph(subject_id, {"limit": 100}))["nodes"]
        assert (await repository.export_graph(other_subject_id, {"limit": 100}))["nodes"] == []

        with pytest.raises(MemoryError) as source_error:
            await repository.delete_graph(
                subject_id,
                {
                    "scope": "source",
                    "source_ids": [source_id],
                    "node_ids": [],
                    "mode": "delete",
                    "confirmation": True,
                    "idempotency_key": f"source-delete-{uuid4().hex}",
                },
            )
        assert source_error.value.kind == MemoryErrorKind.VALIDATION_ERROR

        delete_request = {
            "scope": "all",
            "source_ids": [],
            "node_ids": [],
            "mode": "delete",
            "confirmation": True,
            "idempotency_key": f"delete-{uuid4().hex}",
        }
        deleted = await repository.delete_graph(subject_id, delete_request)
        assert await repository.delete_graph(subject_id, delete_request) == deleted
    finally:
        await driver.execute_query(
            "MATCH (node) WHERE node.subject_id IN $subject_ids DETACH DELETE node",
            subject_ids=[subject_id, other_subject_id],
            database_=database,
        )
        await repository.close()
