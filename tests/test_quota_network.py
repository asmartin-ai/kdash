from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError

import pytest

from tokdash.sources.quota import antigravity, clinepass, codex, omp, qwencloud, zenmux

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "quota"


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _header(req, name: str) -> str | None:
    for key, value in req.header_items():
        if key.lower() == name.lower():
            return value
    return None


# ── antigravity tests ─────────────────────────────────────────────────────


def test_antigravity_api_normalizes_model_quota(monkeypatch, tmp_path):
    ag_dir = tmp_path / ".gemini" / "antigravity-cli"
    ag_dir.mkdir(parents=True)
    (ag_dir / "antigravity-oauth-token").write_text(
        json.dumps(
            {
                "auth_method": "oauth",
                "token": {
                    "access_token": "ya29.token",
                    "refresh_token": "secret-refresh",
                    "expiry": "2096-10-02T07:06:40Z",
                },
                "email": "h@example.com",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(antigravity.clientpaths, "antigravity_cli_dir", lambda: ag_dir)
    authorizations = []

    def opener(req, timeout=15):
        authorizations.append(_header(req, "Authorization"))
        if req.full_url.endswith(":loadCodeAssist"):
            return FakeResponse({"projectId": "project-1"})
        assert req.full_url.endswith(":fetchAvailableModels")
        return FakeResponse(
            {
                "models": {
                    "gemini-3-pro": {
                        "name": "models/gemini-3-pro",
                        "displayName": "Gemini 3 Pro",
                        "quotaInfo": {"remainingFraction": 0.2, "resetTime": "2026-07-02T00:00:00Z"},
                    }
                }
            }
        )

    snapshots = antigravity.collect_antigravity_api_snapshots(opener=opener, now=1_782_907_200)

    assert len(snapshots) == 1
    assert authorizations == ["Bearer ya29.token", "Bearer ya29.token"]
    assert snapshots[0].account == "h@example.com"
    assert snapshots[0].bucket == "models/gemini-3-pro"
    assert snapshots[0].bucket_label == "Gemini 3 Pro"
    assert snapshots[0].used_percent == 80.0
    assert "secret-refresh" not in json.dumps(snapshots[0].raw)
    assert "ya29.token" not in json.dumps(snapshots[0].raw)


def test_antigravity_nested_expired_token_still_attempts_call_and_401_is_stale_without_secret_raw(monkeypatch, tmp_path):
    ag_dir = tmp_path / ".gemini" / "antigravity-cli"
    ag_dir.mkdir(parents=True)
    (ag_dir / "antigravity-oauth-token").write_text(
        json.dumps(
            {
                "auth_method": "oauth",
                "token": {
                    "access_token": "ya29.token",
                    "refresh_token": "secret-refresh",
                    "expiry": "2020-01-01T00:00:00Z",
                },
                "email": "h@example.com",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(antigravity.clientpaths, "antigravity_cli_dir", lambda: ag_dir)
    calls = {"n": 0}

    def opener(_req, timeout=15):
        calls["n"] += 1
        raise HTTPError("https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist", 401, "Unauthorized", {}, None)

    snapshots = antigravity.collect_antigravity_api_snapshots(opener=opener, now=1_782_907_200)

    assert calls["n"] == 1
    assert snapshots[0].status == "stale_token"
    assert snapshots[0].account == "h@example.com"
    raw = json.dumps(snapshots[0].raw)
    assert "secret-refresh" not in raw
    assert "ya29.token" not in raw


def test_antigravity_http_401_is_stale_token(monkeypatch, tmp_path):
    ag_dir = tmp_path / ".gemini" / "antigravity-cli"
    ag_dir.mkdir(parents=True)
    (ag_dir / "antigravity-oauth-token").write_text(json.dumps({"access_token": "ya29.token"}), encoding="utf-8")
    monkeypatch.setattr(antigravity.clientpaths, "antigravity_cli_dir", lambda: ag_dir)

    def opener(_req, timeout=15):
        raise HTTPError("https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist", 401, "Unauthorized", {}, None)

    snapshots = antigravity.collect_antigravity_api_snapshots(opener=opener, now=1_782_907_200)

    assert snapshots[0].status == "stale_token"


def test_antigravity_does_not_retry_rate_limit(monkeypatch, tmp_path):
    ag_dir = tmp_path / ".gemini" / "antigravity-cli"
    ag_dir.mkdir(parents=True)
    (ag_dir / "antigravity-oauth-token").write_text(json.dumps({"access_token": "ya29.token"}), encoding="utf-8")
    monkeypatch.setattr(antigravity.clientpaths, "antigravity_cli_dir", lambda: ag_dir)
    calls = {"load": 0}

    def opener(req, timeout=15):
        if req.full_url.endswith(":loadCodeAssist"):
            calls["load"] += 1
            raise HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
        return FakeResponse(
            {
                "models": [
                    {
                        "name": "models/gemini-3-pro",
                        "displayName": "Gemini 3 Pro",
                        "quotaInfo": {"remainingFraction": 0.2, "resetTime": "2026-07-02T00:00:00Z"},
                    }
                ]
            }
        )

    snapshots = antigravity.collect_antigravity_api_snapshots(opener=opener, now=1_782_907_200)

    assert calls["load"] == 1
    assert snapshots[0].status == "fetch_error"


def _load_quota_fixture(name: str) -> dict:
    path = _FIXTURE_DIR / name
    if not path.exists():
        pytest.skip(f"frozen fixture {path} not present (run scripts/probe_quota_endpoints.py)")
    return json.loads(path.read_text(encoding="utf-8"))


def test_antigravity_models_frozen_fixture_parses(monkeypatch, tmp_path):
    assist = _load_quota_fixture("antigravity_loadcodeassist.json")
    models = _load_quota_fixture("antigravity_models.json")
    ag_dir = tmp_path / ".gemini" / "antigravity-cli"
    ag_dir.mkdir(parents=True)
    (ag_dir / "antigravity-oauth-token").write_text(json.dumps({"access_token": "ya29.token"}), encoding="utf-8")
    monkeypatch.setattr(antigravity.clientpaths, "antigravity_cli_dir", lambda: ag_dir)

    def opener(req, timeout=15):
        return FakeResponse(assist if req.full_url.endswith(":loadCodeAssist") else models)

    snapshots = antigravity.collect_antigravity_api_snapshots(opener=opener, now=1_782_907_200)

    assert snapshots
    assert all(s.status != "fetch_error" for s in snapshots)


# ── clinepass tests ────────────────────────────────────────────────────────


def test_clinepass_api_parses_limits_shape(monkeypatch):
    monkeypatch.setenv("CLINE_API_KEY", "test-cline-key")
    plan_payload = {
        "data": {
            "plan": {"displayName": "Cline Pass Pro", "name": "cline_pass_pro"},
            "currentPeriodEnd": "2026-08-01T00:00:00Z",
        }
    }
    limits_payload = {
        "data": {
            "limits": [
                {"type": "five_hour", "percentUsed": 33, "resetsAt": "2026-07-21T20:00:00Z"},
                {"type": "weekly", "percentUsed": 12, "resetsAt": 1_787_160_000},
                {"type": "monthly", "percentUsed": 5, "resetsAt": 1_789_920_000},
            ]
        }
    }
    me_payload = {"data": {"id": "user-1"}}
    seen_urls = []

    def opener(req, timeout=15):
        seen_urls.append(req.full_url)
        if req.full_url.endswith("/users/me/plan"):
            return FakeResponse(plan_payload)
        if req.full_url.endswith("/users/me/plan/usage-limits"):
            return FakeResponse(limits_payload)
        if req.full_url.endswith("/users/me"):
            return FakeResponse(me_payload)
        raise AssertionError(f"unexpected url: {req.full_url}")

    snapshots = clinepass.collect_clinepass_api_snapshots(opener=opener, now=1_782_907_200)

    by_bucket = {s.bucket: s for s in snapshots}
    assert set(by_bucket) == {"5h", "weekly", "monthly"}
    assert by_bucket["5h"].used_percent == 33.0
    assert by_bucket["5h"].bucket_label == "5-hour"
    assert by_bucket["5h"].plan == "Cline Pass Pro"
    assert by_bucket["5h"].resets_at == int(
        datetime.fromisoformat("2026-07-21T20:00:00+00:00").timestamp()
    )
    assert by_bucket["weekly"].used_percent == 12.0
    assert by_bucket["monthly"].used_percent == 5.0
    assert all(s.provider == "clinepass" for s in snapshots)
    assert all(s.source == "clinepass_api" for s in snapshots)
    assert seen_urls == [
        "https://api.cline.bot/api/v1/users/me/plan",
        "https://api.cline.bot/api/v1/users/me/plan/usage-limits",
        "https://api.cline.bot/api/v1/users/me",
    ]


def test_clinepass_api_unavailable_when_key_unset(monkeypatch):
    monkeypatch.delenv("CLINE_API_KEY", raising=False)

    snapshots = clinepass.collect_clinepass_api_snapshots(now=1_782_907_200)

    assert len(snapshots) == 1
    assert snapshots[0].provider == "clinepass"
    assert snapshots[0].source == "clinepass_api"
    assert snapshots[0].status == "unavailable"
    assert snapshots[0].bucket == "api"
    assert snapshots[0].raw.get("error") == "CLINE_API_KEY unset"


def test_clinepass_api_stale_token_on_401(monkeypatch):
    monkeypatch.setenv("CLINE_API_KEY", "test-cline-key")

    def opener(_req, timeout=15):
        raise HTTPError("https://api.cline.bot/api/v1/users/me/plan", 401, "Unauthorized", {}, None)

    snapshots = clinepass.collect_clinepass_api_snapshots(opener=opener, now=1_782_907_200)

    assert len(snapshots) == 1
    assert snapshots[0].status == "stale_token"
    assert snapshots[0].provider == "clinepass"
    assert snapshots[0].source == "clinepass_api"


# ── zenmux tests ───────────────────────────────────────────────────────────


def test_zenmux_api_parses_5h_7d_buckets(monkeypatch):
    monkeypatch.setenv("ZENMUX_MANAGEMENT_API_KEY", "test-zenmux-key")
    sub_payload = {
        "data": {
            "plan": {"tier": "pro", "expires_at": "2026-08-01T00:00:00Z"},
            "account_status": "active",
            "quota_5_hour": {
                "usage_percentage": 0.077,
                "remaining_flows": 46,
                "max_flows": 50,
                "used_value_usd": 1.23,
                "max_value_usd": 20.0,
                "resets_at": "2026-07-21T05:34:00Z",
            },
            "quota_7_day": {
                "usage_percentage": 0.227,
                "remaining_flows": 309,
                "max_flows": 400,
                "used_value_usd": 12.5,
                "max_value_usd": 50.0,
                "resets_at": "2026-07-26T13:00:00Z",
            },
        }
    }
    seen_urls = []
    seen_auth = []

    def opener(req, timeout=15):
        seen_urls.append(req.full_url)
        seen_auth.append(_header(req, "Authorization"))
        if req.full_url.endswith("/subscription/detail"):
            return FakeResponse(sub_payload)
        if req.full_url.endswith("/payg/balance"):
            return FakeResponse({"data": {}})
        raise AssertionError(f"unexpected url: {req.full_url}")

    snapshots = zenmux.collect_zenmux_api_snapshots(opener=opener, now=1_782_907_200)

    by_bucket = {s.bucket: s for s in snapshots}
    assert set(by_bucket) == {"5h", "7d"}
    assert by_bucket["5h"].used_percent == 7.7
    assert by_bucket["5h"].bucket_label == "5-hour"
    assert by_bucket["5h"].plan == "PRO"
    assert by_bucket["5h"].resets_at == int(
        datetime.fromisoformat("2026-07-21T05:34:00+00:00").timestamp()
    )
    assert by_bucket["5h"].raw.get("remaining_flows") == 46
    assert by_bucket["5h"].raw.get("max_flows") == 50
    assert by_bucket["7d"].used_percent == 22.7
    assert by_bucket["7d"].bucket_label == "7-day"
    assert by_bucket["7d"].resets_at == int(
        datetime.fromisoformat("2026-07-26T13:00:00+00:00").timestamp()
    )
    assert all(s.provider == "zenmux" for s in snapshots)
    assert all(s.source == "zenmux_api" for s in snapshots)
    assert seen_urls == [
        "https://zenmux.ai/api/v1/management/subscription/detail",
        "https://zenmux.ai/api/v1/management/payg/balance",
    ]
    assert seen_auth == ["Bearer test-zenmux-key", "Bearer test-zenmux-key"]


def test_zenmux_api_unavailable_when_key_unset(monkeypatch):
    monkeypatch.delenv("ZENMUX_MANAGEMENT_API_KEY", raising=False)

    snapshots = zenmux.collect_zenmux_api_snapshots(now=1_782_907_200)

    assert len(snapshots) == 1
    assert snapshots[0].provider == "zenmux"
    assert snapshots[0].source == "zenmux_api"
    assert snapshots[0].status == "unavailable"
    assert snapshots[0].bucket == "api"
    assert snapshots[0].raw.get("error") == "ZENMUX_MANAGEMENT_API_KEY unset"


def test_zenmux_api_stale_token_on_401(monkeypatch):
    monkeypatch.setenv("ZENMUX_MANAGEMENT_API_KEY", "test-zenmux-key")

    def opener(_req, timeout=15):
        raise HTTPError("https://zenmux.ai/api/v1/management/subscription/detail", 401, "Unauthorized", {}, None)

    snapshots = zenmux.collect_zenmux_api_snapshots(opener=opener, now=1_782_907_200)

    assert len(snapshots) == 1
    assert snapshots[0].status == "stale_token"
    assert snapshots[0].provider == "zenmux"
    assert snapshots[0].source == "zenmux_api"


def test_zenmux_api_includes_payg_bucket_when_available(monkeypatch):
    monkeypatch.setenv("ZENMUX_MANAGEMENT_API_KEY", "test-zenmux-key")
    sub_payload = {
        "data": {
            "plan": {"tier": "pro"},
            "quota_5_hour": {"usage_percentage": 0.1, "resets_at": "2026-07-21T05:34:00Z"},
            "quota_7_day": {"usage_percentage": 0.2, "resets_at": "2026-07-26T13:00:00Z"},
        }
    }
    payg_payload = {"data": {"total_credits": 12.34}}
    seen_urls = []

    def opener(req, timeout=15):
        seen_urls.append(req.full_url)
        if req.full_url.endswith("/subscription/detail"):
            return FakeResponse(sub_payload)
        if req.full_url.endswith("/payg/balance"):
            return FakeResponse(payg_payload)
        raise AssertionError(f"unexpected url: {req.full_url}")

    snapshots = zenmux.collect_zenmux_api_snapshots(opener=opener, now=1_782_907_200)

    by_bucket = {s.bucket: s for s in snapshots}
    assert set(by_bucket) == {"5h", "7d", "payg"}
    payg = by_bucket["payg"]
    assert payg.bucket_label == "PAYG credits"
    assert payg.used_percent is None
    assert payg.raw.get("balance") == 12.34
    assert payg.raw.get("currency") == "USD"
    assert payg.status == "ok"
    assert seen_urls == [
        "https://zenmux.ai/api/v1/management/subscription/detail",
        "https://zenmux.ai/api/v1/management/payg/balance",
    ]


# ── omp tests ──────────────────────────────────────────────────────────────


def _omp_anthropic_payload() -> dict:
    return {
        "reports": [
            {
                "provider": "anthropic",
                "fetchedAt": 1_782_907_200,
                "limits": [
                    {
                        "id": "5h",
                        "label": "5-hour window",
                        "amount": {"usedFraction": 0.01},
                        "window": {"resetsAt": 1_782_910_800_000},
                    },
                    {
                        "id": "7d",
                        "label": "7-day window",
                        "amount": {"usedFraction": 0.63},
                        "window": {"resetsAt": 1_783_467_600_000},
                    },
                ],
            }
        ]
    }


def _omp_all_three_payload() -> dict:
    return {
        "reports": [
            {
                "provider": "anthropic",
                "fetchedAt": 1_782_907_200,
                "limits": [
                    {
                        "id": "5h",
                        "label": "5-hour window",
                        "amount": {"usedFraction": 0.01},
                        "window": {"resetsAt": 1_782_910_800_000},
                    },
                ],
            },
            {
                "provider": "openai-codex",
                "fetchedAt": 1_782_907_200,
                "limits": [
                    {
                        "id": "5h",
                        "label": "5-hour window",
                        "amount": {"usedFraction": 0.42},
                        "window": {"resetsAt": 1_782_910_800_000},
                    },
                ],
            },
            {
                "provider": "zai",
                "fetchedAt": 1_782_907_200,
                "limits": [
                    {
                        "id": "5h_tokens",
                        "label": "5h tokens",
                        "amount": {"usedFraction": 0.07},
                        "window": {"resetsAt": 1_787_160_000_000},
                    },
                ],
            },
        ]
    }


def test_omp_collects_anthropic_limits(monkeypatch):
    payload = _omp_anthropic_payload()

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload))

    monkeypatch.setattr("tokdash.sources.quota.omp.subprocess.run", fake_run)

    snapshots = omp.collect_omp_api_snapshots(now=1_782_907_200)

    usage_snaps = [s for s in snapshots if s.bucket not in {"api", "reset_credits"}]
    assert len(usage_snaps) == 2
    assert all(s.provider == "claude" for s in usage_snaps)
    assert all(s.source == "omp_api" for s in usage_snaps)

    by_bucket = {s.bucket: s for s in usage_snaps}
    assert by_bucket["5h"].used_percent == 1.0
    assert by_bucket["5h"].bucket_label == "5-hour window"
    assert by_bucket["5h"].resets_at == 1_782_910_800
    assert by_bucket["7d"].used_percent == 63.0
    assert by_bucket["7d"].resets_at == 1_783_467_600


def test_omp_provides_codex_and_zai_limits(monkeypatch):
    payload = _omp_all_three_payload()

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload))

    monkeypatch.setattr("tokdash.sources.quota.omp.subprocess.run", fake_run)

    snapshots = omp.collect_omp_api_snapshots(now=1_782_907_200)

    providers = {s.provider for s in snapshots if s.bucket not in {"api", "reset_credits"}}
    assert providers == {"claude", "codex", "zai"}

    # codex snapshot
    codex_snaps = [s for s in snapshots if s.provider == "codex"]
    assert len(codex_snaps) == 1
    assert codex_snaps[0].bucket == "5h"
    assert codex_snaps[0].used_percent == 42.0
    assert codex_snaps[0].source == "omp_api"

    # zai snapshot
    zai_snaps = [s for s in snapshots if s.provider == "zai"]
    assert len(zai_snaps) == 1
    assert zai_snaps[0].bucket == "5h_tokens"
    assert zai_snaps[0].used_percent == 7.0
    assert zai_snaps[0].source == "omp_api"


def test_omp_unavailable_when_subprocess_fails(monkeypatch):
    def fake_run(cmd, **kw):
        raise FileNotFoundError("omp not found")

    monkeypatch.setattr("tokdash.sources.quota.omp.subprocess.run", fake_run)

    snapshots = omp.collect_omp_api_snapshots(now=1_782_907_200)

    providers = {s.provider for s in snapshots}
    assert providers == {"claude", "codex", "zai"}
    assert all(s.status == "unavailable" for s in snapshots)
    assert all(s.bucket == "api" for s in snapshots)
    assert all(s.source == "omp_api" for s in snapshots)


def test_omp_unavailable_when_omp_exits_nonzero(monkeypatch):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stderr="omp: not authenticated")

    monkeypatch.setattr("tokdash.sources.quota.omp.subprocess.run", fake_run)

    snapshots = omp.collect_omp_api_snapshots(now=1_782_907_200)

    providers = {s.provider for s in snapshots}
    assert providers == {"claude", "codex", "zai"}
    assert all(s.status == "fetch_error" for s in snapshots)
    assert all(s.bucket == "api" for s in snapshots)
    assert all(s.source == "omp_api" for s in snapshots)

# ── qwencloud tests ────────────────────────────────────────────────────────


def _qwencloud_response_data(
    p5h: float = 0.0000834,
    p7d: float = 0.0799,
    r5h: int = 1_784_847_540_000,
    r7d: int = 1_785_338_340_000,
) -> dict:
    """Build the nested Qwen Cloud usage API response body."""
    return {
        "code": "200",
        "data": {
            "DataV2": {
                "data": {
                    "data": {
                        "per5HourPercentage": p5h,
                        "per1WeekPercentage": p7d,
                        "per5HourResetTime": r5h,
                        "per1WeekResetTime": r7d,
                    },
                    "success": True,
                }
            }
        },
    }


def _qwencloud_fake_har(
    tmp_path: Path, monkeypatch, *, cookie: str = "session=abc123", sec_token: str = "test-sec-token"
) -> Path:
    """Write a minimal HAR fixture and monkeypatch QWEN_CLOUD_HAR_PATH to point at it."""
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "url": "https://cs-data.qwencloud.com/data/api.json?product=sfm_bailian&action=IntlBroadScopeAspnGateway&api=zeldaHttp.apikeyMgr.%2Ftokenplan%2Fpersonal%2Fapi%2Fv2%2Fusage",
                        "headers": [
                            {"name": "Cookie", "value": cookie},
                            {"name": "Content-Type", "value": "application/x-www-form-urlencoded"},
                        ],
                        "postData": {
                            "mimeType": "application/x-www-form-urlencoded",
                            "text": f"product=sfm_bailian&action=IntlBroadScopeAspnGateway&sec_token={sec_token}&region=ap-southeast-1&params=%7B%22Api%22%3A%22zeldaHttp.apikeyMgr.%2Ftokenplan%2Fpersonal%2Fapi%2Fv2%2Fusage%22%7D",
                        },
                    },
                    "response": {
                        "status": 200,
                        "content": {"mimeType": "application/json", "text": json.dumps(_qwencloud_response_data())},
                    },
                }
            ]
        }
    }
    har_path = tmp_path / "qwencloud_har.json"
    har_path.write_text(json.dumps(har), encoding="utf-8")
    monkeypatch.setenv("QWEN_CLOUD_HAR_PATH", str(har_path))
    return har_path


