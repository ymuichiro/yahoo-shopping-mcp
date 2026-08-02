from __future__ import annotations

from collections.abc import Iterable

from .enums import EvidenceKind

CONFIDENCE_CAPS: dict[EvidenceKind, float] = {
    EvidenceKind.USER_CORRECTION: 1.00,
    EvidenceKind.EXPLICIT_STATEMENT: 0.95,
    EvidenceKind.PURCHASE_OBSERVATION: 0.90,
    EvidenceKind.REPEATED_BEHAVIOR: 0.80,
    EvidenceKind.IMPORTED_RECORD: 0.75,
    EvidenceKind.COMPARISON_OBSERVATION: 0.60,
    EvidenceKind.SEARCH_OBSERVATION: 0.35,
}


def confidence_cap(evidence_kind: EvidenceKind) -> float:
    return CONFIDENCE_CAPS[evidence_kind]


def cap_confidence(proposed: float, evidence_kind: EvidenceKind) -> float:
    return min(max(float(proposed), 0.0), confidence_cap(evidence_kind))


def adjust_confidence(
    proposed: float,
    evidence_kinds: Iterable[EvidenceKind],
    *,
    contradicting_count: int = 0,
    age_days: float = 0,
) -> float:
    kinds = tuple(evidence_kinds)
    if not kinds:
        return 0.0
    capped = min(max(float(proposed), 0.0), max(confidence_cap(kind) for kind in kinds))
    contradiction_factor = 1 / (1 + max(contradicting_count, 0))
    age_factor = 1 / (1 + max(age_days, 0.0) / 365)
    return round(capped * contradiction_factor * age_factor, 6)
