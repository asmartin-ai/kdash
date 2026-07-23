from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.error import HTTPError
import urllib.request

from .types import QuotaSnapshot

DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"


def _status_snapshot(status: str, captured_at: int, raw: dict[str, Any]) -> QuotaSnapshot:
    return QuotaSnapshot("deepseek", "default", "balance", "DeepSeek Balance", None, None, None, captured_at, "deepseek_api", status, raw)


def _get_json(url: str, headers: dict[str, str], opener, timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers)
    last_error: HTTPError | None = None
    for attempt in range(2):
        try:
            with opener(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {500, 502, 503, 504} or attempt == 1:
                raise
            time.sleep(0.2)
    assert last_error is not None
    raise last_error


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
        payload = _get_json(DEEPSEEK_BALANCE_URL, headers, opener, timeout)
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
        )
    ]
