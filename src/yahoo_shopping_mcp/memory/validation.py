from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping

from .enums import NodeStatus, NodeType, RelationType
from .errors import MemoryError, MemoryErrorKind
from .ontology import PREFERENCE_RULE_REQUIRED_RELATIONS, RELATION_RULES

_CREDENTIAL = re.compile(
    r"(?i)\b(?:api[_ -]?key|password|passwd|secret|credential|bearer)\b\s*[:=]\s*\S+"
)
_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_SENSITIVE_TOPIC = re.compile(
    r"(?i)(?:"
    r"\b(?:health|religion|politic(?:s|al)?|sexual(?:ity)?|medical diagnosis|bank account|"
    r"social security|passport number|exact address)\b|"
    r"(?:健康|宗教|政治信条|性的指向|性生活|病歴|診断名|銀行口座|政府発行|正確な住所)"
    r")"
)


def validate_relation(
    relation: RelationType,
    source_type: NodeType,
    target_type: NodeType,
    *,
    source_id: str | None = None,
    target_id: str | None = None,
) -> None:
    rule = RELATION_RULES.get(relation)
    if rule is None:
        raise MemoryError(
            MemoryErrorKind.RELATION_NOT_ALLOWED,
            "Relation type is not defined by the active schema.",
            received=relation.value,
            allowed_relations=[item.value for item in RelationType],
        )
    validate_domain_range(relation, source_type, target_type)
    if source_id is not None and target_id is not None:
        validate_self_loop(relation, source_id, target_id)


def validate_domain_range(
    relation: RelationType,
    source_type: NodeType,
    target_type: NodeType,
) -> None:
    rule = RELATION_RULES[relation]
    if source_type not in rule.source_types or target_type not in rule.target_types:
        raise MemoryError(
            MemoryErrorKind.DOMAIN_RANGE_VIOLATION,
            "Relation endpoints do not match the fixed domain and range.",
            relation=relation.value,
            source_type=source_type.value,
            target_type=target_type.value,
        )


def validate_self_loop(relation: RelationType, source_id: str, target_id: str) -> None:
    if not RELATION_RULES[relation].self_loop_allowed and source_id == target_id:
        raise MemoryError(
            MemoryErrorKind.VALIDATION_ERROR,
            "Self-loop is not allowed for this relation.",
            relation=relation.value,
        )


def validate_subject_isolation(subject_ids: Iterable[str]) -> None:
    if len(set(subject_ids)) > 1:
        raise MemoryError(
            MemoryErrorKind.VALIDATION_ERROR,
            "Cross-subject graph references are not allowed.",
        )


def validate_cycle(
    edges: Iterable[tuple[str, RelationType, str]],
    *,
    relation: RelationType,
    source_id: str,
    target_id: str,
) -> None:
    if not RELATION_RULES[relation].acyclic:
        return
    if source_id == target_id:
        raise MemoryError(
            MemoryErrorKind.CYCLE_DETECTED,
            "The proposed relation creates a cycle.",
            relation=relation.value,
        )
    adjacency: dict[str, set[str]] = defaultdict(set)
    for source, edge_relation, target in edges:
        if edge_relation == relation:
            adjacency[source].add(target)
    pending = [target_id]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == source_id:
            raise MemoryError(
                MemoryErrorKind.CYCLE_DETECTED,
                "The proposed relation creates a cycle.",
                relation=relation.value,
            )
        if current not in visited:
            visited.add(current)
            pending.extend(adjacency[current] - visited)


def normalize_conflict_endpoints(source_id: str, target_id: str) -> tuple[str, str]:
    if source_id == target_id:
        raise MemoryError(
            MemoryErrorKind.VALIDATION_ERROR,
            "CONFLICTS_WITH cannot reference the same Claim.",
            relation=RelationType.CONFLICTS_WITH.value,
        )
    return tuple(sorted((source_id, target_id)))


def normalize_conflicts(
    edges: Iterable[tuple[str, RelationType, str]],
) -> list[tuple[str, RelationType, str]]:
    normalized: set[tuple[str, RelationType, str]] = set()
    for source, relation, target in edges:
        if relation == RelationType.CONFLICTS_WITH:
            source, target = normalize_conflict_endpoints(source, target)
        normalized.add((source, relation, target))
    return sorted(normalized, key=lambda item: (item[0], item[1].value, item[2]))


