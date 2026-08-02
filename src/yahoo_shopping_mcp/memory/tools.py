from __future__ import annotations

import json
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from yahoo_shopping_mcp.config import Settings
from yahoo_shopping_mcp.memory.enums import (
    MutationOperation,
    NodeStatus,
    NodeType,
    RelationType,
)
from yahoo_shopping_mcp.memory.errors import MemoryError, MemoryErrorKind
from yahoo_shopping_mcp.memory.models import (
    ApplyMutationRequest,
    ClaimNeighborhoodRequest,
    DeleteMemoryRequest,
    ExportMemoryRequest,
    MutationOperationInput,
    PreferenceGraphRequest,
    PreviewMutationRequest,
    RouteMemorySpacesRequest,
    SearchClaimCandidatesRequest,
)
from yahoo_shopping_mcp.memory.ontology import SCHEMA_VERSION, ontology_document
from yahoo_shopping_mcp.memory.preview import render_preview_svg
from yahoo_shopping_mcp.memory.repository import PreferenceGraphRepository
from yahoo_shopping_mcp.memory.resources import (
    INSTRUCTIONS_RESOURCE_URI,
    MEMORY_INSTRUCTIONS,
    PROFILE_SUMMARY_RESOURCE_URI,
    SCHEMA_RESOURCE_URI,
    schema_resource_text,
)


def _error(exc: MemoryError) -> ToolError:
    return ToolError(json.dumps(exc.to_dict(), ensure_ascii=False))


def _repository(mcp: FastMCP) -> PreferenceGraphRepository:
    repository = mcp.get_context().request_context.lifespan_context.get("memory_repository")
    if repository is None:
        raise MemoryError(
            MemoryErrorKind.IDENTITY_UNAVAILABLE,
            "Agentic Memory repository is unavailable.",
            retryable=True,
        )
    return repository


def _bounded(value: int, maximum: int, field: str) -> None:
    if value > maximum:
        raise _error(
            MemoryError(
                MemoryErrorKind.LIMIT_EXCEEDED,
                "Requested memory output exceeds the configured bound.",
                field=field,
                maximum=maximum,
            )
        )


async def _run(operation) -> dict[str, object]:
    try:
        return await operation()
    except MemoryError as exc:
        raise _error(exc) from exc
    except ValidationError as exc:
        raise _error(
            MemoryError(
                MemoryErrorKind.VALIDATION_ERROR,
                "Memory request failed validation.",
                fields=[".".join(str(part) for part in error["loc"]) for error in exc.errors()],
            )
        ) from exc
    except Exception as exc:
        # Never expose Neo4j messages, Cypher, credentials, or received memory text.
        raise _error(
            MemoryError(
                MemoryErrorKind.VALIDATION_ERROR,
                "Agentic Memory repository is temporarily unavailable.",
                retryable=True,
            )
        ) from exc


