from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
import urllib.request
import time

from .codex import _parse_time
from .types import QuotaSnapshot

ZAI_USAGE_URL = "https://api.z.ai/api/monitor/usage/quota/limit"

# Z.ai's auth scheme is unusual: the raw key is sent as the Authorization header value
# with NO "Bearer " prefix (probed 2026-07-22 — see glance.py's "raw token, no Bearer"
# comment). Mirroring that here so a configured ZAI_API_KEY works against the real API.
_PLAN_LABEL = "Coding Plan"


def _status_snapshot(status: str, captured_at: int, raw: dict[str, Any]) -> QuotaSnapshot:
    return QuotaSnapshot("zai", "default", "api", "Z.ai GLM API", None, None, _PLAN_LABEL, captured_at, "zai_api", status, raw)


def _bucket_for_limit(limit: dict[str, Any]) -> tuple[str, str]:
    typ = str(limit.get("type") or "")
    unit = limit.get("unit")
    number = limit.get("number")
    if typ == "TOKENS_LIMIT" and unit == 3 and number == 5:
        return "5h_tokens", "5h tokens"
    if typ == "TOKENS_LIMIT" and unit == 6 and number == 1:
        return "weekly_tokens", "weekly tokens"
    if typ == "TIME_LIMIT":
        return "mcp_monthly", "MCP monthly"
    return f"{typ}:{unit}x{number}", f"{typ}:{unit}x{number}"


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
            # Mirror claude.py: retry once on 5xx; 4xx (401/403 auth, 429 rate-limit)
            # surfaces as-is so the user sees a stale_token/fetch_error banner instead of
            # burning a 200 ms sleep on a problem that won't fix itself in 200 ms.
            if exc.code not in {500, 502, 503, 504} or attempt == 1:
                raise
            time.sleep(0.2)
    assert last_error is not None
    raise last_error


def collect_zai_api_snapshots(
    *,
    opener=urllib.request.urlopen,
    now: int | None = None,
    timeout: float = 15.0,
) -> list[QuotaSnapshot]:
    captured_at = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    key = os.environ.get("ZAI_API_KEY", "").strip()
    if not key:
        return [
            _status_snapshot(
                "unavailable",
                captured_at,
                {"error": "ZAI_API_KEY unset"},
            )
        ]

    # Raw token, no Bearer prefix — see module docstring note.
    headers = {
        "Authorization": key,
        "Accept-Language": "en-US,en",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        payload = _get_json(ZAI_USAGE_URL, headers, opener, timeout)
    except HTTPError as exc:
        status = "stale_token" if exc.code in {401, 403} else "fetch_error"
        return [_status_snapshot(status, captured_at, {"error": f"HTTP {exc.code}: {exc.reason}"})]
    except Exception as exc:
        return [_status_snapshot("fetch_error", captured_at, {"error": str(exc)})]

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    raw_limits = data.get("limits") if isinstance(data.get("limits"), list) else []
    out: list[QuotaSnapshot] = []
    for limit in raw_limits:
        if not isinstance(limit, dict):
            continue
        try:
            pct = float(limit.get("percentage") or 0)
        except Exception:
            continue
        bucket, label = _bucket_for_limit(limit)
        # nextResetTime is epoch milliseconds; _parse_time detects >1e12 and divides by 1000.
        out.append(
            QuotaSnapshot(
                "zai",
                "default",
                bucket,
                label,
                round(pct, 4),
                _parse_time(limit.get("nextResetTime")),
                _PLAN_LABEL,
                captured_at,
                "zai_api",
                "ok",
                {"limit": limit},
            )
        )
    if not out:
        return [_status_snapshot("unavailable", captured_at, {"error": "no_limits", "msg": payload.get("msg")})]
    return out
