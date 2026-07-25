from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import pytest

from tokdash.sources.stack import (
    _collect_expiries,
    _collect_health,
    _collect_roles,
    _compute_staleness,
    collect_stack_snapshot,
)

# ── fixtures ────────────────────────────────────────────────────────────────

_SAMPLE_CATALOG = {
    "schema_version": 1,
    "source_sha256": "a" * 64,
    "providers": {
        "free-pool": {"name": "Free Pool", "enabled": True, "constraint": "none"},
        "zai": {"name": "Z.ai", "enabled": True, "constraint": "quota"},
    },
    "models": {
        "deepseek-v4-flash": {
            "display_name": "DeepSeek V4 Flash",
            "tier": 3,
            "cost_class": "free",
            "context": 1048576,
            "tools": True,
            "images": False,
            "reasoning": True,
            "routes": [
                {
                    "provider": "clinepass",
                    "slug": "cline-pass/deepseek-v4-flash",
                    "cost_class": "prepaid",
                },
                {
                    "provider": "deepseek-direct",
                    "slug": "deepseek-v4-flash",
                    "cost_class": "payg",
                },
            ],
        },
        "free-pool-auto": {
            "display_name": "Free Pool Auto",
            "tier": 3,
            "cost_class": "free",
            "context": 262144,
            "tools": False,
            "images": False,
            "reasoning": False,
            "routes": [
                {
                    "provider": "free-pool",
                    "slug": "free-pool/auto",
                    "cost_class": "free",
                }
            ],
        },
    },
    "routing": {
        "tiers": {
            "t3": {"description": "Overflow / free", "default_model": "deepseek-v4-flash"},
        },
        "roles": {
            "task": "clinepass/cline-pass/deepseek-v4-flash",
            "smol": "free-pool/free-pool/auto",
            "default": "anthropic/claude-opus-5",
        },
    },
    "calendar": [],
}

_STALE_HASH = "b" * 64


def _catalog_with_calendar(entries: list[dict]) -> dict:
    c = dict(_SAMPLE_CATALOG)
    c["calendar"] = list(entries)
    return c


def _doctor_ok() -> dict:
    return {
        "schema_version": 1,
        "generated_at": "2026-07-24T12:00:00+00:00",
        "ok": True,
        "counts": {"PASS": 15, "WARN": 0, "FAIL": 0},
        "checks": [
            {"status": "PASS", "name": "hub layout", "detail": "ok"},
            {"status": "PASS", "name": "reserved names", "detail": "ok"},
        ],
    }


def _doctor_failing() -> dict:
    return {
        "schema_version": 1,
        "generated_at": "2026-07-24T12:00:00+00:00",
        "ok": False,
        "counts": {"PASS": 13, "WARN": 2, "FAIL": 1},
        "checks": [
            {"status": "PASS", "name": "hub layout", "detail": "ok"},
            {"status": "FAIL", "name": "mcp registry", "detail": "missing server"},
            {"status": "WARN", "name": "skill resources", "detail": "oversized file"},
        ],
    }


# ── _collect_roles ──────────────────────────────────────────────────────────


def test_roles_happy_path():
    """Roles matched to catalog models carry tier, context, cost_class."""
    result = _collect_roles(_SAMPLE_CATALOG)
    assert result["status"] == "ok"
    roles = result["roles"]

    # Known catalog model: clinepass/cline-pass/deepseek-v4-flash
    task = roles["task"]
    assert task["model"] == "deepseek-v4-flash"
    assert task["display_name"] == "DeepSeek V4 Flash"
    assert task["tier"] == "T3"
    assert task["context"] == 1048576
    assert task["cost_class"] == "free"

    # Also catalog model: free-pool/free-pool/auto
    smol = roles["smol"]
    assert smol["model"] == "free-pool-auto"

    # External role (anthropic) — just the raw value
    default = roles["default"]
    assert default["model"] == "anthropic/claude-opus-5"
    assert default["tier"] is None
    assert default["note"] is not None


def test_roles_no_catalog():
    result = _collect_roles(None)
    assert result["status"] == "unavailable"
    assert "reason" in result


def test_roles_empty_routing():
    catalog = dict(_SAMPLE_CATALOG)
    catalog["routing"] = {}
    result = _collect_roles(catalog)
    assert result["status"] == "ok"
    assert result["roles"] == {}


