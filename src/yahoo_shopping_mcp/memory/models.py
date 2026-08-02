from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from .enums import (
    ClaimKind,
    ConceptKind,
    EvidenceKind,
    MutationOperation,
    NodeStatus,
    NodeType,
    RelationType,
    SourceKind,
)
from .validation import validate_privacy

Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$",
    ),
]
ClientReference = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$",
    ),
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
SpaceKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
]


class MemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)


class RouteMemorySpacesRequest(MemoryModel):
    query: ShortText
    task: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = None
    limit: int = Field(default=5, ge=1, le=50)


class SearchClaimCandidatesRequest(MemoryModel):
    query: ShortText
    space_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    task: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = None
    node_types: list[NodeType] = Field(
        default_factory=lambda: [NodeType.CLAIM, NodeType.PREFERENCE_RULE, NodeType.CONTEXT],
        min_length=1,
        max_length=len(NodeType),
    )
    status: list[NodeStatus] = Field(default_factory=lambda: [NodeStatus.ACTIVE], min_length=1, max_length=5)
    limit: int = Field(default=20, ge=1, le=100)


class ClaimNeighborhoodRequest(MemoryModel):
    root_node_ids: list[Identifier] = Field(min_length=1, max_length=30)
    relations: list[RelationType] = Field(
        default_factory=lambda: list(RelationType),
        min_length=1,
        max_length=len(RelationType),
    )
    max_depth: int = Field(default=2, ge=1, le=3)
    max_nodes: int = Field(default=50, ge=1, le=100)
    max_edges: int = Field(default=100, ge=1, le=250)
    include_evidence_summary: bool = True


class PreferenceGraphRequest(MemoryModel):
    root_node_ids: list[Identifier] = Field(default_factory=list, max_length=30)
    space_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    relations: list[RelationType] = Field(
        default_factory=lambda: list(RelationType),
        min_length=1,
        max_length=len(RelationType),
    )
    status: list[NodeStatus] = Field(default_factory=lambda: [NodeStatus.ACTIVE], min_length=1, max_length=5)
    max_depth: int = Field(default=2, ge=1, le=3)
    max_nodes: int = Field(default=50, ge=1, le=100)
    max_edges: int = Field(default=100, ge=1, le=250)
    include_evidence_summary: bool = True

    @model_validator(mode="after")
    def reject_full_graph_read(self) -> PreferenceGraphRequest:
        if not (self.root_node_ids or self.space_ids):
            raise ValueError("At least one root_node_id or space_id is required.")
        return self


class ExportMemoryRequest(MemoryModel):
    cursor: Identifier | None = None
    limit: int = Field(default=100, ge=1, le=100)
    status: list[NodeStatus] = Field(
        default_factory=lambda: [
            NodeStatus.ACTIVE,
            NodeStatus.RETIRED,
            NodeStatus.SUPERSEDED,
        ],
        min_length=1,
        max_length=5,
    )
    include_evidence_summary: bool = True
    format: Literal["json"] = "json"


class DeleteMemoryRequest(MemoryModel):
    scope: Literal["nodes", "source", "all"]
    node_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    source_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    mode: Literal["retire", "delete"] = "retire"
    confirmation: Literal[True]
    idempotency_key: ClientReference

    @model_validator(mode="after")
    def validate_scope(self) -> DeleteMemoryRequest:
        if self.scope == "nodes" and (not self.node_ids or self.source_ids):
            raise ValueError("nodes scope requires only node_ids.")
        if self.scope == "source" and (not self.source_ids or self.node_ids):
            raise ValueError("source scope requires only source_ids.")
        if self.scope == "all" and (self.node_ids or self.source_ids):
            raise ValueError("all scope does not accept node_ids or source_ids.")
        return self


class NodeReference(MemoryModel):
    node_id: Identifier | None = None
    client_ref: ClientReference | None = None

    @model_validator(mode="after")
    def exactly_one_reference(self) -> NodeReference:
        if (self.node_id is None) == (self.client_ref is None):
            raise ValueError("Exactly one of node_id or client_ref is required.")
        return self


class NewClaim(MemoryModel):
    node_type: Literal[NodeType.CLAIM] = NodeType.CLAIM
    client_ref: ClientReference
    claim_kind: ClaimKind
    statement: ShortText
    status: Literal[NodeStatus.DRAFT, NodeStatus.ACTIVE] = NodeStatus.DRAFT
    confidence: float | None = Field(default=None, ge=0, le=1)
    observed_at: AwareDatetime | None = None
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None
    canonical_key_candidate: Annotated[str, StringConstraints(max_length=250)] | None = None

    @model_validator(mode="after")
    def validate_validity_window(self) -> NewClaim:
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise ValueError("valid_from must not be after valid_until.")
        return self


