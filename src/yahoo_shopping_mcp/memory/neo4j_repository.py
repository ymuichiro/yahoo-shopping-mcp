from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncManagedTransaction

from .canonicalization import canonical_json, canonical_key, memory_preview_hash, normalize_text
from .confidence import adjust_confidence
from .enums import EvidenceKind, MutationOperation, NodeStatus, NodeType, RelationType
from .errors import MemoryError, MemoryErrorKind
from .ontology import RELATION_RULES, SCHEMA_VERSION
from .ranking import reciprocal_rank_fusion
from .repository import PreferenceGraphRepository
from .validation import (
    normalize_conflict_endpoints,
    validate_claim_integrity,
    validate_cycle,
    validate_evidence_connections,
    validate_preference_rule,
    validate_preference_rule_conflicts,
    validate_privacy,
    validate_relation,
)

_GRAPH_RELATIONS = "|".join(relation.value for relation in RelationType)
_NODE_PREFIX = {
    NodeType.USER: "usr",
    NodeType.PROFILE: "prf",
    NodeType.MEMORY_SPACE: "spc",
    NodeType.CLAIM: "clm",
    NodeType.CONCEPT: "con",
    NodeType.CONTEXT: "ctx",
    NodeType.PREFERENCE_RULE: "rul",
    NodeType.EVIDENCE: "evd",
    NodeType.SOURCE: "src",
    NodeType.OBSERVATION: "obs",
    NodeType.MEMORY_MUTATION: "mut",
}

# Labels and relationship types are selected only through these server-owned
# enum maps. Client values are always query parameters.
_CREATE_NODE_QUERIES = {
    node_type: f"CREATE (n:{node_type.value}) SET n = $properties RETURN n.id AS id"
    for node_type in NodeType
    if node_type not in {NodeType.USER, NodeType.PROFILE, NodeType.MEMORY_MUTATION}
}
_ADD_EDGE_QUERIES = {
    relation: (
        "MATCH (source {subject_id: $subject_id, id: $source_id}) "
        "MATCH (target {subject_id: $subject_id, id: $target_id}) "
        f"MERGE (source)-[edge:{relation.value}]->(target) "
        "ON CREATE SET edge.created_at = $now "
        "SET edge.updated_at = $now "
        "RETURN count(edge) AS count"
    )
    for relation in RelationType
}
_REMOVE_EDGE_QUERIES = {
    relation: (
        "MATCH (source {subject_id: $subject_id, id: $source_id})"
        f"-[edge:{relation.value}]->"
        "(target {subject_id: $subject_id, id: $target_id}) "
        "DELETE edge RETURN count(edge) AS count"
    )
    for relation in RelationType
}

_SCHEMA_QUERIES = (
    "CREATE CONSTRAINT user_subject_unique IF NOT EXISTS FOR (n:User) REQUIRE n.subject_id IS UNIQUE",
    "CREATE CONSTRAINT profile_subject_unique IF NOT EXISTS FOR (n:Profile) REQUIRE n.subject_id IS UNIQUE",
    "CREATE CONSTRAINT space_key_unique IF NOT EXISTS FOR (n:MemorySpace) REQUIRE (n.subject_id, n.space_key) IS UNIQUE",
    "CREATE CONSTRAINT claim_id_unique IF NOT EXISTS FOR (n:Claim) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT concept_id_unique IF NOT EXISTS FOR (n:Concept) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT context_id_unique IF NOT EXISTS FOR (n:Context) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT preference_rule_id_unique IF NOT EXISTS FOR (n:PreferenceRule) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT evidence_id_unique IF NOT EXISTS FOR (n:Evidence) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT source_id_unique IF NOT EXISTS FOR (n:Source) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT observation_id_unique IF NOT EXISTS FOR (n:Observation) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT mutation_id_unique IF NOT EXISTS FOR (n:MemoryMutation) REQUIRE n.id IS UNIQUE",
    (
        "CREATE CONSTRAINT mutation_idempotency_unique IF NOT EXISTS "
        "FOR (n:MemoryMutation) REQUIRE (n.subject_id, n.idempotency_key) IS UNIQUE"
    ),
    "CREATE INDEX claim_lookup IF NOT EXISTS FOR (n:Claim) ON (n.subject_id, n.status, n.claim_kind)",
    "CREATE INDEX claim_canonical_key IF NOT EXISTS FOR (n:Claim) ON (n.subject_id, n.canonical_key)",
    "CREATE INDEX concept_key IF NOT EXISTS FOR (n:Concept) ON (n.subject_id, n.canonical_key)",
    "CREATE INDEX observation_expiry IF NOT EXISTS FOR (n:Observation) ON (n.expires_at)",
    "CREATE INDEX mutation_expiry IF NOT EXISTS FOR (n:MemoryMutation) ON (n.expires_at)",
    (
        "CREATE FULLTEXT INDEX memory_space_search IF NOT EXISTS "
        "FOR (n:MemorySpace) ON EACH [n.name, n.summary, n.search_text]"
    ),
    (
        "CREATE FULLTEXT INDEX memory_candidate_search IF NOT EXISTS "
        "FOR (n:Claim|PreferenceRule|Context|Concept) "
        "ON EACH [n.statement, n.summary, n.name, n.search_text, n.canonical_key]"
    ),
)

_PROFILE_SUMMARY_QUERY = """
OPTIONAL MATCH (profile:Profile {subject_id: $subject_id})
OPTIONAL MATCH (profile)-[:CONTAINS_CLAIM]->(claim:Claim)
OPTIONAL MATCH (claim)-[:BELONGS_TO]->(space:MemorySpace)
WITH profile, collect(DISTINCT claim) AS claims, collect(DISTINCT space) AS spaces
OPTIONAL MATCH (conflict_a:Claim {subject_id: $subject_id})-[:CONFLICTS_WITH]-(conflict_b:Claim)
WHERE conflict_a.status = 'active' AND conflict_b.status = 'active' AND conflict_a.id < conflict_b.id
RETURN coalesce(profile.revision, 0) AS profile_revision,
       [space IN spaces WHERE space IS NOT NULL |
          {id: space.id, space_key: space.space_key, name: space.name, summary: space.summary}] AS spaces,
       size([claim IN claims WHERE claim.status = 'active']) AS active_claim_count,
       [claim IN claims WHERE claim.status = 'active' AND claim.claim_kind = 'purchase_intent' |
          {id: claim.id, statement: claim.statement, confidence: claim.confidence}][..10]
          AS active_purchase_intent,
       count(DISTINCT conflict_a) AS unresolved_conflicts,
       [claim IN claims WHERE claim.status = 'active' |
          {id: claim.id, statement: claim.statement, claim_kind: claim.claim_kind,
           confidence: claim.confidence, updated_at: claim.updated_at}][..20] AS major_claims
"""

_ROUTE_SPACE_FULLTEXT_QUERY = """
CALL db.index.fulltext.queryNodes('memory_space_search', $fulltext_query, {limit: $fetch_limit})
YIELD node, score
WHERE node.subject_id = $subject_id
RETURN node.id AS id, node.space_key AS space_key, node.name AS name,
       node.summary AS summary, score
ORDER BY score DESC, node.id
LIMIT $fetch_limit
"""
_ROUTE_SPACE_FILTER_QUERY = """
MATCH (node:MemorySpace {subject_id: $subject_id})
WHERE any(token IN $tokens WHERE
  toLower(coalesce(node.name, '')) CONTAINS token OR
  toLower(coalesce(node.summary, '')) CONTAINS token OR
  any(keyword IN coalesce(node.keywords, []) WHERE toLower(keyword) CONTAINS token))
RETURN node.id AS id, node.space_key AS space_key, node.name AS name,
       node.summary AS summary,
       size([token IN $tokens WHERE
         toLower(coalesce(node.name, '')) CONTAINS token OR
         toLower(coalesce(node.summary, '')) CONTAINS token]) AS score
ORDER BY score DESC, node.id
LIMIT $fetch_limit
"""

_CANDIDATE_FULLTEXT_QUERY = """
CALL db.index.fulltext.queryNodes('memory_candidate_search', $fulltext_query, {limit: $fetch_limit})
YIELD node, score
WHERE node.subject_id = $subject_id
  AND any(label IN labels(node) WHERE label IN $node_types)
  AND coalesce(node.status, 'active') IN $statuses
OPTIONAL MATCH (node)-[:BELONGS_TO]->(space:MemorySpace {subject_id: $subject_id})
WITH node, score, collect(DISTINCT space.id) AS spaces
WHERE size($space_ids) = 0 OR any(space_id IN spaces WHERE space_id IN $space_ids) OR score >= 2.0
RETURN node.id AS id, head(labels(node)) AS node_type, properties(node) AS properties,
       spaces, score
ORDER BY score DESC, node.id
LIMIT $fetch_limit
"""
_CANDIDATE_EXACT_QUERY = """
MATCH (node)
WHERE node.subject_id = $subject_id
  AND any(label IN labels(node) WHERE label IN $node_types)
  AND coalesce(node.status, 'active') IN $statuses
  AND (
    toLower(coalesce(node.statement, '')) = $normalized_query OR
    toLower(coalesce(node.name, '')) = $normalized_query OR
    toLower(coalesce(node.canonical_key, '')) = $normalized_query
  )
OPTIONAL MATCH (node)-[:BELONGS_TO]->(space:MemorySpace {subject_id: $subject_id})
WITH node, collect(DISTINCT space.id) AS spaces
RETURN node.id AS id, head(labels(node)) AS node_type, properties(node) AS properties,
       spaces, 1.0 AS score
ORDER BY node.id
LIMIT $fetch_limit
"""
_CANDIDATE_PROXIMITY_QUERY = f"""
MATCH (intent:Claim {{subject_id: $subject_id, claim_kind: 'purchase_intent', status: 'active'}})
MATCH path=(intent)-[:{_GRAPH_RELATIONS}*1..2]-(node)
WHERE node.subject_id = $subject_id
  AND any(label IN labels(node) WHERE label IN $node_types)
  AND coalesce(node.status, 'active') IN $statuses
OPTIONAL MATCH (node)-[:BELONGS_TO]->(space:MemorySpace {{subject_id: $subject_id}})
WITH node, min(length(path)) AS distance, collect(DISTINCT space.id) AS spaces
WHERE size($space_ids) = 0 OR any(space_id IN spaces WHERE space_id IN $space_ids)
RETURN node.id AS id, head(labels(node)) AS node_type, properties(node) AS properties,
       spaces, 1.0 / (1.0 + distance) AS score
ORDER BY distance, node.id
LIMIT $fetch_limit
"""

