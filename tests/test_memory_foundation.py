from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from yahoo_shopping_mcp.memory.canonicalization import canonical_key, memory_preview_hash
from yahoo_shopping_mcp.memory.confidence import adjust_confidence, cap_confidence
from yahoo_shopping_mcp.memory.enums import (
    ClaimKind,
    ConceptKind,
    EvidenceKind,
    NodeStatus,
    NodeType,
    RelationType,
)
from yahoo_shopping_mcp.memory.errors import MemoryError, MemoryErrorKind
from yahoo_shopping_mcp.memory.models import (
    AddEdgeOperation,
    ApplyMutationRequest,
    CreateNodeOperation,
    PreferenceGraphRequest,
    PreviewMutationRequest,
    SearchClaimCandidatesRequest,
)
from yahoo_shopping_mcp.memory.ontology import RELATION_RULES
from yahoo_shopping_mcp.memory.ranking import reciprocal_rank_fusion
from yahoo_shopping_mcp.memory.validation import (
    normalize_conflict_endpoints,
    normalize_conflicts,
    privacy_violations,
    validate_cycle,
    validate_preference_rule,
    validate_preference_rule_conflicts,
    validate_privacy,
    validate_relation,
    validate_self_loop,
)


def test_fixed_enums_are_exact() -> None:
    assert [item.value for item in NodeType] == [
        "User",
        "Profile",
        "MemorySpace",
        "Claim",
        "Concept",
        "Context",
        "PreferenceRule",
        "Evidence",
        "Source",
        "Observation",
        "MemoryMutation",
    ]
    assert [item.value for item in ClaimKind] == [
        "interest",
        "price_preference",
        "quality_preference",
        "origin_preference",
        "brand_preference",
        "product_attribute_preference",
        "purchase_intent",
        "avoidance",
    ]
    assert [item.value for item in ConceptKind] == [
        "interest_topic",
        "product_category",
        "product_attribute",
        "price_range",
        "brand",
        "origin",
        "seller",
        "shipping_condition",
        "purchase_target",
        "constraint",
    ]
    assert [item.value for item in EvidenceKind] == [
        "explicit_statement",
        "user_correction",
        "repeated_behavior",
        "search_observation",
        "comparison_observation",
        "purchase_observation",
        "imported_record",
    ]
    assert [item.value for item in NodeStatus] == [
        "draft",
        "active",
        "retired",
        "superseded",
        "deleted",
    ]


def test_all_17_relations_have_exact_domain_and_range() -> None:
    expected = {
        "HAS_PROFILE": ({"User"}, {"Profile"}),
        "CONTAINS_CLAIM": ({"Profile"}, {"Claim"}),
        "BELONGS_TO": (
            {"Claim", "Concept", "Context", "PreferenceRule"},
            {"MemorySpace"},
        ),
        "TARGETS": ({"Claim"}, {"Concept"}),
        "APPLIES_IN": ({"Claim"}, {"Context"}),
        "SUPPORTED_BY": ({"Claim", "PreferenceRule"}, {"Evidence"}),
        "CONTRADICTED_BY": ({"Claim", "PreferenceRule"}, {"Evidence"}),
        "HAS_SOURCE": ({"Evidence"}, {"Source"}),
        "DERIVED_FROM": ({"Evidence"}, {"Observation"}),
        "DEPENDS_ON": ({"Claim"}, {"Claim", "Context", "Concept"}),
        "CONFLICTS_WITH": ({"Claim"}, {"Claim"}),
        "SUPERSEDES": ({"Claim"}, {"Claim"}),
        "EXPLAINED_BY": ({"Claim"}, {"Claim"}),
        "STRENGTHENED_BY": ({"Claim"}, {"Claim"}),
        "WHEN": ({"PreferenceRule"}, {"Context"}),
        "PREFERS": ({"PreferenceRule"}, {"Claim"}),
        "OVER": ({"PreferenceRule"}, {"Claim"}),
    }
    assert len(RelationType) == len(RELATION_RULES) == 17
    assert set(expected) == {item.value for item in RelationType}
    for relation, (source_types, target_types) in expected.items():
        rule = RELATION_RULES[RelationType(relation)]
        assert {item.value for item in rule.source_types} == source_types
        assert {item.value for item in rule.target_types} == target_types


