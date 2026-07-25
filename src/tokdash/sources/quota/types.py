from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class QuotaSnapshot:
    provider: str
    account: str
    bucket: str
    bucket_label: str
    used_percent: float | None
    resets_at: int | None
    plan: str | None
    captured_at: int
    source: str
    status: str
    raw: dict[str, Any]
    expires_at: int | None = None  # subscription/trial end (Unix timestamp)
    unit: str | None = None               # "usd" | "native" | "opaque"
    amount_remaining: float | None = None  # remaining balance in unit
    amount_granted: float | None = None    # total granted balance in unit
    source_type: str | None = None         # "api" | "manual" | "inferred"
    balance_state: str | None = None       # "fresh" | "stale" | "unsupported" | "error" | "manual"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
