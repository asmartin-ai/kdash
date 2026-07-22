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

CLINEPASS_PLAN_URL = "https://api.cline.bot/api/v1/users/me/plan"
CLINEPASS_USAGE_LIMITS_URL = "https://api.cline.bot/api/v1/users/me/plan/usage-limits"
CLINEPASS_ME_URL = "https://api.cline.bot/api/v1/users/me"
# Re-enable by setting the third tuple element of ``codex.claude.clinepass_api.zai_api`` in
# ``config.QUOTA_KEYS`` (and uncommenting the antigravity branch in ``__init__.py`` /
# frontend dispatchers). ClinePass is a paid subscription plan that the user opted in to
# tracking on 2026-07-22; the antigravity branch was disabled the same day because the
# Antigravity subscription is no longer active.

_BUCKET_MAP: dict[str, tuple[str, str]] = {
    "five_hour": ("5h", "5-hour"),
    "weekly": ("weekly", "weekly"),
    "monthly": ("monthly", "monthly"),
}


def _status_snapshot(status: str, captured_at: int, raw: dict[str, Any]) -> QuotaSnapshot:
    return QuotaSnapshot("clinepass", "default", "api", "ClinePass API", None, None, raw.get("plan"), captured_at, "clinepass_api", status, raw)


def _plan_label(plan_payload: dict[str, Any]) -> str:
    display = plan_payload.get("displayName")
    if display:
        return str(display)
    name = plan_payload.get("name")
    if name:
        return str(name)
    return "Cline Pass"


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
            # Mirror claude.py: retry only on 5xx server hiccups; 4xx (including 429 rate
            # limit, but ClinePass returns 401/403 for auth problems) is reported as-is.
            if exc.code not in {500, 502, 503, 504} or attempt == 1:
                raise
            time.sleep(0.2)
    assert last_error is not None
    raise last_error


def collect_clinepass_api_snapshots(
    *,
    opener=urllib.request.urlopen,
    now: int | None = None,
    timeout: float = 15.0,
) -> list[QuotaSnapshot]:
    captured_at = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    key = os.environ.get("CLINE_API_KEY", "").strip()
    if not key:
        return [
            _status_snapshot(
                "unavailable",
                captured_at,
                {"error": "CLINE_API_KEY unset"},
            )
        ]

    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    try:
        plan = _get_json(CLINEPASS_PLAN_URL, headers, opener, timeout)
        limits_payload = _get_json(CLINEPASS_USAGE_LIMITS_URL, headers, opener, timeout)
        # /users/me is requested for parity with glance_clinepass (used to look up balance);
        # the quota collector does not need balance, so its failure is non-fatal — but we
        # still fetch it so a single 401 surfaces here rather than later from a hidden call.
        _get_json(CLINEPASS_ME_URL, headers, opener, timeout)
    except HTTPError as exc:
        status = "stale_token" if exc.code in {401, 403} else "fetch_error"
        return [_status_snapshot(status, captured_at, {"error": f"HTTP {exc.code}: {exc.reason}"})]
    except Exception as exc:
        return [_status_snapshot("fetch_error", captured_at, {"error": str(exc)})]

    plan_payload = (plan.get("data") or {}).get("plan") if isinstance(plan.get("data"), dict) else {}
    plan_payload = plan_payload if isinstance(plan_payload, dict) else {}
    plan_label = _plan_label(plan_payload)

    limits_root = limits_payload.get("data") if isinstance(limits_payload.get("data"), dict) else {}
    raw_limits = limits_root.get("limits") if isinstance(limits_root.get("limits"), list) else []
    out: list[QuotaSnapshot] = []
    for limit in raw_limits:
        if not isinstance(limit, dict):
            continue
        try:
            used_raw = limit.get("percentUsed")
            used = float(used_raw) if used_raw is not None else None
        except Exception:
            continue
        if used is None:
            continue
        type_key = str(limit.get("type") or "").strip()
        bucket, label = _BUCKET_MAP.get(type_key, (type_key or "limit", type_key or "limit"))
        out.append(
            QuotaSnapshot(
                "clinepass",
                "default",
                bucket,
                label,
                round(used, 4),
                _parse_time(limit.get("resetsAt")),
                plan_label,
                captured_at,
                "clinepass_api",
                "ok",
                {"limit": limit, "plan": plan_payload},
            )
        )
    if not out:
        return [_status_snapshot("unavailable", captured_at, {"error": "no_limits", "plan": plan_label})]
    return out
