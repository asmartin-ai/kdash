from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
import urllib.request
import time

from .types import QuotaSnapshot

AGNES_MODELS_URL = "https://apihub.agnes-ai.com/v1/models"
# Agnes exposes no quota/usage API. This collector performs a liveness probe against
# the /v1/models endpoint (Bearer AGNES_API_KEY) and reports the model count as the
# status string; used_percent is None because there is no usage signal to report.


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
            # Mirror clinepass.py: retry only on 5xx server hiccups; 4xx (including
            # 401/403 auth problems) is reported as-is.
            if exc.code not in {500, 502, 503, 504} or attempt == 1:
                raise
            time.sleep(0.2)
    assert last_error is not None
    raise last_error


def _status_snapshot(status: str, captured_at: int, raw: dict[str, Any]) -> QuotaSnapshot:
    return QuotaSnapshot(
        "agnes",
        "default",
        "liveness",
        "Agnes API",
        None,
        None,
        None,
        captured_at,
        "agnes_api",
        status,
        raw,
    )


def collect_agnes_api_snapshots(
    *,
    opener=urllib.request.urlopen,
    now: float | None = None,
    timeout: float = 15.0,
) -> list[QuotaSnapshot]:
    captured_at = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    key = os.environ.get("AGNES_API_KEY", "").strip()
    if not key:
        return []

    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    try:
        payload = _get_json(AGNES_MODELS_URL, headers, opener, timeout)
    except HTTPError as exc:
        status = "stale_token" if exc.code in {401, 403} else "fetch_error"
        return [_status_snapshot(status, captured_at, {"error": f"HTTP {exc.code}: {exc.reason}"})]
    except Exception as exc:
        return [_status_snapshot("fetch_error", captured_at, {"error": str(exc)})]

    data = payload.get("data")
    models = data if isinstance(data, list) else []
    count = len(models)
    return [
        _status_snapshot(
            f"up ({count} models)",
            captured_at,
            {"model_count": count, "models": models},
        )
    ]
