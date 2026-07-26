from __future__ import annotations

from dataclasses import dataclass

from .enums import (
    ClaimKind,
    ConceptKind,
    EvidenceKind,
    MutationOperation,
    MutationStatus,
    NodeStatus,
    NodeType,
    RelationType,
    SourceKind,
)

SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class RelationRule:
    source_types: frozenset[NodeType]
    target_types: frozenset[NodeType]
    self_loop_allowed: bool = True
    acyclic: bool = False
    symmetric: bool = False


RELATION_RULES: dict[RelationType, RelationRule] = {
    RelationType.HAS_PROFILE: RelationRule(frozenset({NodeType.USER}), frozenset({NodeType.PROFILE})),
    RelationType.CONTAINS_CLAIM: RelationRule(frozenset({NodeType.PROFILE}), frozenset({NodeType.CLAIM})),
    RelationType.BELONGS_TO: RelationRule(
        frozenset({NodeType.CLAIM, NodeType.CONCEPT, NodeType.CONTEXT, NodeType.PREFERENCE_RULE}),
        frozenset({NodeType.MEMORY_SPACE}),
    ),
    RelationType.TARGETS: RelationRule(frozenset({NodeType.CLAIM}), frozenset({NodeType.CONCEPT})),
    RelationType.APPLIES_IN: RelationRule(frozenset({NodeType.CLAIM}), frozenset({NodeType.CONTEXT})),
    RelationType.SUPPORTED_BY: RelationRule(
        frozenset({NodeType.CLAIM, NodeType.PREFERENCE_RULE}),
        frozenset({NodeType.EVIDENCE}),
    ),
    RelationType.CONTRADICTED_BY: RelationRule(
        frozenset({NodeType.CLAIM, NodeType.PREFERENCE_RULE}),
        frozenset({NodeType.EVIDENCE}),
    ),
    RelationType.HAS_SOURCE: RelationRule(frozenset({NodeType.EVIDENCE}), frozenset({NodeType.SOURCE})),
    RelationType.DERIVED_FROM: RelationRule(
        frozenset({NodeType.EVIDENCE}), frozenset({NodeType.OBSERVATION})
    ),
    RelationType.DEPENDS_ON: RelationRule(
        frozenset({NodeType.CLAIM}),
        frozenset({NodeType.CLAIM, NodeType.CONTEXT, NodeType.CONCEPT}),
        self_loop_allowed=False,
        acyclic=True,
    ),
    RelationType.CONFLICTS_WITH: RelationRule(
        frozenset({NodeType.CLAIM}),
        frozenset({NodeType.CLAIM}),
        self_loop_allowed=False,
        symmetric=True,
    ),
    RelationType.SUPERSEDES: RelationRule(
        frozenset({NodeType.CLAIM}),
        frozenset({NodeType.CLAIM}),
        self_loop_allowed=False,
        acyclic=True,
    ),
    RelationType.EXPLAINED_BY: RelationRule(
        frozenset({NodeType.CLAIM}), frozenset({NodeType.CLAIM})
    ),
    RelationType.STRENGTHENED_BY: RelationRule(
        frozenset({NodeType.CLAIM}), frozenset({NodeType.CLAIM})
    ),
    RelationType.WHEN: RelationRule(
        frozenset({NodeType.PREFERENCE_RULE}), frozenset({NodeType.CONTEXT})
    ),
    RelationType.PREFERS: RelationRule(
        frozenset({NodeType.PREFERENCE_RULE}), frozenset({NodeType.CLAIM})
    ),
    RelationType.OVER: RelationRule(
        frozenset({NodeType.PREFERENCE_RULE}), frozenset({NodeType.CLAIM})
    ),
}

PREFERENCE_RULE_REQUIRED_RELATIONS = frozenset(
    {RelationType.WHEN, RelationType.PREFERS, RelationType.OVER}
)


def ontology_document() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "node_types": [item.value for item in NodeType],
        "claim_kinds": [item.value for item in ClaimKind],
        "concept_kinds": [item.value for item in ConceptKind],
        "evidence_kinds": [item.value for item in EvidenceKind],
        "source_kinds": [item.value for item in SourceKind],
        "statuses": [item.value for item in NodeStatus],
        "mutation_statuses": [item.value for item in MutationStatus],
        "mutation_operations": [item.value for item in MutationOperation],
        "relations": [
            {
                "relation": relation.value,
                "from": sorted(item.value for item in rule.source_types),
                "to": sorted(item.value for item in rule.target_types),
                "self_loop_allowed": rule.self_loop_allowed,
                "acyclic": rule.acyclic,
                "symmetric": rule.symmetric,
            }
            for relation, rule in RELATION_RULES.items()
        ],
        "constraints": {
            "preference_rule_requires": sorted(
                relation.value for relation in PREFERENCE_RULE_REQUIRED_RELATIONS
            ),
            "preference_rule_distinct_prefers_over": True,
            "active_claim_or_rule_requires_evidence": True,
            "evidence_requires_source": True,
            "cross_subject_edges_allowed": False,
        },
        "update_flow": ["route", "search", "neighborhood", "preview", "confirmation", "apply"],
    }
