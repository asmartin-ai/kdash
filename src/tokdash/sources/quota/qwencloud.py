from __future__ import annotations

import json
import os
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
import urllib.request

from .codex import _parse_time
from .types import QuotaSnapshot


def _har_path() -> Path:
    return Path(
        os.environ.get(
            "QWEN_CLOUD_HAR_PATH",
            str(Path.home() / ".omp" / "qwencloud-console.har"),
        )
    )


# Usage API endpoint (HAR-authenticated)
QWEN_CLOUD_USAGE_URL = (
    "https://cs-data.qwencloud.com/data/api.json"
    "?product=sfm_bailian"
    "&action=IntlBroadScopeAspnGateway"
    "&api=zeldaHttp.apikeyMgr.%2Ftokenplan%2Fpersonal%2Fapi%2Fv2%2Fusage"
)

# Model inventory endpoint (API-key fallback)
QWEN_CLOUD_API_BASE = os.environ.get(
    "QWEN_CLOUD_API_BASE",
    "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
).rstrip("/")

QWEN_CLOUD_MODELS_URL = f"{QWEN_CLOUD_API_BASE}/models"


def _status_snapshot(status: str, captured_at: int, raw: dict[str, Any]) -> QuotaSnapshot:
    return QuotaSnapshot("qwencloud", "default", "plan", "Token Plan", None, None, None, captured_at, "qwencloud_api", status, raw)


