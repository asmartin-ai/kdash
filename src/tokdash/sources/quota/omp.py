"""Quota snapshots from ``omp usage --json`` — single subprocess instead of per-provider OAuth/HTTP.

oh-my-pi v17+ exposes provider-aggregated usage limits for every authenticated
account via ``omp usage --json``. This module runs that command as a subprocess
(one call per poll cycle) and maps its structured output to the standard
QuotaSnapshot shape, replacing the old per-provider collectors (claude.py,
zai.py, codex.py API portion).  ClinePass and ZenMux remain custom.

Credit: this approach was inspired by oh-my-pi's built-in usage reporting
(``omp usage`` shows a real-time quota bar in the terminal).  A PR to the
upstream tokdash repo suggesting reuse of the omp JSON path is noted in
NEXT.md § Icebox.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ... import clientpaths
from .codex import _normalize_percent, _parse_time
from .types import QuotaSnapshot

# Provider mapping: omp provider id → our legacy provider string + plan label.
_OMP_PROVIDER_MAP = {
    "anthropic": "claude",
    "openai-codex": "codex",
    "zai": "zai",
}

# omp binary (same dir as the omp executable, usually on PATH).
_OMP_BIN = os.environ.get("TOKDASH_OMP_BIN", "omp")


def collect_omp_api_snapshots(
    *,
    now: int | None = None,
    timeout: float = 20.0,
) -> list[QuotaSnapshot]:
    """Run ``omp usage --json`` and convert its reports to QuotaSnapshots.

    One subprocess call covers all three providers that omp knows about
    (anthropic → claude, openai-codex → codex, zai → zai).  If omp is
    unreachable or the JSON is malformed, the caller gets a single ``"api"``-
    bucket status snapshot per known provider with ``status="unavailable"``.
    """
    captured_at = int(now if now is not None else datetime.now(timezone.utc).timestamp())

    try:
        proc = subprocess.run(
            [_OMP_BIN, "usage", "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return [
            _omp_status_snapshot(provider, captured_at,
                                 "unavailable", {"error": str(exc)})
            for provider in _OMP_PROVIDER_MAP.values()
        ]

    if proc.returncode != 0:
        return [
            _omp_status_snapshot(provider, captured_at,
                                 "fetch_error",
                                 {"error": f"omp exit {proc.returncode}",
                                  "stderr": (proc.stderr or "")[:500]})
            for provider in _OMP_PROVIDER_MAP.values()
        ]

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [
            _omp_status_snapshot(provider, captured_at,
                                 "fetch_error",
                                 {"error": "malformed JSON from omp usage"})
            for provider in _OMP_PROVIDER_MAP.values()
        ]

    reports = payload.get("reports") if isinstance(payload, dict) else None
    if not isinstance(reports, list) or not reports:
        return [
            _omp_status_snapshot(provider, captured_at,
                                 "unavailable",
                                 {"error": "no reports in omp usage output"})
            for provider in _OMP_PROVIDER_MAP.values()
        ]

    out: list[QuotaSnapshot] = []
    seen: set[str] = set()
    for report in reports:
        if not isinstance(report, dict):
            continue
        omp_provider = str(report.get("provider") or "")
        provider = _OMP_PROVIDER_MAP.get(omp_provider)
        if provider is None:
            continue
        seen.add(provider)

        fetched_at = int(report.get("fetchedAt") or captured_at)

        limits = report.get("limits")
        if not isinstance(limits, list) or not limits:
            out.append(_omp_status_snapshot(provider, captured_at,
                                            "unavailable",
                                            {"error": "no limits in report",
                                             "fetchedAt": fetched_at}))
            continue

        for limit in limits:
            if not isinstance(limit, dict):
                continue
            bucket, label, percent, resets_at = _omp_limit_fields(limit)
            if bucket is None:
                continue
            out.append(QuotaSnapshot(
                provider=provider,
                account="default",
                bucket=bucket,
                bucket_label=label,
                used_percent=percent,
                resets_at=resets_at,
                plan=None,
                captured_at=captured_at,
                source="omp_api",
                status="ok",
                raw={"limit": limit, "fetchedAt": fetched_at},
            ))

    # Any known provider missing from the omp report is "unavailable".
    for provider in _OMP_PROVIDER_MAP.values():
        if provider not in seen:
            out.append(_omp_status_snapshot(provider, captured_at,
                                            "unavailable",
                                            {"error": "provider missing from omp output"}))

    return out


def _omp_limit_fields(limit: dict[str, Any]) -> tuple[str | None, str, float | None, int | None]:
    """Extract (bucket, label, used_percent, resets_at_epoch_s) from one omp limit entry."""
    bucket = str(limit.get("id") or limit.get("bucket") or "")
    if not bucket:
        return None, "", None, None

    label = str(limit.get("label") or _omp_bucket_label(bucket))
    amount = limit.get("amount") if isinstance(limit.get("amount"), dict) else {}
    used_fraction = _omp_number(amount.get("usedFraction"))
    percent = round(used_fraction * 100.0, 4) if used_fraction is not None else None

    window = limit.get("window") if isinstance(limit.get("window"), dict) else {}
    resets_ms = _omp_number(window.get("resetsAt"))
    resets_at = int(resets_ms / 1000) if resets_ms is not None and resets_ms > 10_000_000_000 else None

    return bucket, label, percent, resets_at


def _omp_bucket_label(bucket_id: str) -> str:
    """Fallback label from the omp bucket id when the explicit label is missing."""
    parts = bucket_id.split(":")
    return parts[-1] if len(parts) > 1 else bucket_id


def _omp_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _omp_status_snapshot(
    provider: str, captured_at: int, status: str, raw: dict[str, Any]
) -> QuotaSnapshot:
    return QuotaSnapshot(
        provider=provider,
        account="default",
        bucket="api",
        bucket_label="omp API",
        used_percent=None,
        resets_at=None,
        plan=None,
        captured_at=captured_at,
        source="omp_api",
        status=status,
        raw=raw,
    )


# ── Claude plan label (from local credentials.json, not omp) ────────────────
#
# omp does not expose the subscription tier / plan label in its JSON output
# (the `plan` field on omp reports is `None`).  We keep the lightweight local-
# file reader that was previously in claude.py so the web Quota card still
# shows "Pro" / "Max 5x" / "Max 20x".


def read_claude_plan() -> dict[str, Any]:
    """Return ``{status, plan, tier, credential_path}`` from the local Claude config."""
    # Precedence: CLAUDE_CODE_OAUTH_TOKEN env var (no plan metadata) >
    # .credentials.json file > macOS Keychain.
    env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if env_token:
        return {"status": "ok", "plan": None, "tier": None, "credential_path": "CLAUDE_CODE_OAUTH_TOKEN"}

    path = clientpaths.claude_config_dir() / ".credentials.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        data = raw if isinstance(raw, dict) else None
    except (FileNotFoundError, json.JSONDecodeError):
        data = _claude_keychain_read()

    if data is None:
        return {"status": "unavailable", "plan": None, "tier": None, "credential_path": str(path)}

    oauth = data.get("claudeAiOauth") if isinstance(data.get("claudeAiOauth"), dict) else {}
    plan = oauth.get("subscriptionType") or data.get("subscriptionType")
    tier = oauth.get("rateLimitTier") or data.get("rateLimitTier")
    return {
        "status": "ok",
        "plan": _plan_label(plan, tier),
        "tier": tier,
        "credential_path": str(path),
    }


def _claude_keychain_read() -> dict[str, Any] | None:
    """macOS Keychain fallback (claude.py parity). Returns None off-macOS or on failure."""
    import sys as _sys
    if _sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        data = json.loads(result.stdout)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _plan_label(plan: Any, tier: Any) -> str | None:
    tier_text = str(tier or "").lower()
    if "max_20x" in tier_text:
        return "Max 20x"
    if "max_5x" in tier_text:
        return "Max 5x"
    if plan:
        return str(plan).replace("_", " ").strip().title() or None
    return None