_ROOTS_BY_SPACE_QUERY = """
MATCH (node)-[:BELONGS_TO]->(space:MemorySpace {subject_id: $subject_id})
WHERE space.id IN $space_ids AND node.subject_id = $subject_id
  AND coalesce(node.status, 'active') IN $statuses
RETURN DISTINCT node.id AS id
ORDER BY id
LIMIT $limit
"""

_NEIGHBORHOOD_NODES_QUERY = f"""
MATCH (root)
WHERE root.subject_id = $subject_id AND root.id IN $root_ids
MATCH path=(root)-[:{_GRAPH_RELATIONS}*0..3]-(node)
WHERE length(path) <= $max_depth
  AND all(item IN nodes(path) WHERE item.subject_id = $subject_id)
  AND all(edge IN relationships(path) WHERE type(edge) IN $relations)
UNWIND nodes(path) AS result
WITH DISTINCT result
ORDER BY result.id
LIMIT $max_nodes
RETURN result.id AS id, head(labels(result)) AS node_type, properties(result) AS properties
"""
_NEIGHBORHOOD_EDGES_QUERY = f"""
MATCH (root)
WHERE root.subject_id = $subject_id AND root.id IN $root_ids
MATCH path=(root)-[:{_GRAPH_RELATIONS}*1..3]-(node)
WHERE length(path) <= $max_depth
  AND all(item IN nodes(path) WHERE item.subject_id = $subject_id)
  AND all(edge IN relationships(path) WHERE type(edge) IN $relations)
UNWIND relationships(path) AS edge
WITH DISTINCT startNode(edge).id AS source, type(edge) AS relation, endNode(edge).id AS target
ORDER BY source, relation, target
LIMIT $max_edges
RETURN source, relation, target
"""
_EVIDENCE_SUMMARY_QUERY = """
UNWIND $node_ids AS node_id
MATCH (node {subject_id: $subject_id, id: node_id})
OPTIONAL MATCH (node)-[:SUPPORTED_BY]->(support:Evidence {subject_id: $subject_id})
OPTIONAL MATCH (node)-[:CONTRADICTED_BY]->(contradiction:Evidence {subject_id: $subject_id})
RETURN node_id, count(DISTINCT support) AS supporting_count,
       count(DISTINCT contradiction) AS contradicting_count
"""

_SUBJECT_NODES_QUERY = """
MATCH (node)
WHERE node.subject_id = $subject_id AND NOT node:MemoryMutation
RETURN node.id AS id, head(labels(node)) AS node_type, properties(node) AS properties
"""
_SUBJECT_EDGES_QUERY = """
MATCH (source)-[edge]->(target)
WHERE source.subject_id = $subject_id AND target.subject_id = $subject_id
RETURN source.id AS source, type(edge) AS relation, target.id AS target
"""

_BOOTSTRAP_PROFILE_QUERY = """
MERGE (user:User {subject_id: $subject_id})
ON CREATE SET user.id = $user_id, user.schema_version = $schema_version,
              user.status = 'active', user.revision = 0,
              user.created_at = $now, user.updated_at = $now
MERGE (profile:Profile {subject_id: $subject_id})
ON CREATE SET profile.id = $profile_id, profile.schema_version = $schema_version,
              profile.status = 'active', profile.revision = 0,
              profile.created_at = $now, profile.updated_at = $now
MERGE (user)-[:HAS_PROFILE]->(profile)
RETURN profile.id AS id, profile.revision AS revision
"""
_RETIRE_NODES_QUERY = """
MATCH (node)
WHERE node.subject_id = $subject_id AND node.id IN $ids
  AND NOT node:User AND NOT node:Profile AND NOT node:MemoryMutation
  AND NOT node:Evidence AND NOT node:Source
SET node.status = 'retired', node.updated_at = $now,
    node.revision = coalesce(node.revision, 0) + 1
RETURN count(node) AS count
"""
_DELETE_NODES_QUERY = """
MATCH (node)
WHERE node.subject_id = $subject_id AND node.id IN $ids
  AND NOT node:User AND NOT node:Profile AND NOT node:MemoryMutation
  AND NOT node:Evidence AND NOT node:Source
WITH collect(node) AS nodes
FOREACH (node IN nodes | DETACH DELETE node)
RETURN size(nodes) AS count
"""
_RETIRE_SOURCES_QUERY = """
MATCH (source:Source)
WHERE source.subject_id = $subject_id AND source.id IN $ids
OPTIONAL MATCH (evidence:Evidence {subject_id: $subject_id})-[:HAS_SOURCE]->(source)
WITH collect(DISTINCT source) + collect(DISTINCT evidence) AS nodes
FOREACH (node IN nodes |
  SET node.status = 'retired', node.updated_at = $now,
      node.revision = coalesce(node.revision, 0) + 1)
RETURN size(nodes) AS count
"""
_SOURCE_DEPENDENCY_QUERY = """
MATCH (target {subject_id: $subject_id})
WHERE target.status = 'active' AND (target:Claim OR target:PreferenceRule)
MATCH (target)-[:SUPPORTED_BY|CONTRADICTED_BY]->(evidence:Evidence)
      -[:HAS_SOURCE]->(source:Source)
WHERE source.subject_id = $subject_id AND source.id IN $ids
WITH DISTINCT target
OPTIONAL MATCH (target)-[:SUPPORTED_BY|CONTRADICTED_BY]->(remaining:Evidence)
      -[:HAS_SOURCE]->(other:Source)
WHERE remaining.subject_id = $subject_id
  AND other.subject_id = $subject_id
  AND NOT other.id IN $ids
  AND NOT coalesce(remaining.status, 'active') IN ['retired', 'deleted']
WITH target, count(DISTINCT remaining) AS remaining_count
WHERE remaining_count = 0
RETURN target.id AS id
ORDER BY id
LIMIT 20
"""
_DELETE_SOURCES_QUERY = """
MATCH (source:Source)
WHERE source.subject_id = $subject_id AND source.id IN $ids
OPTIONAL MATCH (evidence:Evidence {subject_id: $subject_id})-[:HAS_SOURCE]->(source)
WITH collect(DISTINCT source) + collect(DISTINCT evidence) AS nodes
FOREACH (node IN nodes | DETACH DELETE node)
RETURN size(nodes) AS count
"""