def _post_json(url: str, data: bytes, headers: dict[str, str], opener, timeout: float) -> dict[str, Any]:
    """POST with retry on 5xx."""
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    last_error: HTTPError | None = None
    for attempt in range(2):
        try:
            with opener(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            return result if isinstance(result, dict) else {}
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {500, 502, 503, 504} or attempt == 1:
                raise
            time.sleep(0.2)
    assert last_error is not None
    raise last_error


def _get_json(url: str, headers: dict[str, str], opener, timeout: float) -> dict[str, Any]:
    """GET with retry on 5xx (model-inventory fallback path)."""
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
    assert last_error is not None
    raise last_error


# ── HAR auth extraction ──────────────────────────────────────────────────────


def _load_har_auth() -> tuple[str, str, bytes] | None:
    """Load session auth from a HAR file exported from the Qwen Cloud console.

    Returns (cookie_header, sec_token, post_body_bytes) on success, or None when
    the HAR file is missing, stale (>24 h), or does not contain the expected
    POST request.
    """
    har_path = _har_path()
    if not har_path.exists():
        return None

    mtime = har_path.stat().st_mtime
    age = time.time() - mtime
    if age > 86_400:  # 24 hours
        return None

    try:
        har = json.loads(har_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    entries = har.get("log", {}).get("entries", [])
    for entry in entries:
        req = entry.get("request", {})
        if req.get("method") != "POST":
            continue
        url = req.get("url", "")
        if "cs-data.qwencloud.com" not in url:
            continue

        # Extract Cookie header value
        cookie = ""
        for hdr in req.get("headers", []):
            if hdr.get("name", "").lower() == "cookie":
                cookie = hdr.get("value", "")
                break

        # Grab the raw post body
        post_text = req.get("postData", {}).get("text", "")
        if not post_text:
            continue

        # Extract sec_token from the URL-encoded body
        params = urllib.parse.parse_qs(post_text)
        sec_token_list = params.get("sec_token", [])
        sec_token = sec_token_list[0] if sec_token_list else ""

        if cookie and sec_token:
            return (cookie, sec_token, post_text.encode("utf-8"))

    return None


# ── Usage API (primary) ──────────────────────────────────────────────────────


def _collect_usage_snapshots(
    *,
    opener=urllib.request.urlopen,
    captured_at: int,
    timeout: float,
) -> list[QuotaSnapshot] | None:
    """Attempt to collect usage data via the HAR-authenticated API.

    Returns a two-bucket snapshot list on success, or None when the HAR file is
    unavailable or the session has expired (401/403).  The caller falls back to
    the model-inventory path in that case.
    """
    auth = _load_har_auth()
    if auth is None:
        return None

    cookie, sec_token, body = auth

    headers: dict[str, str] = {
        "Cookie": cookie,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "Origin": "https://home.qwencloud.com",
        "Referer": "https://home.qwencloud.com/billing/subscription/token-plan-individual",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    }

    try:
        payload = _post_json(QWEN_CLOUD_USAGE_URL, body, headers, opener, timeout)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            return None  # session expired — fall back
        raise

    # Navigate the nesting: data -> DataV2 -> data -> data
    data_root = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    dv2 = data_root.get("DataV2") if isinstance(data_root.get("DataV2"), dict) else {}
    dv2_data = dv2.get("data") if isinstance(dv2.get("data"), dict) else {}
    inner = dv2_data.get("data") if isinstance(dv2_data.get("data"), dict) else {}

    p5h = inner.get("per5HourPercentage")
    p7d = inner.get("per1WeekPercentage")
    r5h = inner.get("per5HourResetTime")
    r7d = inner.get("per1WeekResetTime")

    if p5h is None or p7d is None:
        return None  # unexpected response shape

    out: list[QuotaSnapshot] = []
    for bucket, label, pct, reset_ms in (
        ("5h", "5-hour", p5h, r5h),
        ("7d", "7-day", p7d, r7d),
    ):
        used_percent: float | None = round(float(pct) * 100.0, 4)
        resets_at: int | None = _parse_time(reset_ms) if reset_ms is not None else None

        out.append(
            QuotaSnapshot(
                "qwencloud",
                "default",
                bucket,
                label,
                used_percent,
                resets_at,
                None,  # plan — unknown from usage API
                captured_at,
                "qwencloud_api",
                "ok",
                {
                    "per5HourPercentage": p5h,
                    "per1WeekPercentage": p7d,
                    "per5HourResetTime": r5h,
                    "per1WeekResetTime": r7d,
                },
            )
        )

    return out


# ── Public entry point ───────────────────────────────────────────────────────


def collect_qwencloud_api_snapshots(
    *,
    opener=urllib.request.urlopen,
    now: float | None = None,
    timeout: float = 15.0,
) -> list[QuotaSnapshot]:
    """Collect Qwen Cloud Token Plan usage.

    Tries the HAR-authenticated usage API first (returns real 5-hour and 7-day
    usage percentages).  Falls back to the model-inventory endpoint when a HAR
    file is not available or the browser session has expired.
    """
    captured_at = int(now if now is not None else datetime.now(timezone.utc).timestamp())

    # ── Primary: HAR-authenticated usage API ──
    usage = _collect_usage_snapshots(opener=opener, captured_at=captured_at, timeout=timeout)
    if usage is not None:
        return usage

    # ── Fallback: model inventory via API key ──
    key = os.environ.get("QWEN_CLOUD_API_KEY", "").strip()
    if not key:
        return [
            _status_snapshot(
                "no_key",
                captured_at,
                {"error": "QWEN_CLOUD_API_KEY unset; session expired or HAR missing"},
            )
        ]

    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    try:
        payload = _get_json(QWEN_CLOUD_MODELS_URL, headers, opener, timeout)
    except HTTPError as exc:
        status = "stale_token" if exc.code in {401, 403} else "fetch_error"
        return [_status_snapshot(status, captured_at, {"error": f"HTTP {exc.code}: {exc.reason}"})]
    except Exception as exc:
        return [_status_snapshot("fetch_error", captured_at, {"error": str(exc)})]

    # Parse model list
    models_root = payload.get("data")
    raw_models = models_root if isinstance(models_root, list) else []
    model_ids = [str(m.get("id", "")) for m in raw_models if isinstance(m, dict)]

    if not model_ids:
        return [
            _status_snapshot(
                "fetch_error",
                captured_at,
                {"error": "no models in response", "raw": payload},
            )
        ]

    model_count = len(model_ids)
    raw = {"models": list(model_ids), "model_count": model_count, "raw_payload": payload}
    plan_label = f"{model_count} models"
    return [
        QuotaSnapshot(
            "qwencloud",
            "default",
            "plan",
            "Token Plan",
            None,
            None,
            plan_label,
            captured_at,
            "qwencloud_api",
            "ok",
            raw,
        )
    ]