class NewConcept(MemoryModel):
    node_type: Literal[NodeType.CONCEPT] = NodeType.CONCEPT
    client_ref: ClientReference
    concept_kind: ConceptKind
    name: Name
    aliases: list[Name] = Field(default_factory=list, max_length=20)
    canonical_key_candidate: Annotated[str, StringConstraints(max_length=250)] | None = None


class NewContext(MemoryModel):
    node_type: Literal[NodeType.CONTEXT] = NodeType.CONTEXT
    client_ref: ClientReference
    name: Name
    summary: ShortText | None = None


class NewMemorySpace(MemoryModel):
    node_type: Literal[NodeType.MEMORY_SPACE] = NodeType.MEMORY_SPACE
    client_ref: ClientReference
    space_key: SpaceKey
    name: Name
    summary: ShortText
    keywords: list[Name] = Field(default_factory=list, max_length=30)


class NewPreferenceRule(MemoryModel):
    node_type: Literal[NodeType.PREFERENCE_RULE] = NodeType.PREFERENCE_RULE
    client_ref: ClientReference
    summary: ShortText
    status: Literal[NodeStatus.DRAFT, NodeStatus.ACTIVE] = NodeStatus.DRAFT
    confidence: float | None = Field(default=None, ge=0, le=1)


class NewEvidence(MemoryModel):
    node_type: Literal[NodeType.EVIDENCE] = NodeType.EVIDENCE
    client_ref: ClientReference
    evidence_kind: EvidenceKind
    summary: ShortText
    observed_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    source_locator: Annotated[str, StringConstraints(max_length=200)] | None = None

    @model_validator(mode="after")
    def validate_expiry(self) -> NewEvidence:
        if self.expires_at and self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be after observed_at.")
        return self


class NewSource(MemoryModel):
    node_type: Literal[NodeType.SOURCE] = NodeType.SOURCE
    client_ref: ClientReference
    source_kind: SourceKind
    source_ref: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    source_created_at: AwareDatetime | None = None
    retention_policy: Annotated[str, StringConstraints(min_length=1, max_length=80)] | None = None


class NewObservation(MemoryModel):
    node_type: Literal[NodeType.OBSERVATION] = NodeType.OBSERVATION
    client_ref: ClientReference
    summary: ShortText
    product_category: Name | None = None
    filters: list[ShortText] = Field(default_factory=list, max_length=20)
    compared_product_ids: list[Identifier] = Field(default_factory=list, max_length=30)
    observed_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_expiry(self) -> NewObservation:
        if self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be after observed_at.")
        return self


NewNode = Annotated[
    NewClaim
    | NewConcept
    | NewContext
    | NewMemorySpace
    | NewPreferenceRule
    | NewEvidence
    | NewSource
    | NewObservation,
    Field(discriminator="node_type"),
]


class ClaimUpdate(MemoryModel):
    node_type: Literal[NodeType.CLAIM] = NodeType.CLAIM
    confidence: float | None = Field(default=None, ge=0, le=1)
    observed_at: AwareDatetime | None = None
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None


class ConceptUpdate(MemoryModel):
    node_type: Literal[NodeType.CONCEPT] = NodeType.CONCEPT
    name: Name | None = None
    aliases: list[Name] | None = Field(default=None, max_length=20)


class ContextUpdate(MemoryModel):
    node_type: Literal[NodeType.CONTEXT] = NodeType.CONTEXT
    name: Name | None = None
    summary: ShortText | None = None


class MemorySpaceUpdate(MemoryModel):
    node_type: Literal[NodeType.MEMORY_SPACE] = NodeType.MEMORY_SPACE
    name: Name | None = None
    summary: ShortText | None = None
    keywords: list[Name] | None = Field(default=None, max_length=30)


class PreferenceRuleUpdate(MemoryModel):
    node_type: Literal[NodeType.PREFERENCE_RULE] = NodeType.PREFERENCE_RULE
    summary: ShortText | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class EvidenceUpdate(MemoryModel):
    node_type: Literal[NodeType.EVIDENCE] = NodeType.EVIDENCE
    summary: ShortText | None = None
    observed_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None


class SourceUpdate(MemoryModel):
    node_type: Literal[NodeType.SOURCE] = NodeType.SOURCE
    retention_policy: Annotated[str, StringConstraints(min_length=1, max_length=80)] | None = None


class ObservationUpdate(MemoryModel):
    node_type: Literal[NodeType.OBSERVATION] = NodeType.OBSERVATION
    summary: ShortText | None = None
    expires_at: AwareDatetime | None = None


NodeUpdate = Annotated[
    ClaimUpdate
    | ConceptUpdate
    | ContextUpdate
    | MemorySpaceUpdate
    | PreferenceRuleUpdate
    | EvidenceUpdate
    | SourceUpdate
    | ObservationUpdate,
    Field(discriminator="node_type"),
]


