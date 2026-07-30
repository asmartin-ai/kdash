"""Tests for the prototype scoring layer ported into tokdash.suggest (Phase 1).

Covers the pure scoring functions (score_model / recommend / free_pool_view /
build_alerts / runway_days) ported verbatim from
kdash-ts-prototype/src/core/state.ts, the build_scored_state I/O bridge, and
the additive /api/suggest keys (recommendations / free_pool / alerts + the
?tier= filter). Existing build_suggest behaviour is asserted unchanged via the
separate test_suggest.py suite.
"""
from __future__ import annotations

import time

import pytest

import tokdash.api as api
from tokdash.suggest import (
    DEFAULT_REGISTRY,
    _days_until,
    _pct,
    build_alerts,
    build_scored_state,
    free_pool_view,
    recommend,
    runway_days,
    score_model,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model(**overrides):
    """A neutral-healthy T2 subscription model; override any field."""
    base = dict(
        slug="m3",
        name="M3",
        provider="zenmux",
        tier="T2",
        source="subscription",
        max_concurrency=4,
        quota_used=0,
        quota_limit=100,
        health="ok",
        enabled=True,
        latency_ms=0,
        error_rate=0.0,
        cost_out=0.0,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _pct / _days_until primitives (format.ts parity)
# ---------------------------------------------------------------------------


def test_pct_zero_when_limit_nonpositive():
    assert _pct(50, 0) == 0.0
    assert _pct(50, -1) == 0.0


def test_pct_clamps_to_0_100():
    assert _pct(0, 100) == 0.0
    assert _pct(50, 100) == 50.0
    assert _pct(200, 100) == 100.0  # over-limit clamps, not >100


def test_days_until_none_on_missing():
    assert _days_until(None) is None


def test_days_until_fractional_and_negative():
    now = 1_000_000.0
    day = 86400.0
    assert _days_until(int(now + 2 * day), now=now) == 2.0
    assert _days_until(int(now - day), now=now) == -1.0  # past still returns


# ---------------------------------------------------------------------------
# score_model — verbatim state.ts:20-38
# ---------------------------------------------------------------------------


def test_score_subscription_50pct_quota():
    s = score_model(_model(quota_used=50, cost_out=0.5), {})
    # 100 - 50*0.55 - 0 - 0 - 0 - min(15, 0.5*0.35=0.175) + 8 = 80.325 -> 80
    assert s["score"] == 80
    assert s["available"] is True
    assert s["funds_ok"] is True
    assert s["quota_pct"] == 50.0


def test_score_clamps_at_zero():
    # Max penalties + degraded health + no funds (api) + hot quota.
    s = score_model(
        _model(source="api", quota_used=100, health="down", latency_ms=99999,
               error_rate=100, cost_out=100),
        {},
    )
    assert s["score"] == 0
    assert s["available"] is False


def test_available_gate_each_term():
    # disabled
    assert score_model(_model(enabled=False), {})["available"] is False
    # health down
    assert score_model(_model(health="down"), {})["available"] is False
    # quota >= 97
    assert score_model(_model(quota_used=97), {})["available"] is False
    assert score_model(_model(quota_used=96.9), {})["available"] is True
    # api source with no balance -> funds_ok False -> unavailable
    s = score_model(_model(source="api"), {})
    assert s["funds_ok"] is False
    assert s["available"] is False
    # api source WITH balance -> available
    s2 = score_model(_model(source="api"), {"zenmux": 5.0})
    # NOTE: zenmux provider in the registry is subscription, but the model dict
    # here overrides source=api while provider stays zenmux, so the balance
    # lookup hits the zenmux key.
    assert s2["funds_ok"] is True
    assert s2["available"] is True


def test_health_penalty_values():
    ok = score_model(_model(health="ok"), {})
    deg = score_model(_model(health="degraded"), {})
    down = score_model(_model(health="down"), {})
    # All else equal: ok > degraded > down (down also unavailable)
    assert ok["score"] > deg["score"] > down["score"]
    assert deg["score"] == ok["score"] - 25
    assert down["score"] == ok["score"] - 100


def test_source_bonuses_subscription_and_free():
    sub = score_model(_model(source="subscription"), {})
    free = score_model(_model(source="free"), {})
    api_m = score_model(_model(source="api"), {"zenmux": 5.0})
    # subscription +8, free +4, api +0 (and api has funds_ok True here so no -60)
    assert sub["score"] - free["score"] == 4
    assert free["score"] - api_m["score"] == 4


def test_funds_penalty_subtracts_60_for_broke_api():
    s = score_model(_model(source="api"), {})
    funded = score_model(_model(source="api"), {"zenmux": 5.0})
    # broke gets -60 relative to funded (both api, no bonus)
    assert funded["score"] - s["score"] == 60


def test_latency_error_cost_clamps():
    base = score_model(_model(), {})["score"]
    # latency clamp at 20: 99999/200 clamps
    lat = score_model(_model(latency_ms=99999), {})["score"]
    assert base - lat == 20
    # error_rate clamp at 20: rate*2.5 clamps
    err = score_model(_model(error_rate=100), {})["score"]
    assert base - err == 20
    # cost_out clamp at 15: cost*0.35 clamps
    cost = score_model(_model(cost_out=100), {})["score"]
    assert base - cost == 15


def test_quota_zero_when_limit_nonpositive():
    s = score_model(_model(quota_used=50, quota_limit=0), {})
    assert s["quota_pct"] == 0.0
    # No quota penalty applied, and available is not gated by quota.


# ---------------------------------------------------------------------------
# recommend — verbatim state.ts:40-70
# ---------------------------------------------------------------------------


def test_recommend_picks_highest_score_and_reasons():
    scored = [
        score_model(_model(slug="m3", name="M3", quota_used=10), {}),
        score_model(_model(slug="flash", name="Flash", quota_used=60), {}),
    ]
    recs = recommend(scored, {})
    t2 = next(r for r in recs if r["tier"] == "T2")
    assert t2["pick"] == "m3"  # lower quota -> higher score
    assert t2["pick_name"] == "M3"
    assert t2["preferred"] is None
    assert t2["reason"] == "highest score by quota, health, latency and cost"
    assert t2["fallbacks"] == ["flash"]


def test_recommend_preferred_healthy_reason():
    scored = [
        score_model(_model(slug="m3", name="M3", quota_used=28), {}),
        score_model(_model(slug="flash", name="Flash", quota_used=10), {}),
    ]
    recs = recommend(scored, {"pref.T2": "m3"})
    t2 = next(r for r in recs if r["tier"] == "T2")
    assert t2["pick"] == "m3"
    assert t2["preferred"] == "m3"
    assert "preferred model healthy" in t2["reason"]
    assert "72% quota left" in t2["reason"]


def test_recommend_preferred_unavailable_failover():
    # Preferred is gated out by quota>=97; pick falls to the next available.
    scored = [
        score_model(_model(slug="m3", name="M3", quota_used=99), {}),  # unavailable
        score_model(_model(slug="flash", name="Flash", quota_used=10), {}),
    ]
    recs = recommend(scored, {"pref.T2": "m3"})
    t2 = next(r for r in recs if r["tier"] == "T2")
    assert t2["pick"] == "flash"  # failover
    assert "M3 unavailable" in t2["reason"]
    assert "failover" in t2["reason"]


def test_recommend_no_healthy_model_reason():
    scored = [score_model(_model(slug="m3", quota_used=99), {})]  # unavailable
    recs = recommend(scored, {})
    t2 = next(r for r in recs if r["tier"] == "T2")
    assert t2["pick"] is None
    assert t2["pick_name"] is None
    assert t2["reason"] == "no healthy model available in this tier"
    assert t2["fallbacks"] == []


def test_recommend_fallbacks_capped_at_three():
    scored = [
        score_model(_model(slug=f"m{i}", name=f"M{i}", quota_used=i * 10), {})
        for i in range(6)
    ]
    recs = recommend(scored, {})
    t2 = next(r for r in recs if r["tier"] == "T2")
    assert len(t2["fallbacks"]) == 3


def test_recommend_covers_four_tiers_excludes_free():
    scored = [
        score_model(_model(slug="t1", tier="T1", source="free"), {}),
        score_model(_model(slug="t2", tier="T2"), {}),
        score_model(_model(slug="t3", tier="T3"), {}),
        score_model(_model(slug="v", tier="VISION"), {}),
        score_model(_model(slug="f", tier="FREE", source="free"), {}),
    ]
    recs = recommend(scored, {})
    assert [r["tier"] for r in recs] == ["T1", "T2", "T3", "VISION"]
    assert all(r["tier"] != "FREE" for r in recs)


# ---------------------------------------------------------------------------
# free_pool_view — verbatim state.ts:72-87
# ---------------------------------------------------------------------------


def test_free_pool_concurrency_formula_ok_health():
    # max_concurrency 10, ok health, 0% quota -> 10 * 1 * 1 = 10
    scored = [score_model(_model(slug="f", tier="FREE", source="free", max_concurrency=10), {})]
    pool = free_pool_view(scored)
    assert pool["concurrency"] == 10
    assert pool["healthy_count"] == 1
    assert "safe to fan out" in pool["advice"]


def test_free_pool_degraded_health_uses_04_factor():
    # max_concurrency 10, degraded health -> round(10 * 0.4 * 1) = 4
    scored = [score_model(_model(slug="f", tier="FREE", source="free", max_concurrency=10, health="degraded"), {})]
    pool = free_pool_view(scored)
    assert pool["concurrency"] == 4
    assert pool["healthy_count"] == 0
    assert "spawn at most 4" in pool["advice"]


def test_free_pool_quota_reduces_concurrency():
    # 50% quota halves the contribution: round(10 * 1 * 0.5) = 5
    scored = [score_model(_model(slug="f", tier="FREE", source="free", max_concurrency=10, quota_used=50), {})]
    assert free_pool_view(scored)["concurrency"] == 5


def test_free_pool_exhausted_advice():
    # unavailable (quota>=97) free model -> 0 concurrency
    scored = [score_model(_model(slug="f", tier="FREE", source="free", quota_used=99), {})]
    pool = free_pool_view(scored)
    assert pool["concurrency"] == 0
    assert pool["advice"] == "free pool exhausted - do not spawn swarm agents"


def test_free_pool_sums_across_models():
    scored = [
        score_model(_model(slug="f1", tier="FREE", source="free", max_concurrency=5), {}),
        score_model(_model(slug="f2", tier="FREE", source="free", max_concurrency=3), {}),
    ]
    assert free_pool_view(scored)["concurrency"] == 8


def test_free_pool_ignores_non_free_tiers():
    scored = [
        score_model(_model(slug="f", tier="FREE", source="free", max_concurrency=10), {}),
        score_model(_model(slug="t2", tier="T2", max_concurrency=100), {}),
    ]
    assert free_pool_view(scored)["concurrency"] == 10


# ---------------------------------------------------------------------------
# runway_days + build_alerts — verbatim state.ts:142, 194-206
# ---------------------------------------------------------------------------


def test_runway_days_basic_and_zero_spend():
    assert runway_days(100.0, 5.0) == 20.0
    assert runway_days(100.0, 0.0) is None
    assert runway_days(None, 5.0) is None
    assert runway_days(100.0, None) is None


def test_alerts_subscription_85pct_crit():
    alerts = build_alerts(
        [{"plan": "ZenMux", "pct": 90, "window_label": "5h", "expires_at": None}],
        [],
    )
    assert any(a["level"] == "crit" and "90% of 5h" in a["text"] for a in alerts)
    # 84% must NOT fire
    alerts_low = build_alerts(
        [{"plan": "ZenMux", "pct": 84, "window_label": "5h", "expires_at": None}],
        [],
    )
    assert not any("%" in a["text"] for a in alerts_low)


def test_alerts_subscription_expiry_under_3d():
    now = int(time.time())
    alerts = build_alerts(
        [{"plan": "Z", "pct": 10, "window_label": "5h", "expires_at": now + 2 * 86400}],
        [],
    )
    assert any("renews/expires in 2.0d" in a["text"] for a in alerts)
    # 5 days out must NOT fire
    alerts_far = build_alerts(
        [{"plan": "Z", "pct": 10, "window_label": "5h", "expires_at": now + 5 * 86400}],
        [],
    )
    assert not any("renews" in a["text"] for a in alerts_far)


def test_alerts_api_health_not_ok():
    alerts = build_alerts(
        [],
        [{"provider": "deepseek", "health": "degraded", "latency_ms": 500,
          "runway_days": None, "trial_ends_at": None}],
    )
    assert any("deepseek API degraded (500ms)" in a["text"] for a in alerts)


def test_alerts_runway_under_10d_crit():
    alerts = build_alerts(
        [],
        [{"provider": "deepseek", "health": "ok", "latency_ms": 0,
          "runway_days": 5.0, "trial_ends_at": None}],
    )
    assert any(a["level"] == "crit" and "runway 5.0d" in a["text"] for a in alerts)


def test_alerts_runway_none_does_not_fire():
    alerts = build_alerts(
        [],
        [{"provider": "deepseek", "health": "ok", "latency_ms": 0,
          "runway_days": None, "trial_ends_at": None}],
    )
    assert alerts == []


def test_alerts_trial_under_5d_warn():
    now = int(time.time())
    alerts = build_alerts(
        [],
        [{"provider": "fireworks", "health": "ok", "latency_ms": 0,
          "runway_days": None, "trial_ends_at": now + 4 * 86400}],
    )
    assert any("free trial ends in 4.0d" in a["text"] for a in alerts)


# ---------------------------------------------------------------------------
# build_scored_state — I/O bridge
# ---------------------------------------------------------------------------


def test_build_scored_state_keys_and_shape():
    state = build_scored_state({"providers": {}}, pricing_db=None)
    assert set(state.keys()) == {
        "generated_at", "recommendations", "free_pool", "alerts", "scored_models",
    }
    assert isinstance(state["recommendations"], list)
    assert isinstance(state["free_pool"], dict)
    assert isinstance(state["alerts"], list)
    assert isinstance(state["scored_models"], list)
    # Four tiers always present (T1/T2/T3/VISION), FREE excluded.
    assert [r["tier"] for r in state["recommendations"]] == ["T1", "T2", "T3", "VISION"]


def test_build_scored_state_joins_quota_peak_to_health():
    # zenmux saturated -> its T2 models unavailable (quota>=97), peak joined.
    quota = {
        "providers": {
            "zenmux": {
                "status": "ok",
                "network_enabled": True,
                "buckets": [{"used_percent": 99.0}],
            }
        }
    }
    state = build_scored_state(quota, pricing_db=None)
    zenmux_models = [m for m in state["scored_models"] if m["provider"] == "zenmux"]
    assert zenmux_models, "registry must include zenmux models"
    assert all(m["quota_pct"] == 99.0 for m in zenmux_models)
    assert all(m["available"] is False for m in zenmux_models)


def test_build_scored_state_custom_registry():
    custom = [_model(slug="x", tier="T2")]
    state = build_scored_state({"providers": {}}, registry=custom, pricing_db=None)
    assert len(state["scored_models"]) == 1
    assert state["scored_models"][0]["slug"] == "x"


def test_build_scored_state_health_from_provider_status():
    quota = {
        "providers": {
            "deepseek": {"status": "unavailable", "network_enabled": False, "buckets": []},
        }
    }
    state = build_scored_state(quota, pricing_db=None)
    ds = [m for m in state["scored_models"] if m["provider"] == "deepseek"]
    assert ds
    assert ds[0]["health"] == "down"


def test_default_registry_has_free_t2_t3_entries():
    tiers = {e["tier"] for e in DEFAULT_REGISTRY}
    assert {"FREE", "T2", "T3"} <= tiers
    # VISION intentionally empty today; T1 also empty (free lanes are FREE-tier).


# ---------------------------------------------------------------------------
# /api/suggest additive integration
# ---------------------------------------------------------------------------


def test_api_suggest_has_new_keys_and_preserves_existing(monkeypatch):
    from tokdash.sources.quota.types import QuotaSnapshot
    from tokdash.usage_store import UsageEntryStore

    api._clear_cache()
    monkeypatch.setattr(
        "tokdash.sources.quota.collect_local_snapshots",
        lambda: (_ for _ in ()).throw(AssertionError("local collector called")),
    )
    UsageEntryStore().insert_quota_snapshots(
        [
            QuotaSnapshot(
                "zenmux", "default", "5h", "5-hour window", 20.0,
                1_782_909_000, "starter", 1_782_907_200, "zenmux_api", "ok", {},
            )
        ]
    )
    payload = api.get_suggest()

    # Existing build_suggest keys must be intact.
    for key in (
        "schema_version", "pick", "fallbacks", "tiers", "now", "use_next",
        "plans", "flow_budget", "deadlines", "routing_summary", "copy_ready",
    ):
        assert key in payload, f"existing key dropped: {key}"

    # New additive keys.
    assert "recommendations" in payload
    assert "free_pool" in payload
    assert "alerts" in payload
    assert set(payload["free_pool"].keys()) == {"concurrency", "advice"}
    assert [r["tier"] for r in payload["recommendations"]] == ["T1", "T2", "T3", "VISION"]


def test_api_suggest_tier_filter(monkeypatch):
    api._clear_cache()
    monkeypatch.setattr(
        "tokdash.sources.quota.collect_local_snapshots",
        lambda: (_ for _ in ()).throw(AssertionError("local collector called")),
    )
    # No snapshots: still returns a well-formed payload.
    payload = api.get_suggest(tier="t2")
    assert all(r["tier"] == "T2" for r in payload["recommendations"])
    assert len(payload["recommendations"]) == 1
    # Other keys survive the filter.
    assert "pick" in payload
    assert "free_pool" in payload


def test_api_suggest_tier_free_returns_empty(monkeypatch):
    api._clear_cache()
    monkeypatch.setattr(
        "tokdash.sources.quota.collect_local_snapshots",
        lambda: (_ for _ in ()).throw(AssertionError("local collector called")),
    )
    payload = api.get_suggest(tier="FREE")
    assert payload["recommendations"] == []  # prototype contract: FREE not a rec tier


def test_api_suggest_unknown_tier_returns_empty(monkeypatch):
    api._clear_cache()
    monkeypatch.setattr(
        "tokdash.sources.quota.collect_local_snapshots",
        lambda: (_ for _ in ()).throw(AssertionError("local collector called")),
    )
    payload = api.get_suggest(tier="ZZZ")
    assert payload["recommendations"] == []


def test_api_suggest_no_tier_returns_all_four(monkeypatch):
    api._clear_cache()
    monkeypatch.setattr(
        "tokdash.sources.quota.collect_local_snapshots",
        lambda: (_ for _ in ()).throw(AssertionError("local collector called")),
    )
    payload = api.get_suggest()
    assert [r["tier"] for r in payload["recommendations"]] == ["T1", "T2", "T3", "VISION"]
