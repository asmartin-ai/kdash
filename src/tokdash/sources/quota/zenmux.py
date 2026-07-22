from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
import urllib.request

from .codex import _parse_time
from .types import QuotaSnapshot

ZENMUX_BASE_URL = "https://zenmux.ai/api/v1/management"
ZENMUX_SUBSCRIPTION_PATH = "subscription/detail"
ZENMUX_PAYG_PATH = "payg/balance"


def _status_snapshot(status: str, captured_at: int, raw: dict[str, Any], plan: str | None = None) -> QuotaSnapshot:
    return QuotaSnapshot(
        "zenmux",
        "default",
        "api",
        "ZenMux API",
        None,
        None,
        plan,
        captured_at,
        "zenmux_api",
        status,
        raw,
    )


def _plan_label(plan_payload: dict[str, Any]) -> str | None:
    if not isinstance(plan_payload, dict):
        return None
    tier = plan_payload.get("tier")
    if tier:
        return str(tier).upper()
    return None


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
            # Mirror clinepass/zai: retry once on 5xx server hiccups; 4xx (401/403 auth,
            # 429 rate-limit) is reported as-is so the user sees stale_token/fetch_error
            # instead of burning a 200 ms sleep on a problem that won't fix itself.
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 1:
                raise
            time.sleep(0.2)
    assert last_error is not None
    raise last_error


def _bucket_snapshot(
    bucket: str,
    label: str,
    quota: dict[str, Any],
    plan_label: str | None,
    captured_at: int,
) -> QuotaSnapshot:
    try:
        used_raw = quota.get("usage_percentage")
        used_fraction = float(used_raw) if used_raw is not None else None
    except Exception:
        used_fraction = None
    used_percent = round(used_fraction * 100.0, 4) if used_fraction is not None else None
    raw = {
        "remaining_flows": quota.get("remaining_flows"),
        "max_flows": quota.get("max_flows"),
        "used_value_usd": quota.get("used_value_usd"),
        "max_value_usd": quota.get("max_value_usd"),
        "resets_at": quota.get("resets_at"),
        "quota": quota,
    }
    return QuotaSnapshot(
        "zenmux",
        "default",
        bucket,
        label,
        used_percent,
        _parse_time(quota.get("resets_at")),
        plan_label,
        captured_at,
        "zenmux_api",
        "ok",
        raw,
    )


def collect_zenmux_api_snapshots(
    *,
    opener=urllib.request.urlopen,
    now: int | None = None,
    timeout: float = 15.0,
) -> list[QuotaSnapshot]:
    captured_at = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    key = os.environ.get("ZENMUX_MANAGEMENT_API_KEY", "").strip()
    if not key:
        return [
            _status_snapshot(
                "unavailable",
                captured_at,
                {"error": "ZENMUX_MANAGEMENT_API_KEY unset"},
            )
        ]

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        sub_payload = _get_json(f"{ZENMUX_BASE_URL}/{ZENMUX_SUBSCRIPTION_PATH}", headers, opener, timeout)
    except HTTPError as exc:
        status = "stale_token" if exc.code in {401, 403} else "fetch_error"
        return [_status_snapshot(status, captured_at, {"error": f"HTTP {exc.code}: {exc.reason}"})]
    except Exception as exc:
        return [_status_snapshot("fetch_error", captured_at, {"error": str(exc)})]

    sub = sub_payload.get("data") if isinstance(sub_payload.get("data"), dict) else {}
    plan_payload = sub.get("plan") if isinstance(sub.get("plan"), dict) else {}
    plan_label = _plan_label(plan_payload)
    q5 = sub.get("quota_5_hour") if isinstance(sub.get("quota_5_hour"), dict) else {}
    q7 = sub.get("quota_7_day") if isinstance(sub.get("quota_7_day"), dict) else {}

    out: list[QuotaSnapshot] = [
        _bucket_snapshot("5h", "5-hour", q5, plan_label, captured_at),
        _bucket_snapshot("7d", "7-day", q7, plan_label, captured_at),
    ]

    # PAYG balance is optional — fetch after the main subscription detail so a transient
    # balance endpoint failure does not discard the 5h/7d observations we already have.
    payg: float | None = None
    payg_error: str | None = None
    try:
        payg_payload = _get_json(f"{ZENMUX_BASE_URL}/{ZENMUX_PAYG_PATH}", headers, opener, timeout)
        payg_data = payg_payload.get("data") if isinstance(payg_payload.get("data"), dict) else {}
        raw_balance = payg_data.get("total_credits")
        if raw_balance is not None:
            payg = float(raw_balance)
    except HTTPError as exc:
        payg_error = f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        payg_error = str(exc)

    if payg is not None or payg_error is not None:
        payg_raw: dict[str, Any] = {}
        if payg is not None:
            payg_raw = {"balance": payg, "currency": "USD"}
        if payg_error is not None:
            payg_raw["payg_error"] = payg_error
        out.append(
            QuotaSnapshot(
                "zenmux",
                "default",
                "payg",
                "PAYG credits",
                None,
                None,
                plan_label,
                captured_at,
                "zenmux_api",
                "ok" if payg is not None else "fetch_error",
                payg_raw,
            )
        )

    return out