class Neo4jPreferenceGraphRepository(PreferenceGraphRepository):
    """Subject-scoped Neo4j persistence for the fixed preference ontology."""

    def __init__(
        self,
        *,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        mutation_ttl_seconds: int = 3600,
        observation_ttl_seconds: int = 86400,
        driver: AsyncDriver | None = None,
    ) -> None:
        if mutation_ttl_seconds <= 0 or observation_ttl_seconds <= 0:
            raise ValueError("Memory TTL values must be positive.")
        self._database = database
        self._mutation_ttl_seconds = mutation_ttl_seconds
        self._observation_ttl_seconds = observation_ttl_seconds
        self._driver = driver or AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def initialize(self) -> None:
        await self._driver.verify_connectivity()
        for query in _SCHEMA_QUERIES:
            await self._execute(query)

    async def close(self) -> None:
        await self._driver.close()

    async def get_profile_summary(self, subject_id: str) -> dict[str, Any]:
        record = await self._single(_PROFILE_SUMMARY_QUERY, subject_id=subject_id)
        if record is None:
            return {
                "profile_revision": 0,
                "spaces": [],
                "active_claim_count": 0,
                "active_purchase_intent": [],
                "unresolved_conflicts": 0,
                "recent_changes": [],
                "major_claims": [],
            }
        result = dict(record)
        result["recent_changes"] = sorted(
            result.get("major_claims", []),
            key=lambda item: str(item.get("updated_at") or ""),
            reverse=True,
        )[:10]
        return _jsonable(result)

    async def route_spaces(self, subject_id: str, query: str, limit: int) -> dict[str, Any]:
        limit = _bounded(limit, maximum=50, name="limit")
        fetch_limit = min(max(limit * 4, limit), 100)
        tokens = _query_tokens(query)
        parameters = {
            "subject_id": subject_id,
            "fulltext_query": _fulltext_query(tokens),
            "tokens": tokens,
            "fetch_limit": fetch_limit,
        }
        fulltext = await self._records(_ROUTE_SPACE_FULLTEXT_QUERY, **parameters)
        filtered = await self._records(_ROUTE_SPACE_FILTER_QUERY, **parameters)
        by_id = {item["id"]: item for item in [*fulltext, *filtered]}
        fused = reciprocal_rank_fusion(
            {
                "full_text": [item["id"] for item in fulltext],
                "filter": [item["id"] for item in filtered],
            }
        )
        spaces = []
        for item_id, final_score in fused[:limit]:
            item = by_id[item_id]
            fulltext_score = _score_for(fulltext, item_id)
            filter_score = _score_for(filtered, item_id)
            matched_by = []
            if fulltext_score:
                matched_by.append("full_text")
            if filter_score:
                matched_by.append("keyword")
            spaces.append(
                {
                    "space_id": item_id,
                    "space_key": item.get("space_key"),
                    "name": item.get("name"),
                    "summary": item.get("summary"),
                    "scores": {
                        "full_text": fulltext_score,
                        "vector": 0.0,
                        "concept": filter_score,
                        "final": final_score,
                    },
                    "matched_by": matched_by,
                }
            )
        profile_revision = await self._profile_revision(subject_id)
        return {
            "schema_version": SCHEMA_VERSION,
            "profile_revision": profile_revision,
            "spaces": spaces,
            "retrieval": {
                "method": "full_text_filter_rrf",
                "candidate_count_before_limit": len(fused),
                "truncated": len(fused) > limit,
            },
        }

    async def search_candidates(self, subject_id: str, request: dict[str, Any]) -> dict[str, Any]:
        limit = _bounded(int(request.get("limit", 20)), maximum=100, name="limit")
        fetch_limit = min(max(limit * 4, limit), 200)
        query = str(request["query"])
        tokens = _query_tokens(query)
        parameters = {
            "subject_id": subject_id,
            "fulltext_query": _fulltext_query(tokens),
            "normalized_query": normalize_text(query),
            "node_types": [str(item) for item in request.get("node_types") or [
                NodeType.CLAIM.value,
                NodeType.PREFERENCE_RULE.value,
                NodeType.CONTEXT.value,
            ]],
            "statuses": [str(item) for item in request.get("status") or [NodeStatus.ACTIVE.value]],
            "space_ids": list(request.get("space_ids") or []),
            "fetch_limit": fetch_limit,
        }
        exact = await self._records(_CANDIDATE_EXACT_QUERY, **parameters)
        fulltext = await self._records(_CANDIDATE_FULLTEXT_QUERY, **parameters)
        proximity = await self._records(_CANDIDATE_PROXIMITY_QUERY, **parameters)
        by_id = {item["id"]: item for item in [*proximity, *fulltext, *exact]}
        fused = reciprocal_rank_fusion(
            {
                "exact": [item["id"] for item in exact],
                "full_text": [item["id"] for item in fulltext],
                "graph_proximity": [item["id"] for item in proximity],
            },
            weights={"exact": 2.0, "full_text": 1.0, "graph_proximity": 0.75},
        )
        candidates = []
        for item_id, final_score in fused[:limit]:
            item = by_id[item_id]
            properties = _public_properties(item.get("properties") or {})
            exact_score = _score_for(exact, item_id)
            fulltext_score = _score_for(fulltext, item_id)
            proximity_score = _score_for(proximity, item_id)
            matched_by = [
                name
                for name, score in (
                    ("exact", exact_score),
                    ("full_text", fulltext_score),
                    ("graph_proximity", proximity_score),
                )
                if score
            ]
            candidates.append(
                {
                    "node_id": item_id,
                    "node_type": item.get("node_type"),
                    **properties,
                    "spaces": item.get("spaces") or [],
                    "scores": {
                        "exact": exact_score,
                        "full_text": fulltext_score,
                        "vector": 0.0,
                        "graph_proximity": proximity_score,
                        "final": final_score,
                    },
                    "matched_by": matched_by,
                    "recommended_role": (
                        "possible_existing_equivalent" if exact_score else "possible_update_target"
                    ),
                }
            )
        return {
            "profile_revision": await self._profile_revision(subject_id),
            "candidates": _jsonable(candidates),
            "retrieval": {
                "candidate_count_before_limit": len(fused),
                "returned_count": len(candidates),
                "truncated": len(fused) > limit,
                "method": "exact_full_text_graph_rrf",
            },
        }

    async def get_neighborhood(self, subject_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return await self._get_neighborhood(subject_id, request)

    async def get_graph(self, subject_id: str, request: dict[str, Any]) -> dict[str, Any]:
        root_ids = list(request.get("root_node_ids") or [])
        if not root_ids:
            space_ids = list(request.get("space_ids") or [])
            if not space_ids:
                raise MemoryError(
                    MemoryErrorKind.VALIDATION_ERROR,
                    "A bounded graph read requires root_node_ids or space_ids.",
                )
            root_records = await self._records(
                _ROOTS_BY_SPACE_QUERY,
                subject_id=subject_id,
                space_ids=space_ids,
                statuses=[str(item) for item in request.get("status") or [NodeStatus.ACTIVE.value]],
                limit=min(int(request.get("max_nodes", 50)), 100),
            )
            root_ids = [item["id"] for item in root_records]
        bounded_request = {**request, "root_node_ids": root_ids}
        return await self._get_neighborhood(subject_id, bounded_request)

    async def preview_mutation(self, subject_id: str, request: dict[str, Any]) -> dict[str, Any]:
        request_digest = memory_preview_hash(request)
        async with self._driver.session(database=self._database) as session:
            return await session.execute_write(
                self._preview_transaction,
                subject_id,
                request,
                request_digest,
            )

    async def apply_mutation(
        self,
        subject_id: str,
        mutation_id: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        async with self._driver.session(database=self._database) as session:
            return await session.execute_write(
                self._apply_transaction,
                subject_id,
                mutation_id,
                preview_hash,
            )

    async def export_graph(self, subject_id: str, request: dict[str, Any]) -> dict[str, Any]:
        limit = _bounded(int(request.get("limit", 100)), maximum=100, name="limit")
        cursor = request.get("cursor")
        statuses = [str(item) for item in request.get("status") or [
            NodeStatus.ACTIVE.value,
            NodeStatus.RETIRED.value,
            NodeStatus.SUPERSEDED.value,
        ]]
        nodes = await self._records(
            """
            MATCH (node)
            WHERE node.subject_id = $subject_id AND NOT node:MemoryMutation
              AND ($cursor IS NULL OR node.id > $cursor)
              AND (node:User OR node:Profile OR coalesce(node.status, 'active') IN $statuses)
            RETURN node.id AS id, head(labels(node)) AS node_type, properties(node) AS properties
            ORDER BY node.id LIMIT $fetch_limit
            """,
            subject_id=subject_id,
            cursor=cursor,
            statuses=statuses,
            fetch_limit=limit + 1,
        )
        page, has_more = nodes[:limit], len(nodes) > limit
        node_ids = [item["id"] for item in page]
        edges = await self._records(
            """
            MATCH (source)-[edge]->(target)
            WHERE source.subject_id = $subject_id AND target.subject_id = $subject_id
              AND source.id IN $node_ids
            RETURN source.id AS source, type(edge) AS relation, target.id AS target
            ORDER BY source, relation, target
            LIMIT 250
            """,
            subject_id=subject_id,
            node_ids=node_ids,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "profile_revision": await self._profile_revision(subject_id),
            "nodes": [
                {
                    "id": item["id"],
                    "type": item["node_type"],
                    **_public_properties(item["properties"]),
                }
                for item in page
            ],
            "edges": edges,
            "next_cursor": page[-1]["id"] if has_more and page else None,
            "truncated": has_more,
        }

    async def delete_graph(self, subject_id: str, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("confirmation") is not True:
            raise MemoryError(
                MemoryErrorKind.CONFIRMATION_REQUIRED,
                "Explicit confirmation is required.",
            )
        async with self._driver.session(database=self._database) as session:
            return await session.execute_write(self._delete_transaction, subject_id, request)

    async def cleanup_expired(self) -> dict[str, int]:
        now = datetime.now(UTC)
        mutation_purge_before = now - timedelta(seconds=self._mutation_ttl_seconds)
        observation = await self._single(
            """
            MATCH (node:Observation)
            WHERE node.expires_at <= $now
            WITH collect(node) AS expired
            FOREACH (node IN expired | DETACH DELETE node)
            RETURN size(expired) AS count
            """,
            now=now,
        )
        mutation = await self._single(
            """
            MATCH (node:MemoryMutation {status: 'pending'})
            WHERE node.expires_at <= $now
            SET node.status = 'expired', node.updated_at = $now
            RETURN count(node) AS count
            """,
            now=now,
        )
        purged = await self._single(
            """
            MATCH (node:MemoryMutation {status: 'expired'})
            WHERE node.expires_at <= $purge_before
            WITH collect(node) AS expired
            FOREACH (node IN expired | DETACH DELETE node)
            RETURN size(expired) AS count
            """,
            purge_before=mutation_purge_before,
        )
        return {
            "observations_deleted": int((observation or {}).get("count", 0)),
            "mutations_expired": int((mutation or {}).get("count", 0)),
            "mutations_deleted": int((purged or {}).get("count", 0)),
        }

    async def _get_neighborhood(self, subject_id: str, request: dict[str, Any]) -> dict[str, Any]:
        root_ids = list(request.get("root_node_ids") or [])
        if not root_ids:
            raise MemoryError(MemoryErrorKind.VALIDATION_ERROR, "root_node_ids is required.")
        max_depth = _bounded(int(request.get("max_depth", 2)), maximum=3, name="max_depth")
        max_nodes = _bounded(int(request.get("max_nodes", 50)), maximum=100, name="max_nodes")
        max_edges = _bounded(int(request.get("max_edges", 100)), maximum=250, name="max_edges")
        relations = [str(item) for item in request.get("relations") or list(RelationType)]
        allowed = {item.value for item in RelationType}
        if not set(relations) <= allowed:
            raise MemoryError(
                MemoryErrorKind.RELATION_NOT_ALLOWED,
                "A requested relation is not defined by the active schema.",
                allowed_relations=sorted(allowed),
            )
        parameters = {
            "subject_id": subject_id,
            "root_ids": root_ids[:30],
            "max_depth": max_depth,
            "max_nodes": max_nodes + 1,
            "max_edges": max_edges + 1,
            "relations": relations,
        }

        async def read(tx: AsyncManagedTransaction) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
            profile = await _tx_single(
                tx,
                "OPTIONAL MATCH (p:Profile {subject_id: $subject_id}) "
                "RETURN coalesce(p.revision, 0) AS revision",
                subject_id=subject_id,
            )
            nodes = await _tx_records(tx, _NEIGHBORHOOD_NODES_QUERY, **parameters)
            edges = await _tx_records(tx, _NEIGHBORHOOD_EDGES_QUERY, **parameters)
            return int((profile or {}).get("revision", 0)), nodes, edges

        async with self._driver.session(database=self._database) as session:
            revision, nodes, edges = await session.execute_read(read)
        nodes_truncated, edges_truncated = len(nodes) > max_nodes, len(edges) > max_edges
        nodes, edges = nodes[:max_nodes], edges[:max_edges]
        node_ids = [item["id"] for item in nodes]
        evidence_summary: dict[str, Any] = {}
        if request.get("include_evidence_summary", True) and node_ids:
            summaries = await self._records(
                _EVIDENCE_SUMMARY_QUERY,
                subject_id=subject_id,
                node_ids=node_ids,
            )
            evidence_summary = {
                item["node_id"]: {
                    "supporting_count": item["supporting_count"],
                    "contradicting_count": item["contradicting_count"],
                }
                for item in summaries
                if item["supporting_count"] or item["contradicting_count"]
            }
        snapshot_material = {
            "subject_id": subject_id,
            "profile_revision": revision,
            "root_node_ids": sorted(root_ids),
            "relations": sorted(relations),
            "max_depth": max_depth,
        }
        snapshot_hash = memory_preview_hash(snapshot_material).removeprefix("sha256:")[:16]
        return {
            "snapshot_id": f"snap_{revision}_{snapshot_hash}",
            "profile_revision": revision,
            "is_local_graph": True,
            "nodes": [
                {
                    "id": item["id"],
                    "type": item["node_type"],
                    **_public_properties(item["properties"]),
                }
                for item in nodes
            ],
            "edges": [
                {"from": item["source"], "relation": item["relation"], "to": item["target"]}
                for item in edges
            ],
            "evidence_summary": evidence_summary,
            "retrieval": {
                "max_depth": max_depth,
                "truncated": nodes_truncated or edges_truncated,
            },
        }

    async def _preview_transaction(
        self,
        tx: AsyncManagedTransaction,
        subject_id: str,
        request: dict[str, Any],
        request_digest: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        profile = await _tx_single(
            tx,
            "OPTIONAL MATCH (profile:Profile {subject_id: $subject_id}) "
            "RETURN profile.id AS id, coalesce(profile.revision, 0) AS revision",
            subject_id=subject_id,
        )
        assert profile is not None
        current_revision = int(profile["revision"])
        base_revision = int(request.get("base_revision", -1))
        if base_revision != current_revision:
            raise MemoryError(
                MemoryErrorKind.REVISION_CONFLICT,
                "Profile revision changed; route and preview again.",
                expected_revision=base_revision,
                current_revision=current_revision,
                retryable=True,
            )
        snapshot_id = str(request.get("context_snapshot_id") or "")
        if not snapshot_id.startswith(f"snap_{current_revision}_"):
            raise MemoryError(
                MemoryErrorKind.SNAPSHOT_STALE,
                "The context snapshot is stale.",
                current_revision=current_revision,
                retryable=True,
            )
        idempotency_key = str(request["idempotency_key"])
        existing = await _tx_single(
            tx,
            """
            MATCH (mutation:MemoryMutation {subject_id: $subject_id, idempotency_key: $idempotency_key})
            RETURN properties(mutation) AS mutation
            """,
            subject_id=subject_id,
            idempotency_key=idempotency_key,
        )
        if existing:
            mutation = existing["mutation"]
            if mutation.get("request_digest") != request_digest:
                raise MemoryError(
                    MemoryErrorKind.DUPLICATE_DETECTED,
                    "The idempotency key was already used for a different request.",
                )
            return _preview_result(mutation)

        graph_nodes = await _tx_records(tx, _SUBJECT_NODES_QUERY, subject_id=subject_id)
        graph_edges = await _tx_records(tx, _SUBJECT_EDGES_QUERY, subject_id=subject_id)
        patch, preview_operations, affected_nodes = _normalize_and_preflight(
            subject_id,
            request,
            graph_nodes,
            graph_edges,
            observation_ttl_seconds=self._observation_ttl_seconds,
        )
        preview_hash = memory_preview_hash(
            {
                "schema_version": SCHEMA_VERSION,
                "base_revision": current_revision,
                "context_snapshot_id": snapshot_id,
                "patch": patch,
            }
        )
        mutation_id = _new_id(NodeType.MEMORY_MUTATION)
        expires_at = now + timedelta(seconds=self._mutation_ttl_seconds)
        result = {
            "status": "ready_for_confirmation",
            "mutation_id": mutation_id,
            "preview_hash": preview_hash,
            "expires_at": expires_at.isoformat(),
            "resolution": {"action": "apply_normalized_operations"},
            "normalized_operations": preview_operations,
            "duplicates": [],
            "conflicts": [],
            "affected_nodes": sorted(affected_nodes),
            "requires_confirmation": True,
        }
        await _tx_consume(
            tx,
            """
            CREATE (mutation:MemoryMutation {
              id: $mutation_id, subject_id: $subject_id, schema_version: $schema_version,
              base_revision: $base_revision, context_snapshot_id: $context_snapshot_id,
              idempotency_key: $idempotency_key, request_digest: $request_digest,
              normalized_patch_json: $patch_json, preview_result_json: $preview_result_json,
              preview_hash: $preview_hash, status: 'pending',
              created_at: $now, updated_at: $now, expires_at: $expires_at
            })
            """,
            mutation_id=mutation_id,
            subject_id=subject_id,
            schema_version=SCHEMA_VERSION,
            base_revision=current_revision,
            context_snapshot_id=snapshot_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            patch_json=canonical_json(patch),
            preview_result_json=canonical_json(result),
            preview_hash=preview_hash,
            now=now,
            expires_at=expires_at,
        )
        return result

    async def _apply_transaction(
        self,
        tx: AsyncManagedTransaction,
        subject_id: str,
        mutation_id: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        row = await _tx_single(
            tx,
            """
            MATCH (mutation:MemoryMutation {subject_id: $subject_id, id: $mutation_id})
            RETURN properties(mutation) AS mutation
            """,
            subject_id=subject_id,
            mutation_id=mutation_id,
        )
        if row is None:
            raise MemoryError(MemoryErrorKind.NOT_FOUND, "Memory mutation was not found.")
        mutation = row["mutation"]
        if mutation.get("preview_hash") != preview_hash:
            raise MemoryError(
                MemoryErrorKind.PREVIEW_HASH_MISMATCH,
                "The preview hash does not match the stored mutation.",
            )
        if mutation.get("status") == "applied":
            return json.loads(mutation["apply_result_json"])
        if mutation.get("status") == "expired" or _as_datetime(mutation["expires_at"]) <= now:
            raise MemoryError(MemoryErrorKind.MUTATION_EXPIRED, "The memory mutation has expired.")
        if mutation.get("status") != "pending":
            raise MemoryError(MemoryErrorKind.VALIDATION_ERROR, "The mutation is not pending.")

        await _tx_single(
            tx,
            _BOOTSTRAP_PROFILE_QUERY,
            subject_id=subject_id,
            user_id=_new_id(NodeType.USER),
            profile_id=_new_id(NodeType.PROFILE),
            schema_version=SCHEMA_VERSION,
            now=now,
        )
        # Updating a server-owned lock counter serializes concurrent pending
        # applies before the revision and mutation state are re-read.
        profile = await _tx_single(
            tx,
            """
            MATCH (profile:Profile {subject_id: $subject_id})
            SET profile.apply_lock = coalesce(profile.apply_lock, 0) + 1
            RETURN profile.id AS id, profile.revision AS revision
            """,
            subject_id=subject_id,
        )
        assert profile is not None
        row = await _tx_single(
            tx,
            """
            MATCH (mutation:MemoryMutation {subject_id: $subject_id, id: $mutation_id})
            RETURN properties(mutation) AS mutation
            """,
            subject_id=subject_id,
            mutation_id=mutation_id,
        )
        assert row is not None
        mutation = row["mutation"]
        if mutation.get("status") == "applied":
            return json.loads(mutation["apply_result_json"])
        current_revision = int(profile["revision"])
        if int(mutation["base_revision"]) != current_revision:
            raise MemoryError(
                MemoryErrorKind.REVISION_CONFLICT,
                "Profile revision changed; create a new preview.",
                expected_revision=mutation["base_revision"],
                current_revision=current_revision,
                retryable=True,
            )

        patch = json.loads(mutation["normalized_patch_json"])
        created_ids, updated_ids = await _apply_patch(
            tx,
            subject_id=subject_id,
            profile_id=profile["id"],
            operations=patch["operations"],
            now=now,
        )
        new_revision = current_revision + 1
        result = {
            "status": "applied",
            "previous_revision": current_revision,
            "new_revision": new_revision,
            "created_node_ids": created_ids,
            "updated_node_ids": sorted(updated_ids),
        }
        await _tx_consume(
            tx,
            """
            MATCH (profile:Profile {subject_id: $subject_id})
            MATCH (mutation:MemoryMutation {subject_id: $subject_id, id: $mutation_id})
            SET profile.revision = $new_revision, profile.updated_at = $now,
                mutation.status = 'applied', mutation.updated_at = $now,
                mutation.apply_result_json = $result_json
            """,
            subject_id=subject_id,
            mutation_id=mutation_id,
            new_revision=new_revision,
            now=now,
            result_json=canonical_json(result),
        )
        return result

    async def _delete_transaction(
        self,
        tx: AsyncManagedTransaction,
        subject_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        scope = request.get("scope")
        mode = request.get("mode", "retire")
        now = datetime.now(UTC)
        idempotency_key = str(request.get("idempotency_key") or "")
        if not idempotency_key:
            raise MemoryError(
                MemoryErrorKind.VALIDATION_ERROR,
                "Delete requires an idempotency key.",
            )
        request_digest = memory_preview_hash(request)
        existing = await _tx_single(
            tx,
            """
            MATCH (mutation:MemoryMutation {
              subject_id: $subject_id, idempotency_key: $idempotency_key
            })
            RETURN properties(mutation) AS mutation
            """,
            subject_id=subject_id,
            idempotency_key=idempotency_key,
        )
        if existing:
            mutation = existing["mutation"]
            if mutation.get("request_digest") != request_digest:
                raise MemoryError(
                    MemoryErrorKind.DUPLICATE_DETECTED,
                    "The idempotency key was already used for a different request.",
                )
            if mutation.get("status") == "applied" and mutation.get("mutation_kind") == "delete":
                return json.loads(mutation["apply_result_json"])
            raise MemoryError(
                MemoryErrorKind.DUPLICATE_DETECTED,
                "The idempotency key is already in use.",
            )
        if scope == "all":
            result = await _tx_single(
                tx,
                """
                MATCH (node {subject_id: $subject_id})
                WITH collect(node) AS nodes
                FOREACH (node IN nodes | DETACH DELETE node)
                RETURN size(nodes) AS count
                """,
                subject_id=subject_id,
            )
            response = {
                "status": "deleted",
                "scope": "all",
                "affected_count": int(result["count"]),
            }
            await _store_delete_result(
                tx,
                subject_id=subject_id,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                result=response,
                now=now,
            )
            return response
        ids = list(request.get("node_ids") or request.get("source_ids") or [])
        if not ids:
            raise MemoryError(MemoryErrorKind.VALIDATION_ERROR, "The delete scope requires IDs.")
        if scope == "source":
            dependents = await _tx_records(
                tx,
                _SOURCE_DEPENDENCY_QUERY,
                subject_id=subject_id,
                ids=ids,
            )
            if dependents:
                raise MemoryError(
                    MemoryErrorKind.VALIDATION_ERROR,
                    "Deleting this Source would leave an active Claim or PreferenceRule without Evidence.",
                    dependent_node_ids=[item["id"] for item in dependents],
                )
        queries = {
            ("nodes", "retire"): _RETIRE_NODES_QUERY,
            ("nodes", "delete"): _DELETE_NODES_QUERY,
            ("source", "retire"): _RETIRE_SOURCES_QUERY,
            ("source", "delete"): _DELETE_SOURCES_QUERY,
        }
        query = queries.get((str(scope), str(mode)))
        if query is None:
            raise MemoryError(MemoryErrorKind.VALIDATION_ERROR, "Unknown delete scope.")
        result = await _tx_single(tx, query, subject_id=subject_id, ids=ids, now=now)
        affected_count = int((result or {}).get("count", 0))
        if affected_count:
            profile = await _tx_single(
                tx,
                """
                MATCH (profile:Profile {subject_id: $subject_id})
                SET profile.revision = coalesce(profile.revision, 0) + 1, profile.updated_at = $now
                RETURN profile.revision AS revision
                """,
                subject_id=subject_id,
                now=now,
            )
        else:
            profile = await _tx_single(
                tx,
                "OPTIONAL MATCH (profile:Profile {subject_id: $subject_id}) "
                "RETURN coalesce(profile.revision, 0) AS revision",
                subject_id=subject_id,
            )
        response = {
            "status": "retired" if mode == "retire" else "deleted",
            "scope": scope,
            "affected_count": affected_count,
            "profile_revision": int((profile or {}).get("revision", 0)),
        }
        await _store_delete_result(
            tx,
            subject_id=subject_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            result=response,
            now=now,
        )
        return response

    async def _profile_revision(self, subject_id: str) -> int:
        result = await self._single(
            "OPTIONAL MATCH (profile:Profile {subject_id: $subject_id}) "
            "RETURN coalesce(profile.revision, 0) AS revision",
            subject_id=subject_id,
        )
        return int((result or {}).get("revision", 0))

    async def _execute(self, query: str, **parameters: Any) -> None:
        await self._driver.execute_query(
            query,
            parameters_=parameters,
            database_=self._database,
        )

    async def _records(self, query: str, **parameters: Any) -> list[dict[str, Any]]:
        eager = await self._driver.execute_query(
            query,
            parameters_=parameters,
            database_=self._database,
        )
        return [record.data() for record in eager.records]

    async def _single(self, query: str, **parameters: Any) -> dict[str, Any] | None:
        records = await self._records(query, **parameters)
        return records[0] if records else None


def _normalize_and_preflight(
    subject_id: str,
    request: Mapping[str, Any],
    graph_nodes: list[dict[str, Any]],
    graph_edges: list[dict[str, Any]],
    *,
    observation_ttl_seconds: int = 86400,
) -> tuple[dict[str, Any], list[dict[str, Any]], set[str]]:
    if request.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise MemoryError(
            MemoryErrorKind.SCHEMA_VERSION_MISMATCH,
            "The mutation schema version is not supported.",
            expected=SCHEMA_VERSION,
            received=request.get("schema_version"),
        )
    validate_privacy(_all_strings(request))
    node_types = {item["id"]: NodeType(item["node_type"]) for item in graph_nodes}
    node_properties = {item["id"]: dict(item["properties"]) for item in graph_nodes}
    existing_edges = []
    for item in graph_edges:
        source, relation, target = (
            item["source"],
            RelationType(item["relation"]),
            item["target"],
        )
        if relation == RelationType.CONFLICTS_WITH:
            source, target = normalize_conflict_endpoints(source, target)
        existing_edges.append((source, relation, target))
    existing_edge_set = set(existing_edges)
    canonical_keys = {
        properties.get("canonical_key")
        for properties in node_properties.values()
        if properties.get("canonical_key")
    }
    operations = list(request.get("operations") or [])
    if not operations or len(operations) > 50:
        raise MemoryError(
            MemoryErrorKind.LIMIT_EXCEEDED,
            "A mutation must contain between 1 and 50 operations.",
            maximum=50,
        )
    client_ids: dict[str, str] = {}
    client_types: dict[str, NodeType] = {}
    primitive: list[dict[str, Any]] = []
    preview_operations: list[dict[str, Any]] = []
    affected: set[str] = set()

    # Allocate all server IDs first so operations may reference later client_ref values.
    def reserve(client_ref: object, node_type: NodeType) -> None:
        ref = str(client_ref)
        if ref in client_ids:
            raise MemoryError(
                MemoryErrorKind.DUPLICATE_DETECTED,
                "A client_ref may be assigned only once per mutation.",
                client_ref=ref,
            )
        client_ids[ref] = _new_id(node_type)
        client_types[ref] = node_type

    for raw in operations:
        operation = str(raw["operation"])
        if operation == MutationOperation.CREATE_NODE.value:
            node = dict(raw["node"])
            node_type = NodeType(str(node["node_type"]))
            reserve(node["client_ref"], node_type)
        elif operation == MutationOperation.ADD_EVIDENCE.value:
            evidence = dict(raw["evidence"])
            source = dict(evidence["source"])
            reserve(evidence["client_ref"], NodeType.EVIDENCE)
            reserve(source["client_ref"], NodeType.SOURCE)
        elif operation == MutationOperation.SUPERSEDE_CLAIM.value:
            replacement = dict(raw["replacement"])
            evidence = dict(raw["evidence"])
            source = dict(evidence["source"])
            for client_ref, node_type in (
                (replacement["client_ref"], NodeType.CLAIM),
                (evidence["client_ref"], NodeType.EVIDENCE),
                (source["client_ref"], NodeType.SOURCE),
            ):
                reserve(client_ref, node_type)
    node_types.update({client_ids[ref]: node_type for ref, node_type in client_types.items()})

    for raw in operations:
        operation = str(raw["operation"])
        if operation == MutationOperation.CREATE_NODE.value:
            node = dict(raw["node"])
            node_type = NodeType(str(node.pop("node_type")))
            client_ref = str(node.pop("client_ref"))
            node_id = client_ids[client_ref]
            properties = _new_node_properties(subject_id, node_id, node_type, node)
            if node_type == NodeType.OBSERVATION:
                observed_at = _as_datetime(properties["observed_at"])
                expires_at = _as_datetime(properties["expires_at"])
                if expires_at - observed_at > timedelta(seconds=observation_ttl_seconds):
                    raise MemoryError(
                        MemoryErrorKind.LIMIT_EXCEEDED,
                        "Observation expiry exceeds the configured TTL.",
                        maximum_seconds=observation_ttl_seconds,
                    )
            if node_type == NodeType.MEMORY_SPACE and any(
                existing_type == NodeType.MEMORY_SPACE
                and existing_properties.get("space_key") == properties.get("space_key")
                for existing_id, existing_type in node_types.items()
                if existing_id != node_id
                for existing_properties in [node_properties.get(existing_id, {})]
            ):
                raise MemoryError(
                    MemoryErrorKind.DUPLICATE_DETECTED,
                    "A MemorySpace with this space_key already exists.",
                )
            canonical = properties.get("canonical_key")
            if canonical and canonical in canonical_keys:
                raise MemoryError(
                    MemoryErrorKind.DUPLICATE_DETECTED,
                    "An equivalent node already exists.",
                    node_type=node_type.value,
                )
            if canonical:
                canonical_keys.add(canonical)
            node_types[node_id] = node_type
            node_properties[node_id] = properties
            primitive.append({"operation": "create_node", "node_type": node_type.value, "properties": properties})
            preview_operations.append(
                {
                    "operation": operation,
                    "client_ref": client_ref,
                    "assigned_client_refs": {client_ref: node_id},
                }
            )
            affected.add(node_id)
        elif operation == MutationOperation.UPDATE_NODE_PROPERTIES.value:
            target_id = str(raw["target_node_id"])
            _require_node(target_id, node_types)
            update = dict(raw["update"])
            expected_type = NodeType(str(update.pop("node_type")))
            if node_types[target_id] != expected_type:
                raise MemoryError(
                    MemoryErrorKind.DOMAIN_RANGE_VIOLATION,
                    "The update model does not match the stored node type.",
                )
            expected_revision = raw.get("expected_revision")
            if expected_revision is not None and int(
                node_properties[target_id].get("revision", 0)
            ) != int(expected_revision):
                raise MemoryError(
                    MemoryErrorKind.REVISION_CONFLICT,
                    "The target node revision changed.",
                    target_node_id=target_id,
                    retryable=True,
                )
            update = {key: value for key, value in update.items() if value is not None}
            merged = {**node_properties[target_id], **update}
            if (
                expected_type == NodeType.CLAIM
                and merged.get("valid_from")
                and merged.get("valid_until")
                and _as_datetime(merged["valid_from"]) > _as_datetime(merged["valid_until"])
            ):
                raise MemoryError(
                    MemoryErrorKind.VALIDATION_ERROR,
                    "valid_from must not be after valid_until.",
                )
            if (
                expected_type in {NodeType.EVIDENCE, NodeType.OBSERVATION}
                and merged.get("observed_at")
                and merged.get("expires_at")
                and _as_datetime(merged["expires_at"]) <= _as_datetime(merged["observed_at"])
            ):
                raise MemoryError(
                    MemoryErrorKind.VALIDATION_ERROR,
                    "expires_at must be after observed_at.",
                )
            if expected_type == NodeType.CLAIM and "statement" in update:
                new_canonical_key = canonical_key(
                    subject_id=subject_id,
                    node_type=NodeType.CLAIM,
                    kind=str(merged.get("claim_kind", "")),
                    subject=str(merged["statement"]),
                )
                if new_canonical_key in canonical_keys and new_canonical_key != node_properties[
                    target_id
                ].get("canonical_key"):
                    raise MemoryError(
                        MemoryErrorKind.DUPLICATE_DETECTED,
                        "An equivalent Claim already exists.",
                    )
                update["canonical_key"] = new_canonical_key
                update["search_text"] = merged["statement"]
            elif expected_type == NodeType.CONCEPT and "name" in update:
                new_canonical_key = canonical_key(
                    subject_id=subject_id,
                    node_type=NodeType.CONCEPT,
                    kind=str(merged.get("concept_kind", "")),
                    subject=str(merged["name"]),
                )
                if new_canonical_key in canonical_keys and new_canonical_key != node_properties[
                    target_id
                ].get("canonical_key"):
                    raise MemoryError(
                        MemoryErrorKind.DUPLICATE_DETECTED,
                        "An equivalent Concept already exists.",
                    )
                update["canonical_key"] = new_canonical_key
                update["search_text"] = merged["name"]
            elif expected_type in {NodeType.CONTEXT, NodeType.MEMORY_SPACE} and {
                "name",
                "summary",
            } & update.keys():
                update["search_text"] = " ".join(
                    str(merged.get(key) or "") for key in ("name", "summary")
                ).strip()
            elif expected_type == NodeType.PREFERENCE_RULE and "summary" in update:
                update["search_text"] = merged["summary"]
            node_properties[target_id].update(update)
            primitive.append({"operation": "update_node_properties", "target_node_id": target_id, "properties": update})
            preview_operations.append({"operation": operation, "target_node_id": target_id})
            affected.add(target_id)
        elif operation == MutationOperation.ADD_EDGE.value:
            source_id, source_type = _resolve_ref(raw["source"], client_ids, client_types, node_types)
            target_id, target_type = _resolve_ref(raw["target"], client_ids, client_types, node_types)
            relation = RelationType(str(raw["relation"]))
            _validate_rule_target_status(
                relation,
                source_id,
                target_id,
                source_type,
                node_properties,
            )
            source_id, target_id = _validate_proposed_edge(
                relation,
                source_id,
                source_type,
                target_id,
                target_type,
                existing_edges,
                existing_edge_set,
            )
            edge = (source_id, relation, target_id)
            existing_edges.append(edge)
            existing_edge_set.add(edge)
            primitive.append({"operation": "add_edge", "source_id": source_id, "relation": relation.value, "target_id": target_id})
            preview_operations.append({"operation": operation, "source_id": source_id, "relation": relation.value, "target_id": target_id})
            affected.update((source_id, target_id))
        elif operation == MutationOperation.REMOVE_EDGE.value:
            source_id, target_id = str(raw["source_node_id"]), str(raw["target_node_id"])
            relation = RelationType(str(raw["relation"]))
            _require_node(source_id, node_types)
            _require_node(target_id, node_types)
            edge = (source_id, relation, target_id)
            if relation == RelationType.CONFLICTS_WITH:
                source_id, target_id = normalize_conflict_endpoints(source_id, target_id)
                edge = (source_id, relation, target_id)
            if edge not in existing_edge_set:
                raise MemoryError(
                    MemoryErrorKind.NOT_FOUND,
                    "The relation to remove was not found.",
                )
            existing_edge_set.remove(edge)
            existing_edges.remove(edge)
            primitive.append({"operation": "remove_edge", "source_id": source_id, "relation": relation.value, "target_id": target_id})
            preview_operations.append(dict(primitive[-1]))
            affected.update((source_id, target_id))
        elif operation == MutationOperation.ADD_EVIDENCE.value:
            if raw.get("target") is not None:
                target_id, target_type = _resolve_ref(
                    raw["target"],
                    client_ids,
                    client_types,
                    node_types,
                )
            elif raw.get("target_node_id") is not None:
                target_id = str(raw["target_node_id"])
                target_type = _require_node(target_id, node_types)
            else:
                target_ref = str(raw.get("target_client_ref") or "")
                if target_ref not in client_ids:
                    raise MemoryError(
                        MemoryErrorKind.NOT_FOUND,
                        "The Evidence target client_ref could not be resolved.",
                    )
                target_id = client_ids[target_ref]
                target_type = client_types[target_ref]
            evidence = dict(raw["evidence"])
            source = dict(evidence.pop("source"))
            evidence_id = client_ids[str(evidence.pop("client_ref"))]
            source_id = client_ids[str(source.pop("client_ref"))]
            relation = RelationType(str(raw.get("relation", RelationType.SUPPORTED_BY.value)))
            _append_created_node(
                primitive, node_types, node_properties, subject_id, source_id, NodeType.SOURCE, source
            )
            _append_created_node(
                primitive, node_types, node_properties, subject_id, evidence_id, NodeType.EVIDENCE, evidence
            )
            for source_node, edge_relation, target_node, source_type, target_type in (
                (evidence_id, RelationType.HAS_SOURCE, source_id, NodeType.EVIDENCE, NodeType.SOURCE),
                (target_id, relation, evidence_id, target_type, NodeType.EVIDENCE),
            ):
                _validate_proposed_edge(
                    edge_relation,
                    source_node,
                    source_type,
                    target_node,
                    target_type,
                    existing_edges,
                    existing_edge_set,
                )
                existing_edges.append((source_node, edge_relation, target_node))
                existing_edge_set.add((source_node, edge_relation, target_node))
                primitive.append({"operation": "add_edge", "source_id": source_node, "relation": edge_relation.value, "target_id": target_node})
            preview_operations.append(
                {
                    "operation": operation,
                    "target_node_id": target_id,
                    "assigned_client_refs": {
                        raw["evidence"]["client_ref"]: evidence_id,
                        raw["evidence"]["source"]["client_ref"]: source_id,
                    },
                }
            )
            affected.update((target_id, evidence_id, source_id))
        elif operation == MutationOperation.RETIRE_NODE.value:
            target_id = str(raw["target_node_id"])
            _require_node(target_id, node_types)
            primitive.append({"operation": "retire_node", "target_node_id": target_id})
            preview_operations.append({"operation": operation, "target_node_id": target_id})
            affected.add(target_id)
        elif operation == MutationOperation.SUPERSEDE_CLAIM.value:
            old_id = str(raw["old_claim_id"])
            if _require_node(old_id, node_types) != NodeType.CLAIM:
                raise MemoryError(MemoryErrorKind.DOMAIN_RANGE_VIOLATION, "Only a Claim can be superseded.")
            replacement = dict(raw["replacement"])
            replacement_ref = str(replacement.pop("client_ref"))
            replacement.pop("node_type", None)
            new_id = client_ids[replacement_ref]
            _append_created_node(
                primitive, node_types, node_properties, subject_id, new_id, NodeType.CLAIM, replacement
            )
            # A replacement inherits the old Claim's target/context/space
            # structure; the new statement and Evidence remain explicit.
            for _, inherited_relation, inherited_target in [
                edge
                for edge in existing_edges
                if edge[0] == old_id
                and edge[1]
                in {RelationType.TARGETS, RelationType.APPLIES_IN, RelationType.BELONGS_TO}
            ]:
                primitive.append(
                    {
                        "operation": "add_edge",
                        "source_id": new_id,
                        "relation": inherited_relation.value,
                        "target_id": inherited_target,
                    }
                )
                existing_edges.append((new_id, inherited_relation, inherited_target))
                existing_edge_set.add((new_id, inherited_relation, inherited_target))
            _validate_proposed_edge(
                RelationType.SUPERSEDES,
                new_id,
                NodeType.CLAIM,
                old_id,
                NodeType.CLAIM,
                existing_edges,
                existing_edge_set,
            )
            primitive.extend(
                [
                    {
                        "operation": "add_edge",
                        "source_id": new_id,
                        "relation": RelationType.SUPERSEDES.value,
                        "target_id": old_id,
                    },
                    {
                        "operation": "set_status",
                        "target_node_id": old_id,
                        "status": NodeStatus.SUPERSEDED.value,
                    },
                ]
            )
            existing_edges.append((new_id, RelationType.SUPERSEDES, old_id))
            existing_edge_set.add((new_id, RelationType.SUPERSEDES, old_id))
            evidence = dict(raw["evidence"])
            source = dict(evidence.pop("source"))
            evidence_ref = str(evidence.pop("client_ref"))
            source_ref = str(source.pop("client_ref"))
            evidence_id = client_ids[evidence_ref]
            source_id = client_ids[source_ref]
            _append_created_node(
                primitive, node_types, node_properties, subject_id, source_id, NodeType.SOURCE, source
            )
            _append_created_node(
                primitive, node_types, node_properties, subject_id, evidence_id, NodeType.EVIDENCE, evidence
            )
            for source_node, relation, target_node, source_type, target_type in (
                (evidence_id, RelationType.HAS_SOURCE, source_id, NodeType.EVIDENCE, NodeType.SOURCE),
                (new_id, RelationType.SUPPORTED_BY, evidence_id, NodeType.CLAIM, NodeType.EVIDENCE),
            ):
                _validate_proposed_edge(
                    relation,
                    source_node,
                    source_type,
                    target_node,
                    target_type,
                    existing_edges,
                    existing_edge_set,
                )
                existing_edges.append((source_node, relation, target_node))
                existing_edge_set.add((source_node, relation, target_node))
                primitive.append(
                    {
                        "operation": "add_edge",
                        "source_id": source_node,
                        "relation": relation.value,
                        "target_id": target_node,
                    }
                )
            preview_operations.append(
                {
                    "operation": operation,
                    "old_claim_id": old_id,
                    "assigned_client_refs": {
                        replacement_ref: new_id,
                        evidence_ref: evidence_id,
                        source_ref: source_id,
                    },
                }
            )
            affected.update((old_id, new_id, evidence_id, source_id))
        elif operation in {
            MutationOperation.ASSIGN_SPACE.value,
            MutationOperation.REMOVE_SPACE_ASSIGNMENT.value,
        }:
            if operation == MutationOperation.ASSIGN_SPACE.value:
                node_id, node_type = _resolve_ref(raw["node"], client_ids, client_types, node_types)
                space_id, space_type = _resolve_ref(raw["space"], client_ids, client_types, node_types)
            else:
                node_id, space_id = str(raw["node_id"]), str(raw["space_id"])
                node_type, space_type = _require_node(node_id, node_types), _require_node(space_id, node_types)
            validate_relation(
                RelationType.BELONGS_TO,
                node_type,
                space_type,
                source_id=node_id,
                target_id=space_id,
            )
            primitive.append(
                {
                    "operation": "add_edge" if operation == MutationOperation.ASSIGN_SPACE.value else "remove_edge",
                    "source_id": node_id,
                    "relation": RelationType.BELONGS_TO.value,
                    "target_id": space_id,
                }
            )
            edge = (node_id, RelationType.BELONGS_TO, space_id)
            if operation == MutationOperation.ASSIGN_SPACE.value:
                if edge in existing_edge_set:
                    raise MemoryError(
                        MemoryErrorKind.DUPLICATE_DETECTED,
                        "The space assignment already exists.",
                    )
                existing_edges.append(edge)
                existing_edge_set.add(edge)
            elif edge in existing_edge_set:
                existing_edges.remove(edge)
                existing_edge_set.remove(edge)
            else:
                raise MemoryError(
                    MemoryErrorKind.NOT_FOUND,
                    "The space assignment to remove was not found.",
                )
            preview_operations.append({"operation": operation, "node_id": node_id, "space_id": space_id})
            affected.update((node_id, space_id))
        else:
            raise MemoryError(
                MemoryErrorKind.VALIDATION_ERROR,
                "Unsupported memory mutation operation.",
                received=operation,
            )

    _validate_created_integrity(node_types, node_properties, existing_edges, primitive)
    _apply_confidence_policy(node_types, node_properties, existing_edges, primitive, affected)
    return {"operations": primitive}, preview_operations, affected


def _validate_created_integrity(
    node_types: Mapping[str, NodeType],
    node_properties: Mapping[str, Mapping[str, Any]],
    edges: list[tuple[str, RelationType, str]],
    primitive: list[dict[str, Any]],
) -> None:
    created_ids = {
        item["properties"]["id"]
        for item in primitive
        if item["operation"] == "create_node"
    }
    rule_ids_to_validate = {
        node_id for node_id in created_ids if node_types[node_id] == NodeType.PREFERENCE_RULE
    } | {
        item["source_id"]
        for item in primitive
        if item["operation"] in {"add_edge", "remove_edge"}
        and item["relation"]
        in {
            RelationType.WHEN.value,
            RelationType.PREFERS.value,
            RelationType.OVER.value,
            RelationType.SUPPORTED_BY.value,
            RelationType.CONTRADICTED_BY.value,
        }
        and node_types.get(item["source_id"]) == NodeType.PREFERENCE_RULE
    }
    claim_ids_to_validate = {
        node_id for node_id in created_ids if node_types[node_id] == NodeType.CLAIM
    } | {
        item["source_id"]
        for item in primitive
        if item["operation"] in {"add_edge", "remove_edge"}
        and item["relation"]
        in {
            RelationType.TARGETS.value,
            RelationType.SUPPORTED_BY.value,
            RelationType.CONTRADICTED_BY.value,
        }
        and node_types.get(item["source_id"]) == NodeType.CLAIM
    }
    for node_id in created_ids | rule_ids_to_validate | claim_ids_to_validate:
        node_type = node_types[node_id]
        outgoing = [(relation, target) for source, relation, target in edges if source == node_id]
        if node_type == NodeType.CLAIM:
            validate_claim_integrity(
                [relation for relation, _ in outgoing],
                status=NodeStatus(str(node_properties[node_id].get("status", NodeStatus.DRAFT.value))),
            )
        elif node_type == NodeType.PREFERENCE_RULE:
            rule_status = NodeStatus(
                str(node_properties[node_id].get("status", NodeStatus.DRAFT.value))
            )
            validate_preference_rule(
                outgoing,
                status=rule_status,
            )
            if rule_status == NodeStatus.ACTIVE and any(
                relation in {RelationType.PREFERS, RelationType.OVER}
                and str(
                    node_properties.get(target, {}).get("status", NodeStatus.ACTIVE.value)
                )
                in {
                    NodeStatus.RETIRED.value,
                    NodeStatus.SUPERSEDED.value,
                    NodeStatus.DELETED.value,
                }
                for relation, target in outgoing
            ):
                raise MemoryError(
                    MemoryErrorKind.VALIDATION_ERROR,
                    "An active PreferenceRule cannot directly target an inactive Claim.",
                )
            validate_preference_rule_conflicts(
                context_ids=[
                    target for relation, target in outgoing if relation == RelationType.WHEN
                ],
                prefers_ids=[
                    target for relation, target in outgoing if relation == RelationType.PREFERS
                ],
                over_ids=[target for relation, target in outgoing if relation == RelationType.OVER],
                existing_rules=[
                    (
                        [
                            target
                            for source, relation, target in edges
                            if source == other_id and relation == RelationType.WHEN
                        ],
                        [
                            target
                            for source, relation, target in edges
                            if source == other_id and relation == RelationType.PREFERS
                        ],
                        [
                            target
                            for source, relation, target in edges
                            if source == other_id and relation == RelationType.OVER
                        ],
                    )
                    for other_id, other_type in node_types.items()
                    if other_type == NodeType.PREFERENCE_RULE
                    and other_id != node_id
                    and str(node_properties.get(other_id, {}).get("status", NodeStatus.ACTIVE.value))
                    == NodeStatus.ACTIVE.value
                ],
            )
        elif node_type == NodeType.EVIDENCE and not any(
            relation == RelationType.HAS_SOURCE for relation, _ in outgoing
        ):
            raise MemoryError(
                MemoryErrorKind.VALIDATION_ERROR,
                "Evidence requires a Source.",
            )
    by_source: dict[str, dict[RelationType, set[str]]] = {}
    for source, relation, target in edges:
        by_source.setdefault(source, {}).setdefault(relation, set()).add(target)
    for relations in by_source.values():
        validate_evidence_connections(
            relations.get(RelationType.SUPPORTED_BY, set()),
            relations.get(RelationType.CONTRADICTED_BY, set()),
        )


def _apply_confidence_policy(
    node_types: Mapping[str, NodeType],
    node_properties: dict[str, dict[str, Any]],
    edges: list[tuple[str, RelationType, str]],
    primitive: list[dict[str, Any]],
    affected: set[str],
) -> None:
    created_operations = {
        item["properties"]["id"]: item
        for item in primitive
        if item["operation"] == "create_node"
    }
    for node_id in affected:
        if node_types.get(node_id) not in {NodeType.CLAIM, NodeType.PREFERENCE_RULE}:
            continue
        proposed = node_properties.get(node_id, {}).get("confidence")
        if proposed is None:
            continue
        supporting = [
            target
            for source, relation, target in edges
            if source == node_id and relation == RelationType.SUPPORTED_BY
        ]
        contradicting = [
            target
            for source, relation, target in edges
            if source == node_id and relation == RelationType.CONTRADICTED_BY
        ]
        evidence_kinds = [
            EvidenceKind(str(node_properties[evidence_id]["evidence_kind"]))
            for evidence_id in [*supporting, *contradicting]
            if evidence_id in node_properties and node_properties[evidence_id].get("evidence_kind")
        ]
        if not evidence_kinds:
            continue
        adjusted = adjust_confidence(
            float(proposed),
            evidence_kinds,
            contradicting_count=len(contradicting),
        )
        node_properties[node_id]["confidence"] = adjusted
        if node_id in created_operations:
            created_operations[node_id]["properties"]["confidence"] = adjusted
            continue
        existing_update = next(
            (
                item
                for item in primitive
                if item["operation"] == "update_node_properties"
                and item["target_node_id"] == node_id
            ),
            None,
        )
        if existing_update is None:
            primitive.append(
                {
                    "operation": "update_node_properties",
                    "target_node_id": node_id,
                    "properties": {"confidence": adjusted},
                }
            )
        else:
            existing_update["properties"]["confidence"] = adjusted


async def _apply_patch(
    tx: AsyncManagedTransaction,
    *,
    subject_id: str,
    profile_id: str,
    operations: list[dict[str, Any]],
    now: datetime,
) -> tuple[list[str], set[str]]:
    created: list[str] = []
    updated: set[str] = set()
    ordered = sorted(operations, key=lambda item: item["operation"] != "create_node")
    for operation in ordered:
        kind = operation["operation"]
        if kind == "create_node":
            node_type = NodeType(operation["node_type"])
            query = _CREATE_NODE_QUERIES[node_type]
            properties = _neo4j_properties(operation["properties"])
            await _tx_consume(tx, query, properties=properties)
            node_id = str(properties["id"])
            created.append(node_id)
            if node_type == NodeType.CLAIM:
                await _tx_consume(
                    tx,
                    """
                    MATCH (profile:Profile {subject_id: $subject_id, id: $profile_id})
                    MATCH (claim:Claim {subject_id: $subject_id, id: $node_id})
                    MERGE (profile)-[:CONTAINS_CLAIM]->(claim)
                    """,
                    subject_id=subject_id,
                    profile_id=profile_id,
                    node_id=node_id,
                )
        elif kind == "update_node_properties":
            await _tx_consume(
                tx,
                """
                MATCH (node {subject_id: $subject_id, id: $target_node_id})
                SET node += $properties, node.updated_at = $now,
                    node.revision = coalesce(node.revision, 0) + 1
                """,
                subject_id=subject_id,
                target_node_id=operation["target_node_id"],
                properties=_neo4j_properties(operation["properties"]),
                now=now,
            )
            updated.add(operation["target_node_id"])
        elif kind in {"add_edge", "remove_edge"}:
            relation = RelationType(operation["relation"])
            query = (
                _ADD_EDGE_QUERIES[relation]
                if kind == "add_edge"
                else _REMOVE_EDGE_QUERIES[relation]
            )
            await _tx_consume(
                tx,
                query,
                subject_id=subject_id,
                source_id=operation["source_id"],
                target_id=operation["target_id"],
                now=now,
            )
            updated.update((operation["source_id"], operation["target_id"]))
        elif kind in {"retire_node", "set_status"}:
            status = operation.get("status", NodeStatus.RETIRED.value)
            await _tx_consume(
                tx,
                """
                MATCH (node {subject_id: $subject_id, id: $target_node_id})
                SET node.status = $status, node.updated_at = $now,
                    node.revision = coalesce(node.revision, 0) + 1
                """,
                subject_id=subject_id,
                target_node_id=operation["target_node_id"],
                status=status,
                now=now,
            )
            updated.add(operation["target_node_id"])
        else:
            raise MemoryError(MemoryErrorKind.VALIDATION_ERROR, "Stored mutation operation is invalid.")
    return created, updated


def _new_node_properties(
    subject_id: str,
    node_id: str,
    node_type: NodeType,
    values: Mapping[str, Any],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    properties = {
        key: _jsonable(value)
        for key, value in values.items()
        if key
        not in {
            "id",
            "subject_id",
            "schema_version",
            "revision",
            "created_at",
            "updated_at",
            "canonical_key_candidate",
        }
        and value is not None
    }
    properties.update(
        {
            "id": node_id,
            "subject_id": subject_id,
            "schema_version": SCHEMA_VERSION,
            "status": str(
                properties.get(
                    "status",
                    (
                        NodeStatus.DRAFT.value
                        if node_type in {NodeType.CLAIM, NodeType.PREFERENCE_RULE}
                        else NodeStatus.ACTIVE.value
                    ),
                )
            ),
            "revision": 0,
            "created_at": now,
            "updated_at": now,
        }
    )
    if node_type == NodeType.CLAIM:
        properties["canonical_key"] = canonical_key(
            subject_id=subject_id,
            node_type=node_type,
            kind=str(properties.get("claim_kind", "")),
            subject=str(properties.get("statement", "")),
        )
        properties["search_text"] = properties.get("statement")
    elif node_type == NodeType.CONCEPT:
        properties["canonical_key"] = canonical_key(
            subject_id=subject_id,
            node_type=node_type,
            kind=str(properties.get("concept_kind", "")),
            subject=str(properties.get("name", "")),
        )
        properties["search_text"] = properties.get("name")
    elif node_type in {NodeType.CONTEXT, NodeType.MEMORY_SPACE}:
        properties["search_text"] = " ".join(
            str(properties.get(key) or "") for key in ("name", "summary")
        ).strip()
    elif node_type == NodeType.PREFERENCE_RULE:
        properties["search_text"] = properties.get("summary")
    return properties


def _append_created_node(
    primitive: list[dict[str, Any]],
    node_types: dict[str, NodeType],
    node_properties: dict[str, dict[str, Any]],
    subject_id: str,
    node_id: str,
    node_type: NodeType,
    values: Mapping[str, Any],
) -> None:
    properties = _new_node_properties(subject_id, node_id, node_type, values)
    node_types[node_id] = node_type
    node_properties[node_id] = properties
    primitive.append({"operation": "create_node", "node_type": node_type.value, "properties": properties})


def _validate_proposed_edge(
    relation: RelationType,
    source_id: str,
    source_type: NodeType,
    target_id: str,
    target_type: NodeType,
    edges: list[tuple[str, RelationType, str]],
    edge_set: set[tuple[str, RelationType, str]],
) -> tuple[str, str]:
    validate_relation(
        relation,
        source_type,
        target_type,
        source_id=source_id,
        target_id=target_id,
    )
    if relation == RelationType.CONFLICTS_WITH:
        source_id, target_id = normalize_conflict_endpoints(source_id, target_id)
    if (source_id, relation, target_id) in edge_set:
        raise MemoryError(
            MemoryErrorKind.DUPLICATE_DETECTED,
            "The relation already exists.",
            relation=relation.value,
        )
    if RELATION_RULES[relation].acyclic:
        validate_cycle(
            edges,
            relation=relation,
            source_id=source_id,
            target_id=target_id,
        )
    return source_id, target_id


def _validate_rule_target_status(
    relation: RelationType,
    source_id: str,
    target_id: str,
    source_type: NodeType,
    node_properties: Mapping[str, Mapping[str, Any]],
) -> None:
    if (
        source_type == NodeType.PREFERENCE_RULE
        and relation in {RelationType.PREFERS, RelationType.OVER}
        and str(node_properties.get(source_id, {}).get("status", NodeStatus.DRAFT.value))
        == NodeStatus.ACTIVE.value
        and str(node_properties.get(target_id, {}).get("status", NodeStatus.ACTIVE.value))
        in {NodeStatus.RETIRED.value, NodeStatus.SUPERSEDED.value, NodeStatus.DELETED.value}
    ):
        raise MemoryError(
            MemoryErrorKind.VALIDATION_ERROR,
            "An active PreferenceRule cannot directly target an inactive Claim.",
            target_node_id=target_id,
        )


def _resolve_ref(
    raw: Mapping[str, Any],
    client_ids: Mapping[str, str],
    client_types: Mapping[str, NodeType],
    node_types: Mapping[str, NodeType],
) -> tuple[str, NodeType]:
    if raw.get("node_id"):
        node_id = str(raw["node_id"])
        return node_id, _require_node(node_id, node_types)
    client_ref = str(raw.get("client_ref") or "")
    if client_ref not in client_ids:
        raise MemoryError(MemoryErrorKind.NOT_FOUND, "A client_ref could not be resolved.")
    return client_ids[client_ref], client_types[client_ref]


def _require_node(node_id: str, node_types: Mapping[str, NodeType]) -> NodeType:
    node_type = node_types.get(node_id)
    if node_type is None:
        raise MemoryError(
            MemoryErrorKind.NOT_FOUND,
            "A referenced node was not found for this subject.",
            node_id=node_id,
        )
    return node_type


def _preview_result(mutation: Mapping[str, Any]) -> dict[str, Any]:
    result = json.loads(str(mutation["preview_result_json"]))
    if mutation.get("status") == "expired" or _as_datetime(mutation["expires_at"]) <= datetime.now(UTC):
        raise MemoryError(MemoryErrorKind.MUTATION_EXPIRED, "The memory mutation has expired.")
    return result


def _public_properties(properties: Mapping[str, Any]) -> dict[str, Any]:
    blocked = {
        "subject_id",
        "embedding",
        "normalized_patch_json",
        "preview_result_json",
        "apply_result_json",
        "request_digest",
        "source_ref",
        "source_locator",
        "apply_lock",
    }
    return {
        key: _jsonable(value)
        for key, value in properties.items()
        if key not in blocked and not key.startswith("_")
    }


def _neo4j_properties(properties: Mapping[str, Any]) -> dict[str, Any]:
    result = {}
    datetime_keys = {
        "created_at",
        "updated_at",
        "observed_at",
        "expires_at",
        "valid_from",
        "valid_until",
        "source_created_at",
        "last_used_at",
    }
    for key, value in properties.items():
        if key in datetime_keys and isinstance(value, str):
            value = _as_datetime(value)
        result[key] = _neo4j_value(value)
    return result


def _neo4j_value(value: Any) -> Any:
    if isinstance(value, dict):
        return canonical_json(value)
    if isinstance(value, list):
        if all(isinstance(item, (str, int, float, bool)) or item is None for item in value):
            return value
        return canonical_json(value)
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _query_tokens(query: str) -> list[str]:
    return [
        token.casefold()
        for token in re.findall(r"[\w\u3040-\u30ff\u3400-\u9fff]+", query, flags=re.UNICODE)
        if token
    ][:20] or ["memory"]


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [item for child in value.values() for item in _all_strings(child)]
    if isinstance(value, (list, tuple)):
        return [item for child in value for item in _all_strings(child)]
    return [value] if isinstance(value, str) else []


def _fulltext_query(tokens: Iterable[str]) -> str:
    return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)


def _score_for(records: Iterable[Mapping[str, Any]], item_id: str) -> float:
    for record in records:
        if record["id"] == item_id:
            return float(record.get("score") or 0.0)
    return 0.0


def _bounded(value: int, *, maximum: int, name: str) -> int:
    if value < 1 or value > maximum:
        raise MemoryError(
            MemoryErrorKind.LIMIT_EXCEEDED,
            f"{name} exceeds the repository safety limit.",
            maximum=maximum,
        )
    return value


def _new_id(node_type: NodeType) -> str:
    return f"{_NODE_PREFIX[node_type]}_{uuid4().hex}"


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


async def _store_delete_result(
    tx: AsyncManagedTransaction,
    *,
    subject_id: str,
    idempotency_key: str,
    request_digest: str,
    result: Mapping[str, Any],
    now: datetime,
) -> None:
    await _tx_consume(
        tx,
        """
        CREATE (mutation:MemoryMutation {
          id: $mutation_id, subject_id: $subject_id, schema_version: $schema_version,
          idempotency_key: $idempotency_key, request_digest: $request_digest,
          mutation_kind: 'delete', status: 'applied',
          apply_result_json: $result_json, created_at: $now, updated_at: $now
        })
        """,
        mutation_id=_new_id(NodeType.MEMORY_MUTATION),
        subject_id=subject_id,
        schema_version=SCHEMA_VERSION,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_json=canonical_json(result),
        now=now,
    )


async def _tx_records(
    tx: AsyncManagedTransaction,
    query: str,
    **parameters: Any,
) -> list[dict[str, Any]]:
    result = await tx.run(query, **parameters)
    return await result.data()


async def _tx_single(
    tx: AsyncManagedTransaction,
    query: str,
    **parameters: Any,
) -> dict[str, Any] | None:
    result = await tx.run(query, **parameters)
    record = await result.single()
    return record.data() if record is not None else None


async def _tx_consume(
    tx: AsyncManagedTransaction,
    query: str,
    **parameters: Any,
) -> None:
    result = await tx.run(query, **parameters)
    await result.consume()
