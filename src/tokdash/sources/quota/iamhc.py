from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.error import HTTPError
import urllib.request

from .types import QuotaSnapshot

IAMHC_USAGE_URL = "https://api.iamhc.cn/v1/dashboard/billing/usage"


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
            # Retry only on 5xx server hiccups; 4xx is reported as-is.
            if exc.code not in {500, 502, 503, 504} or attempt == 1:
                raise
            time.sleep(0.2)
    assert last_error is not None
    raise last_error


def _beijing_hour(now_utc: datetime) -> int:
    return (now_utc.hour + 8) % 24


def _is_offpeak(beijing_hour: int) -> bool:
    return 1 <= beijing_hour < 6


def collect_iamhc_api_snapshots(
    *,
    opener=urllib.request.urlopen,
    now: Optional[float] = None,
    timeout: float = 15.0,
) -> list[QuotaSnapshot]:
    captured_at = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    key = os.environ.get("IAMHC_API_KEY", "").strip()
    if not key:
        return []

    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }

    try:
        payload = _get_json(IAMHC_USAGE_URL, headers, opener, timeout)
    except HTTPError as exc:
        status = "stale_token" if exc.code in {401, 403} else "fetch_error"
        return [
            QuotaSnapshot(
                "iamhc",
                "default",
                "usage",
                "IAMHC API",
                None,
                None,
                None,
                captured_at,
                "iamhc_api",
                status,
                {"error": f"HTTP {exc.code}: {exc.reason}"},
            )
        ]
    except Exception as exc:
        return [
            QuotaSnapshot(
                "iamhc",
                "default",
                "usage",
                "IAMHC API",
                None,
                None,
                None,
                captured_at,
                "iamhc_api",
                "fetch_error",
                {"error": str(exc)},
            )
        ]

    # Parse total_usage from the billing/usage response.
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    total_usage_raw = data.get("total_usage")
    try:
        total_usage = float(total_usage_raw) if total_usage_raw is not None else None
    except (TypeError, ValueError):
        total_usage = None

    # Compute Beijing off-peak window.
    now_utc = datetime.now(timezone.utc)
    bj_hour = _beijing_hour(now_utc)
    offpeak = _is_offpeak(bj_hour)

    if total_usage is not None:
        status = f"usage: {total_usage:.2f}"
    else:
        status = "ok"

    return [
        QuotaSnapshot(
            "iamhc",
            "default",
            "usage",
            "IAMHC API",
            None,
            None,
            None,
            captured_at,
            "iamhc_api",
            status,
            {
                "payload": payload,
                "total_usage": total_usage,
                "beijing_hour": bj_hour,
                "offpeak": offpeak,
            },
        )
    ]
