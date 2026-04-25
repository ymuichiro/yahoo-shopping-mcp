from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class YahooShoppingError(Exception):
    kind: str
    message: str
    retryable: bool = False
    http_status: int | None = None
    provider_code: str | None = None
    details: dict[str, Any] | None = None

    def to_response(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "retryable": self.retryable,
            "http_status": self.http_status,
            "provider_code": self.provider_code,
            "details": self.details or {},
        }
