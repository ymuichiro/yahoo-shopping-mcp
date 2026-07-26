from __future__ import annotations

from enum import StrEnum
from typing import Any


class MemoryErrorKind(StrEnum):
    DISABLED = "memory_disabled"
    IDENTITY_UNAVAILABLE = "memory_identity_unavailable"
    VALIDATION_ERROR = "memory_validation_error"
    SCHEMA_VERSION_MISMATCH = "memory_schema_version_mismatch"
    RELATION_NOT_ALLOWED = "memory_relation_not_allowed"
    NODE_TYPE_NOT_ALLOWED = "memory_node_type_not_allowed"
    DOMAIN_RANGE_VIOLATION = "memory_domain_range_violation"
    CYCLE_DETECTED = "memory_cycle_detected"
    DUPLICATE_DETECTED = "memory_duplicate_detected"
    AMBIGUOUS_UPDATE_TARGET = "memory_ambiguous_update_target"
    REVISION_CONFLICT = "memory_revision_conflict"
    SNAPSHOT_STALE = "memory_snapshot_stale"
    MUTATION_EXPIRED = "memory_mutation_expired"
    PREVIEW_HASH_MISMATCH = "memory_preview_hash_mismatch"
    CONFIRMATION_REQUIRED = "memory_confirmation_required"
    LIMIT_EXCEEDED = "memory_limit_exceeded"
    NOT_FOUND = "memory_not_found"
    PRIVACY_VIOLATION = "memory_privacy_violation"


class MemoryError(Exception):
    def __init__(
        self,
        kind: MemoryErrorKind,
        message: str,
        *,
        retryable: bool = False,
        **details: Any,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retryable = retryable
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "message": self.message,
            **self.details,
            "retryable": self.retryable,
        }