def validate_preference_rule(
    outgoing_edges: Iterable[tuple[RelationType, str]],
    *,
    status: NodeStatus = NodeStatus.DRAFT,
) -> None:
    targets: dict[RelationType, set[str]] = defaultdict(set)
    for relation, target_id in outgoing_edges:
        targets[relation].add(target_id)
    missing = sorted(
        relation.value for relation in PREFERENCE_RULE_REQUIRED_RELATIONS if not targets[relation]
    )
    if missing:
        raise MemoryError(
            MemoryErrorKind.VALIDATION_ERROR,
            "PreferenceRule is missing required relations.",
            missing_relations=missing,
        )
    overlap = targets[RelationType.PREFERS] & targets[RelationType.OVER]
    if overlap:
        raise MemoryError(
            MemoryErrorKind.VALIDATION_ERROR,
            "PREFERS and OVER must reference different Claims.",
        )
    if status == NodeStatus.ACTIVE and not (
        targets[RelationType.SUPPORTED_BY] or targets[RelationType.CONTRADICTED_BY]
    ):
        raise MemoryError(
            MemoryErrorKind.VALIDATION_ERROR,
            "An active PreferenceRule requires Evidence.",
        )


def validate_preference_rule_conflicts(
    *,
    context_ids: Iterable[str],
    prefers_ids: Iterable[str],
    over_ids: Iterable[str],
    existing_rules: Iterable[tuple[Iterable[str], Iterable[str], Iterable[str]]],
) -> None:
    contexts = set(context_ids)
    prefers = set(prefers_ids)
    over = set(over_ids)
    for existing_contexts, existing_prefers, existing_over in existing_rules:
        existing_context_set = set(existing_contexts)
        existing_prefers_set = set(existing_prefers)
        existing_over_set = set(existing_over)
        if not (contexts & existing_context_set):
            continue
        if prefers == existing_prefers_set and over == existing_over_set:
            raise MemoryError(
                MemoryErrorKind.DUPLICATE_DETECTED,
                "An equivalent PreferenceRule already exists.",
            )
        if prefers & existing_over_set and over & existing_prefers_set:
            raise MemoryError(
                MemoryErrorKind.VALIDATION_ERROR,
                "A reverse PreferenceRule exists in the same Context.",
            )


def validate_evidence_connections(
    supported_evidence_ids: Iterable[str],
    contradicted_evidence_ids: Iterable[str],
) -> None:
    if set(supported_evidence_ids) & set(contradicted_evidence_ids):
        raise MemoryError(
            MemoryErrorKind.VALIDATION_ERROR,
            "The same Evidence cannot support and contradict the same target.",
        )


def validate_claim_integrity(
    outgoing_relations: Iterable[RelationType],
    *,
    status: NodeStatus,
) -> None:
    relations = set(outgoing_relations)
    if RelationType.TARGETS not in relations:
        raise MemoryError(
            MemoryErrorKind.VALIDATION_ERROR,
            "A Claim requires a TARGETS relation.",
        )
    if status == NodeStatus.ACTIVE and not (
        {RelationType.SUPPORTED_BY, RelationType.CONTRADICTED_BY} & relations
    ):
        raise MemoryError(
            MemoryErrorKind.VALIDATION_ERROR,
            "An active Claim requires supporting Evidence.",
        )


def privacy_violations(text: str, *, max_length: int = 500) -> list[str]:
    violations: list[str] = []
    if len(text) > max_length:
        violations.append("content_too_long")
    if _CREDENTIAL.search(text):
        violations.append("credential")
    if any(_luhn_valid(match.group()) for match in _CARD_CANDIDATE.finditer(text)):
        violations.append("payment_card")
    if _SENSITIVE_TOPIC.search(text):
        violations.append("sensitive_attribute")
    if text.count("\n") > 8:
        violations.append("possible_full_transcript")
    return violations


def validate_privacy(texts: Iterable[str], *, max_length: int = 500) -> None:
    categories = sorted(
        {category for text in texts for category in privacy_violations(text, max_length=max_length)}
    )
    if categories:
        raise MemoryError(
            MemoryErrorKind.PRIVACY_VIOLATION,
            "Memory content violates the data minimization policy.",
            categories=categories,
        )


def validate_node_types(node_types: Mapping[str, NodeType]) -> None:
    if any(not isinstance(node_type, NodeType) for node_type in node_types.values()):
        raise MemoryError(
            MemoryErrorKind.NODE_TYPE_NOT_ALLOWED,
            "Node type is not defined by the active schema.",
        )


def _luhn_valid(candidate: str) -> bool:
    digits = [int(char) for char in candidate if char.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0
