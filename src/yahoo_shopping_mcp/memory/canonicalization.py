from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping, Sequence

from pydantic import BaseModel

from .enums import NodeType

_WHITESPACE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value).strip()).casefold()


def canonical_key(
    *,
    subject_id: str,
    node_type: NodeType,
    kind: str,
    subject: str = "",
    concepts: Sequence[str] = (),
    contexts: Sequence[str] = (),
    polarity: str = "",
) -> str:
    material = {
        "subject_id": normalize_text(subject_id),
        "node_type": node_type.value,
        "kind": normalize_text(kind),
        "subject": normalize_text(subject),
        "concepts": sorted({normalize_text(item) for item in concepts if item.strip()}),
        "contexts": sorted({normalize_text(item) for item in contexts if item.strip()}),
        "polarity": normalize_text(polarity),
    }
    digest = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return f"{node_type.value.lower()}:{digest}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json", exclude_none=True))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_jsonable(item) for item in value), key=repr)
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def memory_preview_hash(value: Any) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