def test_qwencloud_api_parses_usage_buckets(monkeypatch, tmp_path):
    _qwencloud_fake_har(tmp_path, monkeypatch)

    seen_cookie = None
    seen_body = None

    def opener(req, timeout=15):
        nonlocal seen_cookie, seen_body
        seen_cookie = _header(req, "Cookie")
        seen_body = req.data
        return FakeResponse(_qwencloud_response_data())

    snapshots = qwencloud.collect_qwencloud_api_snapshots(opener=opener, now=1_782_907_200)

    by_bucket = {s.bucket: s for s in snapshots}
    assert set(by_bucket) == {"5h", "7d"}
    assert by_bucket["5h"].used_percent == 0.0083  # 0.0000834 * 100
    assert by_bucket["5h"].bucket_label == "5-hour"
    assert by_bucket["5h"].resets_at == 1_784_847_540  # ms → s
    assert by_bucket["7d"].used_percent == 7.99  # 0.0799 * 100
    assert by_bucket["7d"].bucket_label == "7-day"
    assert by_bucket["7d"].resets_at == 1_785_338_340  # ms → s
    assert all(s.provider == "qwencloud" for s in snapshots)
    assert all(s.source == "qwencloud_api" for s in snapshots)
    assert all(s.status == "ok" for s in snapshots)
    assert seen_cookie == "session=abc123"
    assert seen_body == b"product=sfm_bailian&action=IntlBroadScopeAspnGateway&sec_token=test-sec-token&region=ap-southeast-1&params=%7B%22Api%22%3A%22zeldaHttp.apikeyMgr.%2Ftokenplan%2Fpersonal%2Fapi%2Fv2%2Fusage%22%7D"


