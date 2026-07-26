from enum import StrEnum


class NodeType(StrEnum):
    USER = "User"
    PROFILE = "Profile"
    MEMORY_SPACE = "MemorySpace"
    CLAIM = "Claim"
    CONCEPT = "Concept"
    CONTEXT = "Context"
    PREFERENCE_RULE = "PreferenceRule"
    EVIDENCE = "Evidence"
    SOURCE = "Source"
    OBSERVATION = "Observation"
    MEMORY_MUTATION = "MemoryMutation"


class ClaimKind(StrEnum):
    INTEREST = "interest"
    PRICE_PREFERENCE = "price_preference"
    QUALITY_PREFERENCE = "quality_preference"
    ORIGIN_PREFERENCE = "origin_preference"
    BRAND_PREFERENCE = "brand_preference"
    PRODUCT_ATTRIBUTE_PREFERENCE = "product_attribute_preference"
    PURCHASE_INTENT = "purchase_intent"
    AVOIDANCE = "avoidance"


class ConceptKind(StrEnum):
    INTEREST_TOPIC = "interest_topic"
    PRODUCT_CATEGORY = "product_category"
    PRODUCT_ATTRIBUTE = "product_attribute"
    PRICE_RANGE = "price_range"
    BRAND = "brand"
    ORIGIN = "origin"
    SELLER = "seller"
    SHIPPING_CONDITION = "shipping_condition"
    PURCHASE_TARGET = "purchase_target"
    CONSTRAINT = "constraint"


class EvidenceKind(StrEnum):
    EXPLICIT_STATEMENT = "explicit_statement"
    USER_CORRECTION = "user_correction"
    REPEATED_BEHAVIOR = "repeated_behavior"
    SEARCH_OBSERVATION = "search_observation"
    COMPARISON_OBSERVATION = "comparison_observation"
    PURCHASE_OBSERVATION = "purchase_observation"
    IMPORTED_RECORD = "imported_record"


class NodeStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class MutationStatus(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    EXPIRED = "expired"


class RelationType(StrEnum):
    HAS_PROFILE = "HAS_PROFILE"
    CONTAINS_CLAIM = "CONTAINS_CLAIM"
    BELONGS_TO = "BELONGS_TO"
    TARGETS = "TARGETS"
    APPLIES_IN = "APPLIES_IN"
    SUPPORTED_BY = "SUPPORTED_BY"
    CONTRADICTED_BY = "CONTRADICTED_BY"
    HAS_SOURCE = "HAS_SOURCE"
    DERIVED_FROM = "DERIVED_FROM"
    DEPENDS_ON = "DEPENDS_ON"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    SUPERSEDES = "SUPERSEDES"
    EXPLAINED_BY = "EXPLAINED_BY"
    STRENGTHENED_BY = "STRENGTHENED_BY"
    WHEN = "WHEN"
    PREFERS = "PREFERS"
    OVER = "OVER"


class MutationOperation(StrEnum):
    CREATE_NODE = "create_node"
    UPDATE_NODE_PROPERTIES = "update_node_properties"
    ADD_EDGE = "add_edge"
    REMOVE_EDGE = "remove_edge"
    ADD_EVIDENCE = "add_evidence"
    RETIRE_NODE = "retire_node"
    SUPERSEDE_CLAIM = "supersede_claim"
    ASSIGN_SPACE = "assign_space"
    REMOVE_SPACE_ASSIGNMENT = "remove_space_assignment"


class SourceKind(StrEnum):
    CONVERSATION = "conversation"
    SEARCH_EVENT = "search_event"
    COMPARISON_EVENT = "comparison_event"
    PURCHASE_EVENT = "purchase_event"
    MANUAL_IMPORT = "manual_import"
