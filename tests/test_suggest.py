"""Contract tests for tokdash.suggest (single policy brain)."""
from __future__ import annotations

from datetime import date

from tokdash.suggest import build_suggest, format_glance_lines


def test_confidential_drops_free_tiers():
    data = build_suggest(
        today=date(2026, 7, 14),
        confidential=True,
        zenmux_peak_pct=20.0,
    )
    tiers = {t["tier"]: t for t in data["tiers"]}
    assert "T0" not in tiers
    assert "T1" not in tiers
    assert data["now"].startswith("NOW:")
    assert "confidential" in data["now"].lower() or "minimax" in data["now"].lower()


def test_warm_puts_flash_before_m3():
    data = build_suggest(
        today=date(2026, 7, 14),
        zenmux_peak_pct=60.0,
        confidential=False,
    )
    t2 = next(t for t in data["tiers"] if t["tier"] == "T2")
    ids = [m["id"] for m in t2["models"] if m.get("copy")]
    assert ids[0] == "deepseek/deepseek-v4-flash"
    assert "minimax/minimax-m3" in ids


def test_hot_demotes_claude_and_zai():
    data = build_suggest(
        today=date(2026, 7, 14),
        claude_peak_pct=90.0,
        zai_peak_pct=95.0,
    )
    t4 = next(t for t in data["tiers"] if t["tier"] == "T4")
    text = " ".join(m["id"] for m in t4["models"])
    assert "HOT" in text
    skip = next(t for t in data["tiers"] if t["tier"] == "SKIP")
    skip_text = " ".join(m["id"] for m in skip["models"])
    assert "HOT" in skip_text


def test_flow_budget_and_med_turns():
    data = build_suggest(
        today=date(2026, 7, 14),
        zenmux_rem5=44.0,
        zenmux_rem7=113.0,
        zenmux_max5=50.0,
        zenmux_max7=213.0,
        zenmux_peak_pct=30.0,
    )
    fb = data["flow_budget"]
    assert fb["rem7"] == 113.0
    assert fb["med_m3_turns"] == int(113 / 0.4)
    assert fb["med_flow_per_turn"] == 0.4
    assert data["copy_ready"]
    assert any(c["value"] == "minimax/minimax-m3" for c in data["copy_ready"])


def test_no_fable_or_zenmux_free_in_output():
    data = build_suggest(today=date(2026, 7, 14))
    # Fable, Freebuff, SuperGrok, and zenmux-free slugs all unwired 2026-07-22 —
    # they must not appear as model ids, copy values, or fallbacks.
    blob = str(data)
    assert "claude-fable" not in blob
    assert "Freebuff" not in blob
    assert "z-ai/glm-4.7-flash-free" not in blob
    assert "z-ai/glm-4.6v-flash-free" not in blob
    assert "zenmux-free" not in blob
    for fb in data["fallbacks"]:
        assert "zenmux-free" != fb.get("via", "")
    for entry in data["copy_ready"]:
        assert "SuperGrok" not in entry.get("label", "")
        assert "SuperGrok" not in entry.get("value", "")


def test_format_glance_lines_has_now_and_flows():
    data = build_suggest(
        today=date(2026, 7, 14),
        zenmux_rem5=40.0,
        zenmux_rem7=100.0,
        zenmux_peak_pct=10.0,
    )
    lines = format_glance_lines(data, hot_items=[], width=28)
    assert lines[0] == "SUGGEST"
    assert any(l.startswith("Flows ") for l in lines)
    assert any(l.startswith("NOW:") for l in lines)
    assert any("0.4 fl" in l for l in lines)


def test_tier_footnotes_present():
    data = build_suggest(today=date(2026, 7, 14))
    for tier in data["tiers"]:
        assert tier.get("footnote"), tier["tier"]


def test_agnes_in_t1_when_key_present():
    data = build_suggest(
        today=date(2026, 7, 14),
        confidential=False,
        has_agnes=True,
    )
    assert any("Agnes" in p["plan"] for p in data["plans"])
    t1 = next(t for t in data["tiers"] if t["tier"] == "T1")
    ids = [m["id"] for m in t1["models"]]
    assert "agnes-2.0-flash" in ids
    assert any(c["value"] == "agnes-2.0-flash" for c in data["copy_ready"])


def test_agnes_hidden_when_confidential():
    data = build_suggest(
        today=date(2026, 7, 14),
        confidential=True,
        has_agnes=True,
    )
    assert not any("Agnes" in p["plan"] for p in data["plans"])


def test_schema_version_and_pick_paid_default():
    data = build_suggest(
        today=date(2026, 7, 14),
        confidential=False,
        zenmux_peak_pct=20.0,
    )
    assert data["schema_version"] == 1
    pick = data["pick"]
    assert pick["model"] == "minimax/minimax-m3"
    assert pick["tier"] == "T2"
    assert pick["reason_code"] == "paid_default"
    assert pick["confidential_ok"] is True
    assert pick["via"] == "zenmux"
    models = [f["model"] for f in data["fallbacks"]]
    assert "qwen/qwen3.7-plus" in models


def test_pick_confidential_paid_default():
    data = build_suggest(
        today=date(2026, 7, 14),
        confidential=True,
        zenmux_peak_pct=20.0,
    )
    pick = data["pick"]
    assert pick["model"] == "minimax/minimax-m3"
    assert pick["reason_code"] == "confidential"
    assert pick["confidential_ok"] is True


def test_pick_warm_cheap():
    data = build_suggest(
        today=date(2026, 7, 14),
        zenmux_peak_pct=60.0,
        confidential=False,
    )
    pick = data["pick"]
    assert pick["model"] == "deepseek/deepseek-v4-flash"
    assert pick["reason_code"] == "warm_cheap"
    assert any(f["model"] == "minimax/minimax-m3" for f in data["fallbacks"])


def test_pick_hot_pause():
    data = build_suggest(
        today=date(2026, 7, 14),
        zenmux_peak_pct=90.0,
        confidential=False,
    )
    pick = data["pick"]
    assert pick["reason_code"] == "hot_pause"
    assert pick["tier"] in {"T1", "T2"}
    # paid M3 must not be the pick while hot
    assert pick["model"] != "minimax/minimax-m3"


def test_codex_free_low_peak_in_t4_and_plans():
    data = build_suggest(
        today=date(2026, 7, 17),
        codex_plan="Free",
        codex_peak_pct=20.0,
        confidential=False,
    )
    assert any("Codex" in p["plan"] and "Free" in p["plan"] for p in data["plans"])
    t4 = next(t for t in data["tiers"] if t["tier"] == "T4")
    ids = " ".join(m["id"] for m in t4["models"])
    assert "Codex Free" in ids
    assert not any("HOT" in m["id"] for m in t4["models"] if "Codex" in m["id"])
    assert any("Codex Free" in s for s in data["use_next"])


def test_codex_free_hot_demotes_to_skip():
    data = build_suggest(
        today=date(2026, 7, 17),
        codex_plan="Free",
        codex_peak_pct=92.0,
        confidential=False,
    )
    t4 = next(t for t in data["tiers"] if t["tier"] == "T4")
    assert any("Codex HOT" in m["id"] for m in t4["models"])
    skip = next(t for t in data["tiers"] if t["tier"] == "SKIP")
    skip_ids = " ".join(m["id"] for m in skip["models"])
    assert "Codex HOT" in skip_ids
    assert any("Codex HOT" in s for s in data["use_next"])


def test_codex_absent_when_no_plan_or_peak():
    data = build_suggest(today=date(2026, 7, 17))
    assert not any("Codex" in p["plan"] for p in data["plans"])