def test_request_json_schemas_expose_fixed_enums() -> None:
    candidate_schema = json.dumps(SearchClaimCandidatesRequest.model_json_schema())
    edge_schema = json.dumps(AddEdgeOperation.model_json_schema())
    assert all(node_type.value in candidate_schema for node_type in NodeType)
    assert all(relation.value in edge_schema for relation in RelationType)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "operation": "add_edge",
            "source": {"node_id": "clm_a"},
            "relation": "RELATED_TO",
            "target": {"node_id": "clm_b"},
        },
        {
            "operation": "create_node",
            "node": {
                "node_type": "ArbitraryLabel",
                "client_ref": "new-1",
                "name": "bad",
            },
        },
        {
            "operation": "create_node",
            "node": {
                "node_type": "Claim",
                "client_ref": "new-1",
                "id": "client-chosen-server-id",
                "claim_kind": "interest",
                "statement": "軽量な商品を好む",
            },
        },
    ],
)
def test_mutation_operations_reject_arbitrary_relation_label_or_server_id(
    payload: dict[str, object],
) -> None:
    model = AddEdgeOperation if payload["operation"] == "add_edge" else CreateNodeOperation
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    "extra",
    [
        {"subject_id": "client-subject"},
        {"cypher": "MATCH (n) DETACH DELETE n"},
        {"unexpected": "value"},
    ],
)
def test_preview_rejects_subject_cypher_and_extra_fields(extra: dict[str, str]) -> None:
    payload = _preview_payload()
    payload.update(extra)
    with pytest.raises(ValidationError):
        PreviewMutationRequest.model_validate(payload)


def test_canonical_key_and_preview_hash_are_deterministic() -> None:
    left = canonical_key(
        subject_id="local-default",
        node_type=NodeType.CLAIM,
        kind="interest",
        subject="  Ｌight   Weight ",
        concepts=["portable", "display"],
        contexts=["outside"],
        polarity="positive",
    )
    right = canonical_key(
        subject_id="local-default",
        node_type=NodeType.CLAIM,
        kind="INTEREST",
        subject="light weight",
        concepts=["display", "portable"],
        contexts=["outside"],
        polarity="POSITIVE",
    )
    assert left == right
    assert left != canonical_key(
        subject_id="another-subject",
        node_type=NodeType.CLAIM,
        kind="interest",
        subject="light weight",
        concepts=["display", "portable"],
        contexts=["outside"],
        polarity="positive",
    )
    assert memory_preview_hash({"b": 2, "a": 1}) == memory_preview_hash({"a": 1, "b": 2})
    assert memory_preview_hash({"a": 1}).startswith("sha256:")


def test_privacy_filter_rejects_secrets_cards_sensitive_data_and_transcripts() -> None:
    assert privacy_violations("password=do-not-store") == ["credential"]
    assert "payment_card" in privacy_violations("4111 1111 1111 1111")
    assert "sensitive_attribute" in privacy_violations("political preference")
    assert "possible_full_transcript" in privacy_violations("\n".join(["line"] * 10))
    with pytest.raises(MemoryError) as caught:
        validate_privacy(["api_key=secret"])
    assert caught.value.kind == MemoryErrorKind.PRIVACY_VIOLATION
    validate_privacy(["持ち運び時は軽さを優先する"])


def test_confidence_caps_and_adjustment() -> None:
    assert cap_confidence(0.99, EvidenceKind.EXPLICIT_STATEMENT) == 0.95
    assert cap_confidence(0.99, EvidenceKind.USER_CORRECTION) == 0.99
    assert cap_confidence(0.90, EvidenceKind.SEARCH_OBSERVATION) == 0.35
    assert adjust_confidence(0.9, []) == 0
    assert adjust_confidence(
        0.9,
        [EvidenceKind.EXPLICIT_STATEMENT],
        contradicting_count=1,
    ) == 0.45