def test_qwencloud_api_falls_back_to_models_when_har_missing(monkeypatch):
    """When no HAR file is available and QWEN_CLOUD_API_KEY is set, fall back to model list."""
    monkeypatch.setenv("QWEN_CLOUD_HAR_PATH", str(_FIXTURE_DIR / "nonexistent_har.json"))
    monkeypatch.setenv("QWEN_CLOUD_API_KEY", "test-key")

    def opener(req, timeout=15):
        return FakeResponse({"data": [{"id": "qwen-turbo"}, {"id": "qwen-plus"}]})

    snapshots = qwencloud.collect_qwencloud_api_snapshots(opener=opener, now=1_782_907_200)

    assert len(snapshots) == 1
    assert snapshots[0].bucket == "plan"
    assert snapshots[0].plan == "2 models"
    assert snapshots[0].status == "ok"
    assert snapshots[0].source == "qwencloud_api"
    assert snapshots[0].raw.get("model_count") == 2


def test_qwencloud_api_session_expired_falls_back(monkeypatch, tmp_path):
    """When the HAR exists but the server returns 401, fall back to model inventory."""
    _qwencloud_fake_har(tmp_path, monkeypatch)
    monkeypatch.setenv("QWEN_CLOUD_API_KEY", "test-key")

    canary_fired = False

    def opener(req, timeout=15):
        nonlocal canary_fired
        if "api.json" in req.full_url:
            canary_fired = True
            raise HTTPError(req.full_url, 401, "Unauthorized", {}, None)
        if "/models" in req.full_url:
            return FakeResponse({"data": [{"id": "qwen-turbo"}]})
        raise AssertionError(f"unexpected url: {req.full_url}")

    snapshots = qwencloud.collect_qwencloud_api_snapshots(opener=opener, now=1_782_907_200)

    assert canary_fired  # confirms usage API was indeed attempted
    assert len(snapshots) == 1
    assert snapshots[0].bucket == "plan"
    assert snapshots[0].status == "ok"


