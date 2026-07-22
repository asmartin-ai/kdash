"""Focused contract tests for tokdash.glance (the in-package module).

These were previously loaded via importlib from scripts/tokdash_glance.py
(the standalone copy). That copy has been removed; the canonical location
is now src/tokdash/glance.py. We import the package module directly.

Note: the Codex HUD section (glance_codex) was intentionally removed from
glance.py on 2026-07-18 (free plan, no auth.json, can't refresh — see the
comment at the former call site in src/tokdash/glance.py). The three codex
tests below are therefore skipped, not deleted, so the removal stays
visible in the test record.
"""
from __future__ import annotations

import time

import pytest

from tokdash import glance


@pytest.fixture
def glance_mod():
    return glance


def _sample_claude_payload() -> dict:
    return {
        "five_hour": {"utilization": 0.42, "resets_at": "2026-07-17T12:00:00Z"},
        "seven_day": {"utilization": 0.18, "resets_at": "2026-07-20T00:00:00Z"},
    }


def test_cooldown_records_claude_section_before_meters(glance_mod, monkeypatch, tmp_path):
    """P0: cooldown/cache path must not leave Claude meters under ZENMUX."""
    monkeypatch.setenv("TOKDASH_CLAUDE_OAUTH_COOLDOWN", "300")
    glance._CLAUDE_OAUTH_COOLDOWN_S = 300.0
    glance._CLAUDE_OAUTH_LAST_CALL = time.monotonic()  # force cooldown
    glance._CLAUDE_AUTH_FREEZE_UNTIL_MTIME = None
    glance._CLAUDE_NEXT_LIVE_AFTER = 0.0
    glance._CLAUDE_LAST_PAYLOAD = _sample_claude_payload()
    glance._CLAUDE_LAST_PAYLOAD_AT = time.time()
    cache_path = tmp_path / "claude_usage_cache.json"
    cache_path.write_text(
        __import__("json").dumps(
            {"saved_at": time.time(), "payload": _sample_claude_payload()}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(glance, "_claude_cache_path", lambda: cache_path)

    glance._COMPACT = True
    glance._RECORDS = []
    glance._CUR_SECTION = ""
    # Prior provider (what compact mode was still "in" before the bugfix).
    glance.section("ZENMUX", "starter")
    glance.kv_row("5-hour", 10.0, "zenmux prior")

    rc = glance._glance_claude_plan_body(
        token="tok",
        meta={"plan": "pro", "cred_mtime": 1.0},
        plan="pro",
        logged_in=True,
        cli_st={"email": "user@example.com"},
    )
    assert rc == 0

    # First CLAUDE record must be the section heading.
    claude_idx = next(
        i
        for i, r in enumerate(glance._RECORDS)
        if r.get("kind") == "section" and r.get("title") == "CLAUDE"
    )
    assert glance._RECORDS[claude_idx]["title"] == "CLAUDE"
    # Every Claude meter after that section belongs to CLAUDE, not ZENMUX.
    for r in glance._RECORDS[claude_idx + 1 :]:
        if r.get("kind") == "section":
            break
        if r.get("kind") == "meter":
            assert r.get("section") == "CLAUDE", r


def test_live_path_section_before_meters(glance_mod, monkeypatch):
    glance._CLAUDE_OAUTH_LAST_CALL = 0.0
    glance._CLAUDE_AUTH_FREEZE_UNTIL_MTIME = None
    glance._CLAUDE_NEXT_LIVE_AFTER = 0.0
    payload = _sample_claude_payload()
    monkeypatch.setattr(glance, "_http_json", lambda *a, **k: payload)
    monkeypatch.setattr(glance, "_save_claude_usage_cache", lambda p: None)
    monkeypatch.setattr(glance, "_load_claude_usage_cache", lambda: None)

    glance._COMPACT = True
    glance._RECORDS = []
    glance._CUR_SECTION = ""
    glance.section("ZENMUX", "prior")
    rc = glance._glance_claude_plan_body(
        token="tok",
        meta={"plan": "pro"},
        plan="pro",
        logged_in=True,
        cli_st={},
    )
    assert rc == 0
    titles = [r.get("title") for r in glance._RECORDS if r.get("kind") == "section"]
    assert "CLAUDE" in titles
    claude_i = next(
        i
        for i, r in enumerate(glance._RECORDS)
        if r.get("kind") == "section" and r.get("title") == "CLAUDE"
    )
    meters = [
        r
        for r in glance._RECORDS[claude_i + 1 :]
        if r.get("kind") == "meter"
    ]
    assert meters
    assert all(m.get("section") == "CLAUDE" for m in meters)


def test_401_freeze_and_429_backoff_section_order(glance_mod, monkeypatch):
    import urllib.error

    glance._COMPACT = True
    payload = _sample_claude_payload()
    monkeypatch.setattr(
        glance,
        "_load_claude_usage_cache",
        lambda: (payload, time.time()),
    )
    monkeypatch.setattr(glance, "_render_claude_payload", lambda p, mode="live": True)

    # 401 path
    glance._RECORDS = []
    glance._CUR_SECTION = "ZENMUX"
    glance._CLAUDE_OAUTH_LAST_CALL = 0.0
    glance._CLAUDE_AUTH_FREEZE_UNTIL_MTIME = None
    glance._CLAUDE_NEXT_LIVE_AFTER = 0.0

    def boom401(*a, **k):
        raise urllib.error.HTTPError(
            "https://api.anthropic.com/api/oauth/usage",
            401,
            "Unauthorized",
            hdrs=None,
            fp=__import__("io").BytesIO(b"nope"),
        )

    monkeypatch.setattr(glance, "_http_json", boom401)
    glance._glance_claude_plan_body(
        token="tok",
        meta={"plan": "pro", "cred_mtime": 42.0},
        plan="pro",
        logged_in=True,
        cli_st={},
    )
    claude_i = next(
        i
        for i, r in enumerate(glance._RECORDS)
        if r.get("kind") == "section" and r.get("title") == "CLAUDE"
    )
    assert claude_i is not None
    meters_401 = [
        r
        for r in glance._RECORDS[claude_i + 1 :]
        if r.get("kind") == "meter"
    ]
    # When cache render runs, meters must belong to CLAUDE (not leftover ZENMUX).
    assert all(m.get("section") == "CLAUDE" for m in meters_401)

    # 429 path
    glance._RECORDS = []
    glance._CUR_SECTION = "ZENMUX"
    glance._CLAUDE_OAUTH_LAST_CALL = 0.0
    glance._CLAUDE_AUTH_FREEZE_UNTIL_MTIME = None
    glance._CLAUDE_NEXT_LIVE_AFTER = 0.0

    def boom429(*a, **k):
        raise urllib.error.HTTPError(
            "https://api.anthropic.com/api/oauth/usage",
            429,
            "Too Many",
            hdrs=None,
            fp=__import__("io").BytesIO(b"slow"),
        )

    monkeypatch.setattr(glance, "_http_json", boom429)
    glance._glance_claude_plan_body(
        token="tok",
        meta={"plan": "pro"},
        plan="pro",
        logged_in=True,
        cli_st={},
    )
    claude_i429 = next(
        i
        for i, r in enumerate(glance._RECORDS)
        if r.get("kind") == "section" and r.get("title") == "CLAUDE"
    )
    meters_429 = [
        r
        for r in glance._RECORDS[claude_i429 + 1 :]
        if r.get("kind") == "meter"
    ]
    assert all(m.get("section") == "CLAUDE" for m in meters_429)


def test_sanitize_display_strips_controls(glance_mod):
    dirty = "ok\r\nline\x1b[31mRED\x1b[0m\x07"
    clean = glance.sanitize_display(dirty)
    assert "\n" not in clean
    assert "\r" not in clean
    assert "\x1b" not in clean
    assert "\x07" not in clean
    assert "ok" in clean and "line" in clean and "RED" in clean


def test_compose_dashboard_widths_and_rail(glance_mod):
    glance.USE_COLOR = False
    records = [
        {"kind": "section", "section": "ZENMUX", "title": "ZENMUX", "subtitle": "starter"},
        {
            "kind": "meter",
            "section": "ZENMUX",
            "label": "5-hour",
            "pct": 12.5,
            "extra": "44/50 left",
        },
        {"kind": "section", "section": "CLAUDE", "title": "CLAUDE", "subtitle": "plan=pro · cached"},
        {
            "kind": "meter",
            "section": "CLAUDE",
            "label": "5-hour",
            "pct": 42.0,
            "extra": "reset 07-17 12:00 · cached",
        },
        {
            "kind": "meter",
            "section": "CLAUDE",
            "label": "7-day",
            "pct": 18.0,
            "extra": "reset 07-20 00:00 · cached",
        },
    ]
    for cols in (72, 80, 100, 140):
        lines = glance.compose_dashboard(records, term_cols=cols)
        assert lines
        plain = [glance._strip_ansi(L) for L in lines]
        # every composed line fits terminal width
        assert all(len(L) <= cols for L in plain), (cols, max(len(L) for L in plain))
        # right SUGGEST box: top/body/bot share one left edge (ignore rare
        # meter text that may also contain a box glyph).
        top_idx = next(i for i, L in enumerate(plain) if "┌" in L)
        bot_idx = next(i for i, L in enumerate(plain) if "└" in L)
        rail = plain[top_idx].index("┌")
        assert plain[bot_idx].index("└") == rail
        for L in plain[top_idx : bot_idx + 1]:
            if "│" in L:
                assert L.index("│") == rail, (cols, L, rail)
        # section ownership in the left column text
        left_only = "\n".join(L[:rail] for L in plain)
        assert "CLAUDE" in left_only
        assert "ZENMUX" in left_only
        assert left_only.index("ZENMUX") < left_only.index("CLAUDE")


def _sample_codex_quota(*, plan: str = "Free", used5: float = 42.0, used7: float = 18.0) -> dict:
    return {
        "providers": {
            "codex": {
                "provider": "codex",
                "plan": plan,
                "status": "ok",
                "estimated": False,
                "buckets": [
                    {
                        "bucket": "5h",
                        "bucket_label": "5-hour window",
                        "used_percent": used5,
                        "remaining_percent": 100.0 - used5,
                        "resets_at": 1784400000,
                        "status": "ok",
                    },
                    {
                        "bucket": "7d",
                        "bucket_label": "7-day window",
                        "used_percent": used7,
                        "remaining_percent": 100.0 - used7,
                        "resets_at": 1784800000,
                        "status": "ok",
                    },
                ],
            }
        }
    }


# Codex HUD section (glance_codex) was removed from glance.py on 2026-07-18:
# free plan, no auth.json, can't refresh. See the comment at the former call
# site in src/tokdash/glance.py. The three codex tests are skipped (not
# deleted) so the removal stays visible in the test record.
_SKIP_REASON = "Codex HUD removed from glance.py on 2026-07-18 (free plan can't refresh)"


@pytest.mark.skip(reason=_SKIP_REASON)
def test_codex_section_before_meters(glance_mod, monkeypatch):
    """Codex Free windows: section first, then meters under CODEX (not prior section)."""
    monkeypatch.setattr(glance, "_get", lambda *a, **k: _sample_codex_quota(plan="Free"))
    glance._COMPACT = True
    glance._RECORDS = []
    glance._CUR_SECTION = ""
    glance.section("ZENMUX", "prior")
    glance.kv_row("5-hour", 10.0, "zenmux")

    rc = glance.glance_codex()
    assert rc == 0

    codex_i = next(
        i
        for i, r in enumerate(glance._RECORDS)
        if r.get("kind") == "section" and r.get("title") == "CODEX"
    )
    sub = glance._RECORDS[codex_i].get("subtitle") or ""
    assert "Free" in sub or "plan=Free" in sub
    meters = [
        r
        for r in glance._RECORDS[codex_i + 1 :]
        if r.get("kind") == "meter"
    ]
    assert len(meters) >= 2
    assert all(m.get("section") == "CODEX" for m in meters)
    labels = {m.get("label") for m in meters}
    assert "5-hour" in labels
    assert "7-day" in labels


@pytest.mark.skip(reason=_SKIP_REASON)
def test_codex_skips_when_quota_unavailable(glance_mod, monkeypatch):
    def boom(*a, **k):
        raise OSError("tokdash down")

    monkeypatch.setattr(glance, "_get", boom)
    glance._COMPACT = True
    glance._RECORDS = []
    glance._CUR_SECTION = "ZENMUX"
    assert glance.glance_codex() == 0
    assert not any(r.get("title") == "CODEX" for r in glance._RECORDS)


def test_claude_limits_distinguish_scoped_weekly(glance_mod):
    """weekly_all vs Fable weekly_scoped must not both render as bare '7-day'."""
    glance._COMPACT = True
    glance._RECORDS = []
    glance._CUR_SECTION = "CLAUDE"
    payload = {
        "limits": [
            {
                "kind": "session",
                "percent": 14,
                "resets_at": "2026-07-17T23:20:00+00:00",
                "is_active": True,
            },
            {
                "kind": "weekly_all",
                "percent": 2,
                "resets_at": "2026-07-24T02:00:00+00:00",
                "is_active": False,
            },
            {
                "kind": "weekly_scoped",
                "percent": 0,
                "resets_at": None,
                "is_active": False,
                "scope": {"model": {"display_name": "Fable"}},
            },
        ]
    }
    assert glance._render_claude_payload(payload, mode="live") is True
    meters = [r for r in glance._RECORDS if r.get("kind") == "meter"]
    labels = [m.get("label") for m in meters]
    assert "session" in labels
    assert "7-day" in labels
    # Empty inactive Fable scoped window is noise — drop it.
    assert not any(lbl == "7-day" and m.get("pct") == 0.0 for m, lbl in zip(meters, labels) if lbl != "7-day")
    assert "7d Fable" not in labels  # dropped as noise at 0% / no reset
    assert labels.count("7-day") == 1


def test_claude_scoped_weekly_shown_when_used(glance_mod):
    glance._COMPACT = True
    glance._RECORDS = []
    glance._CUR_SECTION = "CLAUDE"
    payload = {
        "limits": [
            {
                "kind": "weekly_all",
                "percent": 10,
                "resets_at": "2026-07-24T02:00:00+00:00",
                "is_active": True,
            },
            {
                "kind": "weekly_scoped",
                "percent": 40,
                "resets_at": "2026-07-24T02:00:00+00:00",
                "is_active": True,
                "scope": {"model": {"display_name": "Fable"}},
            },
        ]
    }
    assert glance._render_claude_payload(payload, mode="live") is True
    labels = [r.get("label") for r in glance._RECORDS if r.get("kind") == "meter"]
    assert "7-day" in labels
    assert "7d Fable" in labels


@pytest.mark.skip(reason=_SKIP_REASON)
def test_codex_skips_when_no_plan_or_buckets(glance_mod, monkeypatch):
    monkeypatch.setattr(
        glance,
        "_get",
        lambda *a, **k: {
            "providers": {
                "codex": {
                    "provider": "codex",
                    "plan": None,
                    "status": "unavailable",
                    "buckets": [],
                }
            }
        },
    )
    glance._COMPACT = True
    glance._RECORDS = []
    assert glance.glance_codex() == 0
    assert not any(r.get("title") == "CODEX" for r in glance._RECORDS)


def test_open_web_dashboard_returns_true_on_success(monkeypatch):
    monkeypatch.setattr("tokdash.glance.webbrowser.open", lambda url: None)
    assert glance.open_web_dashboard() is True


def test_open_web_dashboard_returns_false_on_exception(monkeypatch):
    def raise_oserror(url):
        raise OSError("no browser")

    monkeypatch.setattr("tokdash.glance.webbrowser.open", raise_oserror)
    assert glance.open_web_dashboard() is False