# ── _collect_expiries ───────────────────────────────────────────────────────


def test_expiries_deadline_only():
    """deadline entries appear; stamp entries are excluded."""
    today = date.today()
    entries = [
        {"date": str(today), "date_kind": "deadline", "kind": "model", "id": "a", "note": "due now"},
        {"date": str(today), "date_kind": "stamp", "kind": "model", "id": "b", "note": "bookkeeping"},
        {
            "date": str(today.replace(year=today.year + 1)),
            "date_kind": "deadline",
            "kind": "provider",
            "id": "c",
            "note": "far future",
        },
    ]
    catalog = _catalog_with_calendar(entries)
    result = _collect_expiries(catalog)
    assert result["status"] == "ok"
    ids = [d["id"] for d in result["deadlines"]]
    assert "a" in ids
    assert "b" not in ids  # stamp excluded
    assert "c" in ids


def test_expiries_past_deadline_excluded():
    """Entries with dates in the past are filtered out."""
    entries = [
        {"date": "2020-01-01", "date_kind": "deadline", "kind": "model", "id": "old", "note": ""},
    ]
    catalog = _catalog_with_calendar(entries)
    result = _collect_expiries(catalog)
    assert result["status"] == "ok"
    assert result["deadlines"] == []


def test_expiries_no_catalog():
    result = _collect_expiries(None)
    assert result["status"] == "unavailable"


# ── _collect_health ─────────────────────────────────────────────────────────


def test_health_ok():
    result = _collect_health(_doctor_ok())
    assert result["status"] == "ok"
    assert result["ok"] is True
    assert result["failing_checks"] == []


def test_health_failing():
    result = _collect_health(_doctor_failing())
    assert result["status"] == "ok"
    assert result["ok"] is False
    assert result["failing_checks"] == ["mcp registry"]
    assert result["warning_checks"] == ["skill resources"]


def test_health_no_doctor():
    result = _collect_health(None)
    assert result["status"] == "unavailable"


# ── _compute_staleness ──────────────────────────────────────────────────────


def test_staleness_no_catalog():
    result = _compute_staleness(None)
    assert result["status"] == "unknown"


def test_staleness_fresh(monkeypatch, tmp_path):
    """SHA matches = fresh."""
    catalog = dict(_SAMPLE_CATALOG)
    catalog["source_sha256"] = "a" * 64
    # Write a models.toml with matching SHA
    toml = tmp_path / "models.toml"
    toml.write_text("dummy", encoding="utf-8")
    import hashlib

    actual = hashlib.sha256(b"dummy").hexdigest()
    catalog["source_sha256"] = actual
    monkeypatch.setattr(
        "tokdash.sources.stack._DEFAULT_MODELS_TOML", toml
    )
    result = _compute_staleness(catalog)
    assert result["status"] == "fresh"


def test_staleness_stale(monkeypatch, tmp_path):
    """SHA mismatch = stale."""
    catalog = dict(_SAMPLE_CATALOG)
    catalog["source_sha256"] = "a" * 64
    toml = tmp_path / "models.toml"
    toml.write_text("different content", encoding="utf-8")
    monkeypatch.setattr(
        "tokdash.sources.stack._DEFAULT_MODELS_TOML", toml
    )
    result = _compute_staleness(catalog)
    assert result["status"] == "stale"
    assert "render_models.py" in result["remedy"]


def test_staleness_missing_toml(monkeypatch, tmp_path):
    toml = tmp_path / "models.toml"  # don't create it
    monkeypatch.setattr(
        "tokdash.sources.stack._DEFAULT_MODELS_TOML", toml
    )
    catalog = dict(_SAMPLE_CATALOG)
    result = _compute_staleness(catalog)
    assert result["status"] == "unknown"


# ── collect_stack_snapshot (integration-level, all mocked) ──────────────────


@pytest.fixture(autouse=True)
def _mock_services_down():
    """Return empty probe results so tests don't touch real sockets."""
    with patch("tokdash.sources.stack._probe_services", return_value=[]):
        yield


_SENTINEL = object()