def register_memory_surface(mcp: FastMCP, settings: Settings) -> None:
    subject_id = settings.memory_subject_id
    if not subject_id:
        raise RuntimeError("single_user memory mode requires a fixed subject ID.")

    @mcp.resource(
        SCHEMA_RESOURCE_URI,
        name="yahoo-shopping-memory-schema",
        title="Yahoo! Shopping Agentic Memory schema",
        mime_type="application/json",
    )
    def memory_schema_resource() -> str:
        return schema_resource_text()

    @mcp.resource(
        INSTRUCTIONS_RESOURCE_URI,
        name="yahoo-shopping-memory-instructions",
        title="Yahoo! Shopping Agentic Memory instructions",
        mime_type="text/plain",
    )
    def memory_instructions_resource() -> str:
        return MEMORY_INSTRUCTIONS

    @mcp.resource(
        PROFILE_SUMMARY_RESOURCE_URI,
        name="yahoo-shopping-memory-profile-summary",
        title="Current Yahoo! Shopping memory profile summary",
        mime_type="application/json",
    )
    async def memory_profile_summary_resource() -> str:
        result = await _run(lambda: _repository(mcp).get_profile_summary(subject_id))
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool(
        title="購買嗜好メモリの固定スキーマ",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
        structured_output=True,
    )
    async def get_preference_memory_schema() -> dict[str, object]:
        return ontology_document()

    @mcp.tool(
        title="関連 Memory Space の検索",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
        structured_output=True,
    )
    async def route_memory_spaces(
        query: Annotated[str, Field(min_length=1, max_length=500)],
        task: Annotated[str | None, Field(min_length=1, max_length=64)] = None,
        limit: Annotated[int | None, Field(ge=1)] = None,
    ) -> dict[str, object]:
        request = RouteMemorySpacesRequest(
            query=query,
            task=task,
            limit=limit or min(5, settings.memory_max_spaces_per_query),
        )
        _bounded(request.limit, settings.memory_max_spaces_per_query, "limit")
        return await _run(
            lambda: _repository(mcp).route_spaces(subject_id, request.query, request.limit)
        )

    @mcp.tool(
        title="既存 Claim 候補の検索",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
        structured_output=True,
    )
    async def search_claim_candidates(
        query: Annotated[str, Field(min_length=1, max_length=500)],
        space_ids: Annotated[list[str] | None, Field(max_length=50)] = None,
        task: Annotated[str | None, Field(min_length=1, max_length=64)] = None,
        node_types: Annotated[list[NodeType] | None, Field(min_length=1)] = None,
        status: Annotated[list[NodeStatus] | None, Field(min_length=1)] = None,
        limit: Annotated[int | None, Field(ge=1)] = None,
    ) -> dict[str, object]:
        request = SearchClaimCandidatesRequest(
            query=query,
            space_ids=space_ids or [],
            task=task,
            node_types=node_types or [NodeType.CLAIM, NodeType.PREFERENCE_RULE, NodeType.CONTEXT],
            status=status or [NodeStatus.ACTIVE],
            limit=limit or min(20, settings.memory_max_claim_candidates),
        )
        _bounded(len(request.space_ids), settings.memory_max_spaces_per_query, "space_ids")
        _bounded(request.limit, settings.memory_max_claim_candidates, "limit")
        return await _run(
            lambda: _repository(mcp).search_candidates(
                subject_id,
                request.model_dump(mode="json"),
            )
        )

    @mcp.tool(
        title="Claim 周辺の局所グラフ",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
        structured_output=True,
    )
    async def get_claim_neighborhood(
        root_node_ids: Annotated[list[str], Field(min_length=1, max_length=30)],
        relations: Annotated[list[RelationType] | None, Field(min_length=1)] = None,
        max_depth: Annotated[int, Field(ge=1)] = 2,
        max_nodes: Annotated[int, Field(ge=1)] = 50,
        max_edges: Annotated[int, Field(ge=1)] = 100,
        include_evidence_summary: bool = True,
    ) -> dict[str, object]:
        request = ClaimNeighborhoodRequest(
            root_node_ids=root_node_ids,
            relations=relations or list(RelationType),
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_edges=max_edges,
            include_evidence_summary=include_evidence_summary,
        )
        _validate_graph_bounds(request, settings)
        return await _run(
            lambda: _repository(mcp).get_neighborhood(
                subject_id,
                request.model_dump(mode="json"),
            )
        )

    @mcp.tool(
        title="制限付き購買嗜好グラフ",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
        structured_output=True,
    )
    async def get_preference_graph(
        root_node_ids: Annotated[list[str] | None, Field(max_length=30)] = None,
        space_ids: Annotated[list[str] | None, Field(max_length=50)] = None,
        relations: Annotated[list[RelationType] | None, Field(min_length=1)] = None,
        status: Annotated[list[NodeStatus] | None, Field(min_length=1)] = None,
        max_depth: Annotated[int, Field(ge=1)] = 2,
        max_nodes: Annotated[int, Field(ge=1)] = 50,
        max_edges: Annotated[int, Field(ge=1)] = 100,
        include_evidence_summary: bool = True,
    ) -> dict[str, object]:
        request = PreferenceGraphRequest(
            root_node_ids=root_node_ids or [],
            space_ids=space_ids or [],
            relations=relations or list(RelationType),
            status=status or [NodeStatus.ACTIVE],
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_edges=max_edges,
            include_evidence_summary=include_evidence_summary,
        )
        _bounded(len(request.space_ids), settings.memory_max_spaces_per_query, "space_ids")
        _validate_graph_bounds(request, settings)
        return await _run(
            lambda: _repository(mcp).get_graph(subject_id, request.model_dump(mode="json"))
        )

    @mcp.tool(
        title="購買嗜好メモリ更新の Preview",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False),
        structured_output=True,
    )
    async def preview_preference_memory_update(
        base_revision: Annotated[int, Field(ge=0)],
        context_snapshot_id: Annotated[str, Field(min_length=1, max_length=128)],
        idempotency_key: Annotated[str, Field(min_length=1, max_length=128)],
        operations: Annotated[list[MutationOperationInput], Field(min_length=1, max_length=50)],
        schema_version: Annotated[str, Field(min_length=1, max_length=20)] = SCHEMA_VERSION,
    ) -> dict[str, object]:
        if schema_version != SCHEMA_VERSION:
            raise _error(
                MemoryError(
                    MemoryErrorKind.SCHEMA_VERSION_MISMATCH,
                    "The mutation schema version is not supported.",
                    expected=SCHEMA_VERSION,
                    received=schema_version,
                )
            )
        request = PreviewMutationRequest(
            schema_version=schema_version,
            base_revision=base_revision,
            context_snapshot_id=context_snapshot_id,
            idempotency_key=idempotency_key,
            operations=operations,
        )
        result = await _run(
            lambda: _repository(mcp).preview_mutation(
                subject_id,
                request.model_dump(mode="json", exclude_none=True),
            )
        )
        result["preview_svg"] = render_preview_svg(result)
        return result

    @mcp.tool(
        title="確認済み購買嗜好メモリ更新の適用",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
        structured_output=True,
    )
    async def apply_preference_memory_update(
        mutation_id: Annotated[str, Field(min_length=1, max_length=128)],
        preview_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")],
        confirmation: bool,
    ) -> dict[str, object]:
        if confirmation is not True:
            raise _error(
                MemoryError(
                    MemoryErrorKind.CONFIRMATION_REQUIRED,
                    "Explicit confirmation is required.",
                )
            )
        request = ApplyMutationRequest(
            mutation_id=mutation_id,
            preview_hash=preview_hash,
            confirmation=confirmation,
        )
        return await _run(
            lambda: _repository(mcp).apply_mutation(
                subject_id,
                request.mutation_id,
                request.preview_hash,
            )
        )

    @mcp.tool(
        title="購買嗜好メモリのエクスポート",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
        structured_output=True,
    )
    async def export_preference_memory(
        cursor: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 100,
        status: Annotated[list[NodeStatus] | None, Field(min_length=1)] = None,
        include_evidence_summary: bool = True,
        format: Literal["json"] = "json",
    ) -> dict[str, object]:
        request = ExportMemoryRequest(
            cursor=cursor,
            limit=limit,
            status=status
            or [NodeStatus.ACTIVE, NodeStatus.RETIRED, NodeStatus.SUPERSEDED],
            include_evidence_summary=include_evidence_summary,
            format=format,
        )
        return await _run(
            lambda: _repository(mcp).export_graph(subject_id, request.model_dump(mode="json"))
        )

    @mcp.tool(
        title="購買嗜好メモリの明示削除または退役",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
        structured_output=True,
    )
    async def delete_preference_memory(
        scope: Literal["nodes", "source", "all"],
        idempotency_key: Annotated[str, Field(min_length=1, max_length=128)],
        confirmation: bool,
        node_ids: Annotated[list[str] | None, Field(max_length=100)] = None,
        source_ids: Annotated[list[str] | None, Field(max_length=100)] = None,
        mode: Literal["retire", "delete"] = "retire",
    ) -> dict[str, object]:
        if confirmation is not True:
            raise _error(
                MemoryError(
                    MemoryErrorKind.CONFIRMATION_REQUIRED,
                    "Explicit confirmation is required.",
                )
            )
        request = DeleteMemoryRequest(
            scope=scope,
            node_ids=node_ids or [],
            source_ids=source_ids or [],
            mode=mode,
            confirmation=confirmation,
            idempotency_key=idempotency_key,
        )
        return await _run(
            lambda: _repository(mcp).delete_graph(subject_id, request.model_dump(mode="json"))
        )

    preview_tool = mcp._tool_manager.get_tool("preview_preference_memory_update")
    if preview_tool is not None:
        preview_tool.parameters["description"] = (
            "Only the fixed operation enum is accepted: "
            + ", ".join(item.value for item in MutationOperation)
            + ". New nodes use client_ref; server IDs, subject IDs, labels, and Cypher are not accepted."
        )
        preview_tool.parameters["properties"]["schema_version"]["const"] = SCHEMA_VERSION
    for tool_name in ("apply_preference_memory_update", "delete_preference_memory"):
        confirmation_tool = mcp._tool_manager.get_tool(tool_name)
        if confirmation_tool is not None:
            confirmation_tool.parameters["properties"]["confirmation"]["const"] = True


def _validate_graph_bounds(
    request: ClaimNeighborhoodRequest | PreferenceGraphRequest,
    settings: Settings,
) -> None:
    _bounded(request.max_depth, settings.memory_max_depth, "max_depth")
    _bounded(request.max_nodes, settings.memory_max_subgraph_nodes, "max_nodes")
    _bounded(request.max_edges, settings.memory_max_subgraph_edges, "max_edges")
