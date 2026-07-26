"""Shared HTTP client for quota collectors — INCOMPLETE (deepseek not migrated)."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError
import urllib.request


def get_json(url: str, headers: dict[str, str], opener, timeout: float) -> dict[str, Any]:
    """GET with one retry on 5xx, return parsed JSON dict."""
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


def post_json(url: str, headers: dict[str, str], opener, timeout: float, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST JSON body with retry on 5xx, return parsed JSON dict."""
    data_bytes = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers={**headers, "Content-Type": "application/json"})
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