def test_reciprocal_rank_fusion_is_deterministic_and_deduplicates() -> None:
    result = reciprocal_rank_fusion(
        {
            "full_text": ["claim-a", "claim-b", "claim-a"],
            "graph": ["claim-b", "claim-a"],
        }
    )
    assert [item_id for item_id, _ in result] == ["claim-a", "claim-b"]
    assert result[0][1] == result[1][1]
    with pytest.raises(ValueError):
        reciprocal_rank_fusion({}, k=0)


def test_domain_range_self_loop_and_cycles() -> None:
    validate_relation(RelationType.TARGETS, NodeType.CLAIM, NodeType.CONCEPT)
    with pytest.raises(MemoryError) as domain_error:
        validate_relation(RelationType.TARGETS, NodeType.CLAIM, NodeType.CONTEXT)
    assert domain_error.value.kind == MemoryErrorKind.DOMAIN_RANGE_VIOLATION

    with pytest.raises(MemoryError):
        validate_self_loop(RelationType.CONFLICTS_WITH, "clm_a", "clm_a")

    for relation in (RelationType.DEPENDS_ON, RelationType.SUPERSEDES):
        with pytest.raises(MemoryError) as cycle_error:
            validate_cycle(
                [("clm_b", relation, "clm_a")],
                relation=relation,
                source_id="clm_a",
                target_id="clm_b",
            )
        assert cycle_error.value.kind == MemoryErrorKind.CYCLE_DETECTED


def test_conflict_symmetry_is_normalized() -> None:
    assert normalize_conflict_endpoints("clm_z", "clm_a") == ("clm_a", "clm_z")
    assert normalize_conflicts(
        [
            ("clm_z", RelationType.CONFLICTS_WITH, "clm_a"),
            ("clm_a", RelationType.CONFLICTS_WITH, "clm_z"),
        ]
    ) == [("clm_a", RelationType.CONFLICTS_WITH, "clm_z")]


def test_preference_rule_completeness_and_reverse_conflict() -> None:
    with pytest.raises(MemoryError):
        validate_preference_rule([(RelationType.WHEN, "ctx_mobile")])

    complete = [
        (RelationType.WHEN, "ctx_mobile"),
        (RelationType.PREFERS, "clm_light"),
        (RelationType.OVER, "clm_large"),
        (RelationType.SUPPORTED_BY, "evd_1"),
    ]
    validate_preference_rule(complete, status=NodeStatus.ACTIVE)

    with pytest.raises(MemoryError) as conflict:
        validate_preference_rule_conflicts(
            context_ids=["ctx_mobile"],
            prefers_ids=["clm_light"],
            over_ids=["clm_large"],
            existing_rules=[(["ctx_mobile"], ["clm_large"], ["clm_light"])],
        )
    assert conflict.value.kind == MemoryErrorKind.VALIDATION_ERROR


def test_preference_graph_rejects_unbounded_full_graph_request() -> None:
    with pytest.raises(ValidationError):
        PreferenceGraphRequest.model_validate({})
    request = PreferenceGraphRequest(root_node_ids=["clm_light"])
    assert request.max_nodes == 50
    assert request.max_edges == 100


def test_preview_accepts_spec_payload() -> None:
    request = PreviewMutationRequest.model_validate(_preview_payload())
    assert request.base_revision == 184
    assert request.operations[0].target_node_id == "rule_mobile_portability"
    assert request.operations[0].evidence.source.source_ref == "current-message"


def test_apply_requires_literal_true_confirmation() -> None:
    valid = {
        "mutation_id": "mut_01J",
        "preview_hash": f"sha256:{'a' * 64}",
        "confirmation": True,
    }
    assert ApplyMutationRequest.model_validate(valid).confirmation is True
    with pytest.raises(ValidationError):
        ApplyMutationRequest.model_validate({**valid, "confirmation": False})
    with pytest.raises(ValidationError):
        ApplyMutationRequest.model_validate({key: value for key, value in valid.items() if key != "confirmation"})


def _preview_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "base_revision": 184,
        "context_snapshot_id": "snap_184_01",
        "idempotency_key": "client-generated-uuid",
        "operations": [
            {
                "operation": "add_evidence",
                "target_node_id": "rule_mobile_portability",
                "evidence": {
                    "client_ref": "evidence-1",
                    "evidence_kind": "explicit_statement",
                    "summary": "持ち運び時は画面サイズより軽さを優先すると明示した",
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
