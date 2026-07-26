from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.error import HTTPError
import urllib.request

from ._http import get_json
from .types import QuotaSnapshot

DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"


def _status_snapshot(status: str, captured_at: int, raw: dict[str, Any]) -> QuotaSnapshot:
    return QuotaSnapshot("deepseek", "default", "balance", "DeepSeek Balance", None, None, None, captured_at, "deepseek_api", status, raw,
                         balance_state="error")


def collect_deepseek_api_snapshots(
    *,
    opener=urllib.request.urlopen,
    now: Optional[float] = None,
    timeout: float = 15.0,
) -> list[QuotaSnapshot]:
    captured_at = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return []

    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    try:
        payload = get_json(DEEPSEEK_BALANCE_URL, headers, opener, timeout)
    except HTTPError as exc:
        status = "stale_token" if exc.code in {401, 403} else "fetch_error"
        return [_status_snapshot(status, captured_at, {"error": f"HTTP {exc.code}: {exc.reason}"})]
    except Exception as exc:
        return [_status_snapshot("fetch_error", captured_at, {"error": str(exc)})]

    # Parse balance_infos[0]
    balance_infos = payload.get("balance_infos")
    if not isinstance(balance_infos, list) or not balance_infos:
        return [_status_snapshot("fetch_error", captured_at, {"error": "no balance_infos in response", "raw": payload})]

    info = balance_infos[0]
    if not isinstance(info, dict):
        return [_status_snapshot("fetch_error", captured_at, {"error": "balance_infos[0] is not a dict", "raw": payload})]

    total_balance = info.get("total_balance")
    topped_up_balance = info.get("topped_up_balance")
    currency = info.get("currency", "CNY")

    if total_balance is None:
        return [_status_snapshot("fetch_error", captured_at, {"error": "total_balance missing", "raw": payload})]

    # Build status string: "ok 5.23 CNY (top-up: 5.00)"
    parts = [f"ok {total_balance} {currency}"]
    if topped_up_balance is not None:
        parts.append(f"(top-up: {topped_up_balance})")
    status = " ".join(parts)
    return [
        QuotaSnapshot(
            "deepseek",
            "default",
            "balance",
            "DeepSeek Balance",
            None,           # used_percent
            None,           # resets_at
            None,           # plan
            captured_at,
            "deepseek_api",
            status,
            payload,
            unit="usd",
            amount_remaining=total_balance,
            amount_granted=topped_up_balance or total_balance,
            source_type="api",
            balance_state="fresh",
        )
    ]