def _setup_mocks(
    monkeypatch,
    *,
    catalog=_SENTINEL,
    doctor=_SENTINEL,
    staleness_override=_SENTINEL,
):
    if catalog is not _SENTINEL:
        monkeypatch.setattr(
            "tokdash.sources.stack._read_catalog", lambda: catalog
        )
    if doctor is not _SENTINEL:
        monkeypatch.setattr(
            "tokdash.sources.stack._run_doctor", lambda: doctor
        )
    if staleness_override is not _SENTINEL:
        monkeypatch.setattr(
            "tokdash.sources.stack._compute_staleness",
            lambda _c: staleness_override,
        )

def test_snapshot_happy_path(monkeypatch):
    """All sources available — every panel is populated."""
    _setup_mocks(
        monkeypatch,
        catalog=_SAMPLE_CATALOG,
        doctor=_doctor_ok(),
    )
    result = collect_stack_snapshot()
    assert result["roles"]["status"] == "ok"
    assert result["chains"]["status"] == "unavailable"  # by design
    assert result["expiries"]["status"] == "ok"
    assert result["services"]["status"] == "ok"
    assert result["health"]["status"] == "ok"
    assert result["health"]["ok"] is True


def test_snapshot_missing_catalog(monkeypatch):
    """Only the roles/expiries panel degrades; others unaffected."""
    _setup_mocks(
        monkeypatch,
        catalog=None,
        doctor=_doctor_ok(),
    )
    result = collect_stack_snapshot()
    assert result["roles"]["status"] == "unavailable"
    assert result["expiries"]["status"] == "unavailable"
    assert result["health"]["status"] == "ok"
    assert result["services"]["status"] == "ok"
    # Staleness feeds from None catalog
    assert result["catalog_staleness"]["status"] == "unknown"


def test_snapshot_doctor_timeout(monkeypatch):
    """Only health degrades; roles/expiries come from cached catalog."""
    _setup_mocks(
        monkeypatch,
        catalog=_SAMPLE_CATALOG,
        doctor=None,
    )
    result = collect_stack_snapshot()
    assert result["roles"]["status"] == "ok"
    assert result["health"]["status"] == "unavailable"
    assert result["services"]["status"] == "ok"


def test_snapshot_stale_catalog(monkeypatch):
    """Staleness is flagged when SHA does not match."""
    staleness = {"status": "stale", "remedy": "python config/render_models.py --format catalog"}
    _setup_mocks(
        monkeypatch,
        catalog=_SAMPLE_CATALOG,
        doctor=_doctor_ok(),
        staleness_override=staleness,
    )
    result = collect_stack_snapshot()
    assert result["catalog_staleness"]["status"] == "stale"


def _make_probes(*statuses: str) -> list[dict]:
    """Build probe results matching _KNOWN_SERVICES order but with given statuses."""
    names = ["free-pool", "kdash", "cliproxyapi", "openai-budget", "lm-studio", "macaron-stream-adapter"]
    return [
        {"name": n, "host": "127.0.0.1", "port": [8788, 55423, 8317, 9090, 1234, 8789][i], "status": s}
        for i, (n, s) in enumerate(zip(names, statuses))
    ]


def test_snapshot_service_up(monkeypatch):
    """A single reachable service shows as 'up'."""
    _setup_mocks(
        monkeypatch,
        catalog=_SAMPLE_CATALOG,
        doctor=_doctor_ok(),
    )
    probes = _make_probes("up", "down", "down", "down", "down", "down")
    monkeypatch.setattr("tokdash.sources.stack._probe_services", lambda: probes)

    result = collect_stack_snapshot()
    svc = result["services"]["probes"]
    free_pool = [p for p in svc if p["name"] == "free-pool"]
    assert len(free_pool) == 1
    assert free_pool[0]["status"] == "up"
    for p in svc:
        if p["name"] != "free-pool":
            assert p["status"] == "down", f"{p['name']} should be down"


def test_snapshot_all_ports_closed(monkeypatch):
    """Every service shows down when nothing is listening."""
    _setup_mocks(
        monkeypatch,
        catalog=_SAMPLE_CATALOG,
        doctor=_doctor_ok(),
    )
    probes = _make_probes("down", "down", "down", "down", "down", "down")
    monkeypatch.setattr("tokdash.sources.stack._probe_services", lambda: probes)

    result = collect_stack_snapshot()
    assert all(p["status"] == "down" for p in result["services"]["probes"])
