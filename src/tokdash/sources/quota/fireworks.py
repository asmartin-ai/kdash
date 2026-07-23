from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.error import HTTPError
import urllib.request

from .types import QuotaSnapshot

FIREWORKS_BILLING_URL = "https://api.fireworks.ai/v1/accounts/{account}/billingUsage"
_DEFAULT_ACCOUNT = "accounts/asmartin-ai"


def _status_snapshot(status: str, captured_at: int, raw: dict[str, Any]) -> QuotaSnapshot:
    return QuotaSnapshot(
        "fireworks",
        "default",
        "30d_usage",
        "Fireworks 30d Usage",
        None,
        None,
        None,
        captured_at,
        "fireworks_api",
        status,
        raw,
    )


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


def collect_fireworks_api_snapshots(
    *,
    opener=urllib.request.urlopen,
    now: Optional[float] = None,
    timeout: float = 15.0,
) -> list[QuotaSnapshot]:
    captured_at = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    key = os.environ.get("FIREWORKS_API_KEY", "").strip()
    if not key:
        return []

    # Account id may be supplied with or without the "accounts/" prefix; the billing
    # endpoint requires the prefixed form.
    acc = os.environ.get("FIREWORKS_ACCOUNT_ID", _DEFAULT_ACCOUNT).strip() or _DEFAULT_ACCOUNT
    if not acc.startswith("accounts/"):
        acc = "accounts/" + acc

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)
    start_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end.strftime("%Y-%m-%dT%H:%M:%SZ")

    url = f"{FIREWORKS_BILLING_URL.format(account=acc)}?startTime={start_iso}&endTime={end_iso}"
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    try:
        payload = _get_json(url, headers, opener, timeout)
    except HTTPError as exc:
        status = "stale_token" if exc.code in {401, 403} else "fetch_error"
        return [_status_snapshot(status, captured_at, {"error": f"HTTP {exc.code}: {exc.reason}"})]
    except Exception as exc:
        return [_status_snapshot("fetch_error", captured_at, {"error": str(exc)})]

    costs = payload.get("serverlessCosts")
    if not isinstance(costs, list):
        return [
            _status_snapshot(
                "fetch_error",
                captured_at,
                {"error": "no serverlessCosts in response", "raw": payload},
            )
        ]

    total_tokens = 0
    total_cost_usd = 0.0
    for entry in costs:
        if not isinstance(entry, dict):
            continue
        prompt = entry.get("promptTokens")
        completion = entry.get("completionTokens")
        if isinstance(prompt, (int, float)):
            total_tokens += int(prompt)
        if isinstance(completion, (int, float)):
            total_tokens += int(completion)
        cost_nano = entry.get("costNanoUsd")
        if isinstance(cost_nano, (int, float)):
            total_cost_usd += float(cost_nano) / 1e9

    status = f"ok {total_tokens} tokens, ${total_cost_usd:.6f}"
    raw: dict[str, Any] = {
        "serverlessCosts": payload,
        "aggregated": {
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost_usd,
            "startTime": start_iso,
            "endTime": end_iso,
        },
    }

    return [
        QuotaSnapshot(
            "fireworks",
            "default",
            "30d_usage",
            "Fireworks 30d Usage",
            None,           # used_percent
            None,           # resets_at
            None,           # plan
            captured_at,
            "fireworks_api",
            status,
            raw,
        )
    ]
