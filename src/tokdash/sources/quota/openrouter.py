from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
import urllib.request

from .types import QuotaSnapshot

OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
OPENROUTER_CREDITS_URL = "https://openrouter.ai/api/v1/credits"


def _status_snapshot(status: str, captured_at: int, raw: dict[str, Any], plan: str | None = None) -> QuotaSnapshot:
    return QuotaSnapshot(
        "openrouter",
        "default",
        "api",
        "OpenRouter API",
        None,
        None,
        plan,
        captured_at,
        "openrouter_api",
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
            # Mirror clinepass/zenmux: retry once on 5xx server hiccups; 4xx (401/403 auth,
            # 429 rate-limit) is reported as-is so the user sees stale_token/fetch_error
            # instead of burning a 200 ms sleep on a problem that won't fix itself.
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 1:
                raise
            time.sleep(0.2)
    assert last_error is not None
    raise last_error


def collect_openrouter_api_snapshots(
    *,
    opener=urllib.request.urlopen,
    now: int | None = None,
    timeout: float = 15.0,
) -> list[QuotaSnapshot]:
    captured_at = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return [
            _status_snapshot(
                "unavailable",
                captured_at,
                {"error": "OPENROUTER_API_KEY unset"},
            )
        ]

    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}

    try:
        key_payload = _get_json(OPENROUTER_KEY_URL, headers, opener, timeout)
        credits_payload = _get_json(OPENROUTER_CREDITS_URL, headers, opener, timeout)
    except HTTPError as exc:
        status = "stale_token" if exc.code in {401, 403} else "fetch_error"
        return [_status_snapshot(status, captured_at, {"error": f"HTTP {exc.code}: {exc.reason}"})]
    except Exception as exc:
        return [_status_snapshot("fetch_error", captured_at, {"error": str(exc)})]

    kd = key_payload.get("data") if isinstance(key_payload.get("data"), dict) else {}
    cd = credits_payload.get("data") if isinstance(credits_payload.get("data"), dict) else {}

    is_free_tier = bool(kd.get("is_free_tier"))
    plan_label = "free tier" if is_free_tier else "paid"

    total_credits = cd.get("total_credits")
    total_usage = cd.get("total_usage")

    try:
        total = float(total_credits) if total_credits is not None else 0.0
    except Exception:
        total = 0.0
    try:
        used = float(total_usage) if total_usage is not None else 0.0
    except Exception:
        used = 0.0

    used_percent: float | None = None
    if total > 0:
        used_percent = round(100.0 * used / total, 4)

    raw: dict[str, Any] = {
        "is_free_tier": is_free_tier,
        "limit": kd.get("limit"),
        "limit_remaining": kd.get("limit_remaining"),
        "total_credits": total_credits,
        "total_usage": total_usage,
    }

    return [
        QuotaSnapshot(
            "openrouter",
            "default",
            "credits",
            "credits",
            used_percent,
            None,
            plan_label,
            captured_at,
            "openrouter_api",
            "ok",
            raw,
        )
    ]