class CreateNodeOperation(MemoryModel):
    operation: Literal[MutationOperation.CREATE_NODE] = MutationOperation.CREATE_NODE
    node: NewNode


class UpdateNodePropertiesOperation(MemoryModel):
    operation: Literal[MutationOperation.UPDATE_NODE_PROPERTIES] = (
        MutationOperation.UPDATE_NODE_PROPERTIES
    )
    target_node_id: Identifier
    expected_revision: int | None = Field(default=None, ge=0)
    update: NodeUpdate

    @model_validator(mode="after")
    def require_property(self) -> UpdateNodePropertiesOperation:
        if self.update.model_fields_set <= {"node_type"}:
            raise ValueError("At least one mutable property is required.")
        return self


class AddEdgeOperation(MemoryModel):
    operation: Literal[MutationOperation.ADD_EDGE] = MutationOperation.ADD_EDGE
    source: NodeReference
    relation: RelationType
    target: NodeReference


class RemoveEdgeOperation(MemoryModel):
    operation: Literal[MutationOperation.REMOVE_EDGE] = MutationOperation.REMOVE_EDGE
    source_node_id: Identifier
    relation: RelationType
    target_node_id: Identifier


class EvidenceSourceInput(MemoryModel):
    client_ref: ClientReference
    source_kind: SourceKind
    source_ref: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    source_created_at: AwareDatetime | None = None
    retention_policy: Annotated[str, StringConstraints(min_length=1, max_length=80)] | None = None


class EvidenceInput(MemoryModel):
    client_ref: ClientReference
    evidence_kind: EvidenceKind
    summary: ShortText
    observed_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    source: EvidenceSourceInput

    @model_validator(mode="after")
    def validate_expiry(self) -> EvidenceInput:
        if self.expires_at and self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be after observed_at.")
        return self


class AddEvidenceOperation(MemoryModel):
    operation: Literal[MutationOperation.ADD_EVIDENCE] = MutationOperation.ADD_EVIDENCE
    target_node_id: Identifier | None = None
    target_client_ref: ClientReference | None = None
    evidence: EvidenceInput
    relation: Literal[RelationType.SUPPORTED_BY, RelationType.CONTRADICTED_BY] = (
        RelationType.SUPPORTED_BY
    )

    @model_validator(mode="after")
    def exactly_one_target(self) -> AddEvidenceOperation:
        if (self.target_node_id is None) == (self.target_client_ref is None):
            raise ValueError("Exactly one of target_node_id or target_client_ref is required.")
        return self


class RetireNodeOperation(MemoryModel):
    operation: Literal[MutationOperation.RETIRE_NODE] = MutationOperation.RETIRE_NODE
    target_node_id: Identifier
    expected_revision: int | None = Field(default=None, ge=0)


class SupersedeClaimOperation(MemoryModel):
    operation: Literal[MutationOperation.SUPERSEDE_CLAIM] = MutationOperation.SUPERSEDE_CLAIM
    old_claim_id: Identifier
    replacement: NewClaim
    evidence: EvidenceInput


class AssignSpaceOperation(MemoryModel):
    operation: Literal[MutationOperation.ASSIGN_SPACE] = MutationOperation.ASSIGN_SPACE
    node: NodeReference
    space: NodeReference


class RemoveSpaceAssignmentOperation(MemoryModel):
    operation: Literal[MutationOperation.REMOVE_SPACE_ASSIGNMENT] = (
        MutationOperation.REMOVE_SPACE_ASSIGNMENT
    )
    node_id: Identifier
    space_id: Identifier


MutationOperationInput = Annotated[
    CreateNodeOperation
    | UpdateNodePropertiesOperation
    | AddEdgeOperation
    | RemoveEdgeOperation
    | AddEvidenceOperation
    | RetireNodeOperation
    | SupersedeClaimOperation
    | AssignSpaceOperation
    | RemoveSpaceAssignmentOperation,
    Field(discriminator="operation"),
]


class PreviewMutationRequest(MemoryModel):
    schema_version: Literal["1.0"] = "1.0"
    base_revision: int = Field(ge=0)
    context_snapshot_id: Identifier
    idempotency_key: ClientReference
    operations: list[MutationOperationInput] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def enforce_privacy(self) -> PreviewMutationRequest:
        validate_privacy(_strings(self.operations))
        return self


class ApplyMutationRequest(MemoryModel):
    mutation_id: Identifier
    preview_hash: Annotated[
        str,
        StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
    ]
    confirmation: Literal[True]


GetPreferenceGraphRequest = PreferenceGraphRequest


def _strings(value: object) -> list[str]:
    if isinstance(value, BaseModel):
        return _strings(value.model_dump(mode="python", exclude_none=True))
    if isinstance(value, dict):
        return [item for child in value.values() for item in _strings(child)]
    if isinstance(value, (list, tuple)):
        return [item for child in value for item in _strings(child)]
    return [value] if isinstance(value, str) else []
