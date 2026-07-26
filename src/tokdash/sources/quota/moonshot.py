from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
import urllib.request

from ._http import get_json
from .types import QuotaSnapshot

MOONSHOT_BALANCE_URL = "https://api.moonshot.ai/v1/users/me/balance"
MOONSHOT_MODELS_URL = "https://api.moonshot.ai/v1/models"


def _status_snapshot(status: str, captured_at: int, raw: dict[str, Any]) -> QuotaSnapshot:
    return QuotaSnapshot(
        "moonshot",
        "default",
        "balance",
        "balance",
        None,
        None,
        None,
        captured_at,
        "moonshot_api",
        status,
        raw,
        balance_state="error",
    )


def collect_moonshot_api_snapshots(
    *,
    opener=urllib.request.urlopen,
    now: float | None = None,
    timeout: float = 15.0,
) -> list[QuotaSnapshot]:
    captured_at = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    key = os.environ.get("MOONSHOT_API_KEY", "").strip()
    if not key:
        return [
            _status_snapshot(
                "unavailable",
                captured_at,
                {"error": "MOONSHOT_API_KEY unset"},
            )
        ]

    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}

    try:
        balance_payload = get_json(MOONSHOT_BALANCE_URL, headers, opener, timeout)
        models_payload = get_json(MOONSHOT_MODELS_URL, headers, opener, timeout)
    except HTTPError as exc:
        status = "stale_token" if exc.code in {401, 403} else "fetch_error"
        return [_status_snapshot(status, captured_at, {"error": f"HTTP {exc.code}: {exc.reason}"})]
    except Exception as exc:
        return [_status_snapshot("fetch_error", captured_at, {"error": str(exc)})]

    balance_data = balance_payload.get("data") if isinstance(balance_payload.get("data"), dict) else {}
    try:
        available_balance = float(balance_data.get("available_balance", 0) or 0)
    except (TypeError, ValueError):
        available_balance = 0.0
    try:
        cash_balance = float(balance_data.get("cash_balance", 0) or 0)
    except (TypeError, ValueError):
        cash_balance = 0.0
    try:
        voucher_balance = float(balance_data.get("voucher_balance", 0) or 0)
    except (TypeError, ValueError):
        voucher_balance = 0.0

    models_root = models_payload.get("data")
    raw_models = models_root if isinstance(models_root, list) else (
        models_payload.get("models") if isinstance(models_payload.get("models"), list) else []
    )

    def _model_id(m: Any) -> str:
        if isinstance(m, dict):
            return str(m.get("id") or m.get("name") or "")
        return str(m) if m is not None else ""

    model_ids = [_model_id(m) for m in raw_models]
    has_kimi_k3 = any("kimi-k3" in mid.lower() for mid in model_ids if mid)
    has_models = bool(model_ids)

    if has_kimi_k3:
        status = "k3 live"
    elif available_balance <= 0:
        status = "EMPTY"
    elif has_models:
        status = "up"
    else:
        status = "wallet"

    raw = {
        "balance": balance_payload,
        "models": models_payload,
        "available_balance": available_balance,
        "cash_balance": cash_balance,
        "voucher_balance": voucher_balance,
        "model_count": len(model_ids),
        "has_kimi_k3": has_kimi_k3,
    }
    return [
        QuotaSnapshot(
            "moonshot",
            "default",
            "balance",
            "balance",
            None,
            None,
            None,
            captured_at,
            "moonshot_api",
            status,
            raw,
            unit="usd",
            amount_remaining=available_balance,
            amount_granted=cash_balance,
            source_type="api",
            balance_state="fresh",
        )
    ]