def test_qwencloud_api_stale_har_returns_no_key(monkeypatch, tmp_path):
    """Stale HAR (>24h) does not block fallback — no API key means no_key status."""
    har_path = _qwencloud_fake_har(tmp_path, monkeypatch)
    # Set the file's mtime to 48 hours ago
    import os, time
    os.utime(har_path, (time.time() - 172_800, time.time() - 172_800))
    monkeypatch.delenv("QWEN_CLOUD_API_KEY", raising=False)

    snapshots = qwencloud.collect_qwencloud_api_snapshots(now=1_782_907_200)

    assert len(snapshots) == 1
    assert snapshots[0].status == "no_key"
    assert "session expired" in str(snapshots[0].raw.get("error", ""))


def test_qwencloud_api_unavailable_when_no_har_no_key(monkeypatch):
    monkeypatch.setenv("QWEN_CLOUD_HAR_PATH", str(_FIXTURE_DIR / "nonexistent_har.json"))
    monkeypatch.delenv("QWEN_CLOUD_API_KEY", raising=False)

    snapshots = qwencloud.collect_qwencloud_api_snapshots(now=1_782_907_200)

    assert len(snapshots) == 1
    assert snapshots[0].status == "no_key"
    assert "session expired" in str(snapshots[0].raw.get("error", ""))


def test_qwencloud_api_stale_token_on_401_with_no_fallback_key(monkeypatch, tmp_path):
    _qwencloud_fake_har(tmp_path, monkeypatch)
    monkeypatch.delenv("QWEN_CLOUD_API_KEY", raising=False)

    def opener(req, timeout=15):
        if "api.json" in req.full_url:
            raise HTTPError(req.full_url, 401, "Unauthorized", {}, None)
        raise AssertionError(f"unexpected url: {req.full_url}")

    snapshots = qwencloud.collect_qwencloud_api_snapshots(opener=opener, now=1_782_907_200)

    assert len(snapshots) == 1
    assert snapshots[0].status == "no_key"
    assert "session expired" in str(snapshots[0].raw.get("error", ""))
