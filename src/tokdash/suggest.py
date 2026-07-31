"""Plan → model suggestions for tokdash (Starter / free / trial stack).

Single policy brain for the dashboard Suggest tab (`/api/suggest`) and the
ambient glance SUGGEST rail. Rates last verified 2026-07-14 against ZenMux
public /api/v1/models + generation billing (list rate = flow burn).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence


# ZenMux Starter list rates ($/M in/out), first tier. Verified 2026-07-14.
ZENMUX_MODELS: List[Dict[str, Any]] = [
    {
        "id": "deepseek/deepseek-v4-flash",
        "role": "volume / reliability-first",
        "in": 0.14,
        "out": 0.28,
        "note": "reliability / cost-first",
        "priority": 1,
    },
    {
        "id": "minimax/minimax-m3",
        "role": "aider-only · tool calls broken on ZenMux",
        "in": 0.1373,
        "out": 0.5492,
        "note": "structured tool calls leak tokens (2026-07-18 probes)",
        "priority": 2,
    },
    {
        "id": "qwen/qwen3.7-plus",
        "role": "same-cost peer",
        "in": 0.1373,
        "out": 0.5492,
        "note": "strong general · 1M ctx",
        "priority": 2,
    },
    {
        "id": "kuaishou/kat-coder-pro-v2",
        "role": "coding peer",
        "in": 0.1373,
        "out": 0.5492,
        "note": "coding specialist",
        "priority": 2,
    },
    {
        "id": "deepseek/deepseek-v4-flash",
        "role": "cheapest strong paid",
        "in": 0.14,
        "out": 0.28,
        "note": "reliability / cost-first",
        "priority": 3,
    },
    {
        "id": "deepseek/deepseek-v4-pro",
        "role": "hard escalation only",
        "in": 0.435,
        "out": 0.87,
        "note": "~3.1× Flash · kept on Starter, not default",
        "priority": 4,
    },
    # z-ai/glm-5.2 deliberately omitted from Starter wiring (2026-07-15):
    # ~8× Flash flows; historical ZenMux volume was ~99% this model.
]

# ZENMUX_FREE removed 2026-07-22 — no free slugs wired in active rotation.

# Fable unwired 2026-07-22 per user — no subscription.
AVOID_ON_STARTER = [
    "anthropic/claude-opus-4.8 ($5/$25)",
    "openai/gpt-5.5 ($5/$30)",
    "z-ai/glm-5.2 ($0.98/$3.08) — unwired from Starter harnesses 2026-07-15",
    "minimax/minimax-m2.5 · m2.7 (~2.8× Flash, worse than M3) — unwired",
]

# ~0.4 flows ≈ one medium M3 agent turn (≈50k in + 10k out at list rates).
MED_M3_FLOW_PER_TURN = 0.4
FLOW_USD = 0.03283
HOT = 85.0
WARM = 55.0
SCHEMA_VERSION = 1

# Fixed reason_code set for agent consumers (Phase 1).
REASON_TRIAL_BURN = "trial_burn"
REASON_FREE_OVERFLOW = "free_overflow"
REASON_PAID_DEFAULT = "paid_default"
REASON_WARM_CHEAP = "warm_cheap"
REASON_HOT_PAUSE = "hot_pause"
REASON_CONFIDENTIAL = "confidential"
REASON_INTERACTIVE = "interactive"

TIER_FOOTNOTES = {
    "T0": "Reserved (no free tier currently — SuperGrok ended 2026-07-18).",
    "T1": "Free overflow (Agnes serial · IAMHC — no other free lanes currently wired).",
    "T2": "List rate = flow burn on Starter (verified 2026-07-14). M3 bakeoff default.",
    "T3": "Escalate only when quality needs it — Pro is ~3.1× Flash flows.",
    "T4": "Interactive T1 on plan quota, not headless default.",
    "SKIP": "Sub-killers on ZenMux Starter: Opus/GPT frontier + GLM-5.2 volume.",
}


def _parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _env_date(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip() or default


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _status_from_peak(peak: Optional[float]) -> str:
    if peak is None:
        return "active"
    if peak >= HOT:
        return "hot"
    if peak >= WARM:
        return "warm"
    return "active"


def build_suggest(
    *,
    today: Optional[date] = None,
    zenmux_peak_pct: Optional[float] = None,
    claude_peak_pct: Optional[float] = None,
    clinepass_peak_pct: Optional[float] = None,
    zai_peak_pct: Optional[float] = None,
    qwencloud_peak_pct: Optional[float] = None,
    codex_peak_pct: Optional[float] = None,
    codex_plan: Optional[str] = None,
    zenmux_rem5: Optional[float] = None,
    zenmux_rem7: Optional[float] = None,
    zenmux_max5: Optional[float] = None,
    zenmux_max7: Optional[float] = None,
    zenmux_reset5: Optional[str] = None,
    zenmux_reset7: Optional[str] = None,
    has_iamhc: bool = True,
    # has_freebuff removed 2026-07-22 per user — Freebuff not in active rotation.
    has_agnes: Optional[bool] = None,
    confidential: Optional[bool] = None,
    # supergrok_end / supergrok_proxy removed 2026-07-22 — trial lapsed 2026-07-18.
    zenmux_end: Optional[str] = None,
    clinepass_end: Optional[str] = None,
) -> Dict[str, Any]:
    """Return structured plan→model suggestions for API / UI / glance."""
    today = today or date.today()
    confidential = (
        _env_flag("TOKDASH_CONFIDENTIAL", False)
        if confidential is None
        else bool(confidential)
    )
    if has_agnes is None:
        has_agnes = bool(os.environ.get("AGNES_API_KEY", "").strip())
    else:
        has_agnes = bool(has_agnes)
    zenmux_end = zenmux_end or _env_date("TOKDASH_ZENMUX_END", "2026-08-04")
    clinepass_end = clinepass_end or _env_date("TOKDASH_CLINEPASS_END", "2026-08-11")

    plans: List[Dict[str, Any]] = []

    zm_end = _parse_date(zenmux_end)
    zm_days = (zm_end - today).days if zm_end else None
    cp_end = _parse_date(clinepass_end)
    cp_days = (cp_end - today).days if cp_end else None

    # --- SuperGrok trial removed 2026-07-18 — wiring unwired, no longer suggested. ---


    # --- Agnes free serial (Singapore hub; no public quota API) ---
    if has_agnes and not confidential:
        plans.append(
            {
                "plan": "Agnes free serial",
                "status": "active",
                "use_when": "non-confidential free serial aider / one agent loop",
                "models": [
                    {
                        "id": "agnes-2.0-flash",
                        "role": "free serial executor",
                        "via": "https://apihub.agnes-ai.com/v1",
                        "cost": "$0 · ~20 RPM · concurrency wall if parallel",
                        "copy": "agnes-2.0-flash",
                    }
                ],
                "action": "prefer for free serial; not a multi-agent free pool",
                "note": "bakeoff 2026-07-15: quality tie, speed win vs Hy3/DS Flash",
            }
        )


    # --- ZenMux Starter ---
    zm_status = _status_from_peak(zenmux_peak_pct)
    models = [{**m, "copy": m.get("copy") or m.get("id")} for m in ZENMUX_MODELS]
    if zm_status == "hot":
        action = "pause paid volume — wait for flow reset or use free/local"
    elif zm_status == "warm":
        action = "prefer DS V4 Flash / free before M3 to save flows"
    else:
        action = "DS V4 Flash when warm; no volume default (defaults moved to ClinePass DS V4 Pro)"

    med_turns = None
    if zenmux_rem7 is not None:
        med_turns = max(0, int(float(zenmux_rem7) / MED_M3_FLOW_PER_TURN))

    flow_budget: Dict[str, Any] = {
        "flow_usd": FLOW_USD,
        "flows_7d_cap": 213,
        "rem5": zenmux_rem5,
        "rem7": zenmux_rem7,
        "max5": zenmux_max5 if zenmux_max5 is not None else 50,
        "max7": zenmux_max7 if zenmux_max7 is not None else 213,
        "reset5": zenmux_reset5,
        "reset7": zenmux_reset7,
        "med_m3_turns": med_turns,
        "med_flow_per_turn": MED_M3_FLOW_PER_TURN,
        "peak_pct": zenmux_peak_pct,
        "status": zm_status,
    }

    plans.append(
        {
            "plan": "ZenMux Starter",
            "status": zm_status,
            "expires": zenmux_end,
            "days_left": zm_days,
            "peak_pct": zenmux_peak_pct,
            "flow_usd": FLOW_USD,
            "flows_7d": 213,
            "flow_budget": flow_budget,
            "use_when": "confidential · paid delegation",
            "models": models,
            "avoid": AVOID_ON_STARTER,
            "action": action,
            "note": "list rate = flow burn (verified 2026-07-14); free slugs need PAYG key",
        }
    )

    # --- Z.ai coding plan ---
    zai_status = "hot" if (zai_peak_pct is not None and zai_peak_pct >= HOT) else "active"
    plans.append(
        {
            "plan": "Z.ai GLM Coding Lite",
            "status": zai_status,
            "expires": "2026-09-18",
            "peak_pct": zai_peak_pct,
            "use_when": "interactive T1 orchestrator (not headless default)",
            "models": [
                {
                    "id": "glm-5.2",
                    "role": "T1 interactive",
                    "via": "Z.ai direct",
                    "cost": "flat plan quota",
                    "copy": "glm-5.2",
                }
            ],
            "action": "use interactively; headless only with anti-deliberation + oracle",
        }
    )

    # --- Qwen Cloud Token Plan ---
    qc_status = (
        "hot" if (qwencloud_peak_pct is not None and qwencloud_peak_pct >= HOT)
        else "warm" if (qwencloud_peak_pct is not None and qwencloud_peak_pct >= WARM)
        else "active"
    )
    # Night discount: 22:00–08:00 UTC+8 = 14:00–00:00 UTC
    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    cst = timezone(timedelta(hours=8))
    now_cst = now_utc.astimezone(cst)
    in_night_window = now_cst.hour >= 22 or now_cst.hour < 8
    night_note = (
        "80% night discount active (22–08 UTC+8)"
        if in_night_window
        else f"night discount at 22:00 CST ({22 - now_cst.hour}h away)" if now_cst.hour < 22
        else "night discount ended at 08:00"
    )
    plans.append(
        {
            "plan": "Qwen Cloud Token Plan",
            "status": qc_status,
            "peak_pct": qwencloud_peak_pct,
            "use_when": "cheap overflow · night discount 22–08 UTC+8",
            "models": [
                {
                    "id": "qwen3.8-max-preview",
                    "role": "10× usage preview",
                    "via": "Qwen Cloud SG",
                    "cost": "Token Plan credits · 90% off promo",
                    "copy": "qwen3.8-max-preview (10× preview)",
                },
                {
                    "id": "qwen3.7-plus",
                    "role": "general workhorse",
                    "via": "Qwen Cloud SG",
                    "cost": "Token Plan credits",
                    "copy": "qwen3.7-plus",
                },
                {
                    "id": "glm-5.2 / deepseek-v4-pro",
                    "role": "hard escalation",
                    "via": "Qwen Cloud SG",
                    "cost": "Token Plan credits",
                    "copy": "glm-5.2 / deepseek-v4-pro",
                },
            ],
            "action": night_note,
            "note": "Lite $6/mo (700cr/5h, 2500cr/7d); qwen3.8-max-preview = 10× credits promo",
        }
    )

    # --- Claude Pro ---
    cl_status = "hot" if (claude_peak_pct is not None and claude_peak_pct >= HOT) else "active"
    plans.append(
        {
            "plan": "Claude Pro",
            "status": cl_status,
            "peak_pct": claude_peak_pct,
            "use_when": "hard design / escape-hatch review — not default sprint",
            "models": [
                {
                    "id": "claude-sonnet / opus",
                    "role": "T1 escape hatch",
                    "cost": "plan quota",
                    "copy": "claude-sonnet",
                }
            ],
            "action": "keep burn near zero; delegate execution elsewhere",
        }
    )

    # --- Codex / ChatGPT plan (Free / Plus / Pro…) — live windows only, no invented caps ---
    codex_plan_raw = (codex_plan or "").strip()
    codex_plan_key = codex_plan_raw.lower().replace(" ", "_")
    codex_is_free = codex_plan_key in {"free", "chatgpt_free"} or codex_plan_key.endswith("_free")
    # Treat blank plan as unknown; still surface when peak known (API may omit label).
    codex_present = bool(codex_plan_raw) or codex_peak_pct is not None
    codex_status = _status_from_peak(codex_peak_pct) if codex_present else "absent"
    if codex_present:
        plan_label = codex_plan_raw or "Codex"
        if codex_status == "hot":
            codex_action = "pause Codex interactive — wait for 5h/7d window reset"
        elif codex_status == "warm":
            codex_action = "Codex warm — prefer free/local or ZenMux for volume"
        elif codex_is_free:
            codex_action = "Codex Free interactive only; not a headless free pool"
        else:
            codex_action = "Codex plan interactive; demote when windows hot"
        plans.append(
            {
                "plan": f"Codex / ChatGPT ({plan_label})",
                "status": codex_status,
                "peak_pct": codex_peak_pct,
                "use_when": "interactive plan-app work (desktop/CLI), not serial free overflow",
                "models": [
                    {
                        "id": "codex / chatgpt desktop",
                        "role": "interactive plan app",
                        "via": "Codex host",
                        "cost": f"plan={plan_label} · live windows",
                        "copy": "",
                    }
                ],
                "action": codex_action,
                "note": "limits come from quota 5h/7d — do not hardcode Free caps",
            }
        )

    # --- ClinePass ---
    cp_status = (
        "hot"
        if (clinepass_peak_pct is not None and clinepass_peak_pct >= HOT)
        else "promo-month"
    )
    plans.append(
        {
            "plan": "ClinePass Monthly (student)",
            "status": cp_status,
            "expires": clinepass_end,
            "days_left": cp_days,
            "peak_pct": clinepass_peak_pct,
            "use_when": "open-weight overflow this promo month (canceled — lapse Aug 11)",
            "models": [
                {
                    "id": "cline-pass/deepseek-v4-pro",
                    "role": "default daily executor",
                    "cost": "plan limits (not USD)",
                    "copy": "cline-pass/deepseek-v4-pro",
                },
                {
                    "id": "cline-pass/deepseek-v4-flash",
                    "role": "volume / cheap serial",
                    "cost": "plan limits",
                    "copy": "cline-pass/deepseek-v4-flash",
                },
                {
                    "id": "cline-pass/deepseek-v4-pro",
                    "role": "agent loops (proven)",
                    "cost": "plan limits",
                    "copy": "cline-pass/deepseek-v4-pro",
                },
                {
                    "id": "cline-pass/qwen3.7-plus",
                    "role": "general peer",
                    "cost": "plan limits",
                    "copy": "cline-pass/qwen3.7-plus",
                },
                {
                    "id": "cline-pass/glm-5.2",
                    "role": "hard-only flagship",
                    "cost": "plan limits · fat prompts burn weekly %",
                    "copy": "cline-pass/glm-5.2",
                },
            ],
            "action": "default DS V4 Pro; Flash for volume; GLM hard-only; no renew Aug 11",
        }
    )

    # ── Tier ladder ──────────────────────────────────────────────────────────
    tiers: List[Dict[str, Any]] = []
    t0_models: List[Dict[str, Any]] = []
    # T0 reserved (no free tier currently) — SuperGrok trial ended 2026-07-18.

    if not confidential:
        t1_models: List[Dict[str, Any]] = []
        if has_agnes:
            t1_models.insert(
                0,
                {
                    "id": "agnes-2.0-flash",
                    "via": "apihub.agnes-ai.com",
                    "note": "free serial · ~20 RPM · not parallel",
                    "copy": "agnes-2.0-flash",
                },
            )
        if has_iamhc:
            t1_models.append(
                {
                    "id": "IAMHC",
                    "via": "free providers",
                    "note": "capacity varies",
                    "copy": "",
                }
            )
        tiers.append(
            {
                "tier": "T1",
                "name": "Free overflow",
                "footnote": TIER_FOOTNOTES["T1"],
                "models": t1_models,
            }
        )

    if zm_status == "hot":
        t2_note = "ZenMux HOT — prefer free/local"
        t2_models = [
            {"id": "(pause paid M3)", "via": "zenmux", "note": "wait for flow reset", "copy": ""},
        ]
    elif zm_status == "warm":
        t2_note = "warm — cheap-strong first"
        t2_models = [
            {
                "id": "deepseek/deepseek-v4-flash",
                "via": "zenmux",
                "note": "$0.14/$0.28",
                "copy": "deepseek/deepseek-v4-flash",
            },
            {
                "id": "minimax/minimax-m3",
                "via": "zenmux",
                "note": "if quality needs",
                "copy": "minimax/minimax-m3",
            },
        ]
    else:
        t2_note = "default paid workhorse"
        t2_models = [
            {
                "id": "minimax/minimax-m3",
                "via": "zenmux",
                "note": "default · $0.137/$0.549",
                "copy": "minimax/minimax-m3",
            },
            {
                "id": "qwen/qwen3.7-plus",
                "via": "zenmux",
                "note": "same-cost peer",
                "copy": "qwen/qwen3.7-plus",
            },
            {
                "id": "kuaishou/kat-coder-pro-v2",
                "via": "zenmux",
                "note": "coding peer",
                "copy": "kuaishou/kat-coder-pro-v2",
            },
        ]
    if zenmux_rem7 is not None and zm_status != "hot":
        t2_models.append(
            {
                "id": f"budget {float(zenmux_rem7):.0f} fl /7d",
                "via": "zenmux",
                "note": f"~{med_turns} med M3 turns · 0.4 fl/turn",
                "copy": "",
            }
        )
    tiers.append(
        {
            "tier": "T2",
            "name": f"Paid workhorse ({t2_note})",
            "footnote": TIER_FOOTNOTES["T2"],
            "models": t2_models,
        }
    )

    if zm_status != "hot":
        tiers.append(
            {
                "tier": "T3",
                "name": "Escalate (hard only)",
                "footnote": TIER_FOOTNOTES["T3"],
                "models": [
                    {
                        "id": "deepseek/deepseek-v4-pro",
                        "via": "zenmux",
                        "note": "$0.435/$0.87",
                        "copy": "deepseek/deepseek-v4-pro",
                    },
                    {
                        "id": "qwen/qwen3.7-max",
                        "via": "zenmux",
                        "note": "if needed",
                        "copy": "qwen/qwen3.7-max",
                    },
                ],
            }
        )

    t4_models: List[Dict[str, Any]] = []
    t4_hot: List[Dict[str, Any]] = []
    if zai_status != "hot":
        t4_models.append(
            {
                "id": "glm-5.2",
                "via": "Z.ai direct",
                "note": "orchestrator · not headless default",
                "copy": "glm-5.2",
            }
        )
    elif zai_peak_pct is not None:
        t4_hot.append(
            {
                "id": f"Z.ai HOT {zai_peak_pct:.0f}%",
                "via": "Z.ai",
                "note": "avoid until reset",
                "copy": "",
            }
        )
    if cl_status != "hot":
        t4_models.append(
            {
                "id": "claude sonnet/opus",
                "via": "Claude Pro",
                "note": "hard review only",
                "copy": "claude-sonnet",
            }
        )
    elif claude_peak_pct is not None:
        t4_hot.append(
            {
                "id": f"Claude HOT {claude_peak_pct:.0f}%",
                "via": "Claude Pro",
                "note": "avoid until reset",
                "copy": "",
            }
        )
    if codex_present and codex_status != "hot":
        free_tag = "Free" if codex_is_free else (codex_plan_raw or "plan")
        t4_models.append(
            {
                "id": f"Codex {free_tag}",
                "via": "Codex / ChatGPT desktop",
                "note": "interactive plan windows · not headless default",
                "copy": "",
            }
        )
    elif codex_present and codex_peak_pct is not None:
        t4_hot.append(
            {
                "id": f"Codex HOT {codex_peak_pct:.0f}%",
                "via": "Codex / ChatGPT",
                "note": "avoid until 5h/7d reset",
                "copy": "",
            }
        )
    if cp_status != "hot":
        t4_models.append(
            {
                "id": "ClinePass open models",
                "via": "api.cline.bot",
                "note": "promo month",
                "copy": "",
            }
        )
    if t4_models or t4_hot:
        tiers.append(
            {
                "tier": "T4",
                "name": "Interactive T1",
                "footnote": TIER_FOOTNOTES["T4"],
                "models": t4_models + t4_hot,
            }
        )

    skip_models = [
        {
            "id": "z-ai/glm-5.2 on ZenMux",
            "via": "zenmux",
            "note": "~8.6× Flash flows",
            "copy": "",
        },
        {
            "id": "claude-opus · gpt-5.5",
            "via": "zenmux",
            "note": "sub-killers",
            "copy": "",
        },
    ]
    for item in t4_hot:
        skip_models.append(item)
    tiers.append(
        {
            "tier": "SKIP",
            "name": "Avoid volume on Starter",
            "footnote": TIER_FOOTNOTES["SKIP"],
            "models": skip_models,
        }
    )

    # Structured pick + fallbacks (agent-stable); now/use_next derived from same rules.
    pick: Dict[str, Any]
    fallbacks: List[Dict[str, Any]] = []
    use_next: List[str] = []

    def _entry(
        *,
        model: str,
        via: str,
        tier: str,
        reason_code: str,
        reason: str,
        confidential_ok: bool,
        expires: Optional[str] = None,
    ) -> Dict[str, Any]:
        e: Dict[str, Any] = {
            "model": model,
            "via": via,
            "tier": tier,
            "reason_code": reason_code,
            "reason": reason,
            "confidential_ok": confidential_ok,
        }
        if expires:
            e["expires"] = expires
        return e

    if confidential:
        if zm_status == "hot":
            pick = _entry(
                model="",
                via="",
                tier="T2",
                reason_code=REASON_HOT_PAUSE,
                reason="ZenMux HOT — wait reset / local only (confidential)",
                confidential_ok=True,
            )
            use_next.append(f"NOW: {pick['reason']}")
        elif zm_status == "warm":
            pick = _entry(
                model="deepseek/deepseek-v4-flash",
                via="zenmux",
                tier="T2",
                reason_code=REASON_WARM_CHEAP,
                reason="DS V4 Flash (confidential · warm flows)",
                confidential_ok=True,
            )
            fallbacks.append(
                _entry(
                    model="minimax/minimax-m3",
                    via="zenmux",
                    tier="T2",
                    reason_code=REASON_PAID_DEFAULT,
                    reason="M3 only if quality needs",
                    confidential_ok=True,
                )
            )
            use_next.append("NOW: DS V4 Flash (confidential · warm)")
            use_next.append("ZenMux M3 only if quality needs")
        else:
            pick = _entry(
                model="minimax/minimax-m3",
                via="zenmux",
                tier="T2",
                reason_code=REASON_CONFIDENTIAL,
                reason="paid default on confidential path",
                confidential_ok=True,
            )
            fallbacks.extend(
                [
                    _entry(
                        model="qwen/qwen3.7-plus",
                        via="zenmux",
                        tier="T2",
                        reason_code=REASON_PAID_DEFAULT,
                        reason="same-cost peer",
                        confidential_ok=True,
                    ),
                ]
            )
            use_next.append("NOW: minimax/minimax-m3 (confidential)")
            use_next.append("peers: Qwen3.7-Plus · KAT")
    else:
        # No T0 free pick (free-router retired 2026-07-20); default to ZenMux-status branches.
        if zm_status == "hot":
            pick = _entry(
                model="",
                via="",
                tier="T2",
                reason_code=REASON_HOT_PAUSE,
                reason="ZenMux HOT — pause paid; wait reset or use local",
                confidential_ok=False,
            )
            use_next.append("ZenMux HOT — pause sub volume")
        elif zm_status == "warm":
            pick = _entry(
                model="deepseek/deepseek-v4-flash",
                via="zenmux",
                tier="T2",
                reason_code=REASON_WARM_CHEAP,
                reason="warm flows — cheap-strong first",
                confidential_ok=True,
            )
            fallbacks.append(
                _entry(
                    model="minimax/minimax-m3",
                    via="zenmux",
                    tier="T2",
                    reason_code=REASON_PAID_DEFAULT,
                    reason="if quality needs",
                    confidential_ok=True,
                )
            )
            use_next.append("ZenMux warm — prefer DS V4 Flash / free first")
        else:
            pick = _entry(
                model="minimax/minimax-m3",
                via="zenmux",
                tier="T2",
                reason_code=REASON_PAID_DEFAULT,
                reason="default paid executor",
                confidential_ok=True,
            )
            fallbacks.extend(
                [
                    _entry(
                        model="qwen/qwen3.7-plus",
                        via="zenmux",
                        tier="T2",
                        reason_code=REASON_PAID_DEFAULT,
                        reason="same-cost peer",
                        confidential_ok=True,
                    ),
                ]
            )
            use_next.append("ZenMux MiniMax M3 — default paid executor")

    # Human NOW line from structured pick (single source).
    if pick.get("model"):
        now_line = f"NOW: {pick['model']}"
        if pick.get("reason_code") == REASON_CONFIDENTIAL:
            now_line = "NOW: minimax/minimax-m3 (confidential)"
        elif pick.get("reason_code") == REASON_WARM_CHEAP:
            if confidential:
                now_line = "NOW: DS V4 Flash (confidential · warm)"
            else:
                now_line = "NOW: deepseek-v4-flash (warm flows)"
        elif pick.get("reason_code") == REASON_HOT_PAUSE:
            now_line = (
                "NOW: ZenMux HOT — wait reset / local only"
                if confidential
                else "NOW: ZenMux HOT — free/local only"
            )
        elif pick.get("reason_code") == REASON_PAID_DEFAULT:
            now_line = "NOW: minimax/minimax-m3 (paid default)"
    else:
        now_line = f"NOW: {pick.get('reason') or 'no pick'}"

    if zai_status != "hot":
        use_next.append("Z.ai GLM-5.2 interactive T1")
        if not any(f.get("model") == "glm-5.2" for f in fallbacks):
            fallbacks.append(
                _entry(
                    model="glm-5.2",
                    via="Z.ai direct",
                    tier="T4",
                    reason_code=REASON_INTERACTIVE,
                    reason="interactive T1 orchestrator",
                    confidential_ok=True,
                )
            )
    if cl_status != "hot":
        use_next.append("Claude plan only for hard review")
    else:
        use_next.append(f"Claude HOT {claude_peak_pct:.0f}% — avoid")

    if codex_present:
        if codex_status == "hot":
            use_next.append(
                f"Codex HOT {codex_peak_pct:.0f}% — wait window reset"
                if codex_peak_pct is not None
                else "Codex HOT — wait window reset"
            )
        elif codex_status == "warm":
            use_next.append(
                f"Codex warm {codex_peak_pct:.0f}% — spare interactive only"
                if codex_peak_pct is not None
                else "Codex warm — spare interactive only"
            )
        elif codex_is_free:
            use_next.append("Codex Free interactive (live windows; not free overflow pool)")
        else:
            use_next.append(f"Codex {codex_plan_raw or 'plan'} interactive when needed")

    # de-dupe use_next
    seen: set[str] = set()
    uniq_next: List[str] = []
    for s in use_next:
        if s in seen:
            continue
        seen.add(s)
        uniq_next.append(s)

    # de-dupe fallbacks by model, drop if same as pick
    seen_fb: set[str] = set()
    uniq_fb: List[Dict[str, Any]] = []
    pick_model = str(pick.get("model") or "")
    for f in fallbacks:
        mid = str(f.get("model") or "")
        if not mid or mid == pick_model or mid in seen_fb:
            continue
        seen_fb.add(mid)
        uniq_fb.append(f)
    fallbacks = uniq_fb[:5]

    deadlines: List[Dict[str, Any]] = []
    for label, end_str, days in [
        ("ZenMux Starter", zenmux_end, zm_days),
        ("ClinePass promo month", clinepass_end, cp_days),
    ]:
        if days is not None and -3 <= days <= 30:
            deadlines.append({"label": label, "date": end_str, "days_left": days})

    # Free model trial windows (hardcoded — no API available)
    _today = today
    for label, end_date_str in [
        ("Ling 3.0 Flash free", "2026-08-03"),
        ("Laguna S 2.1 free (Nous)", "2026-08-04"),
        ("North Mini Code free", "2026-08-17"),
        ("Step 3.7 Flash free", "2026-08-04"),
        ("Qwen Cloud night disc.", "2026-09-30"),
    ]:
        try:
            end_dt = date.fromisoformat(end_date_str)
            d = (end_dt - _today).days
            if -3 <= d <= 60:
                deadlines.append({"label": label, "date": end_date_str, "days_left": d})
        except Exception:
            pass
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": today.isoformat(),
        "confidential": confidential,
        "pick": pick,
        "fallbacks": fallbacks,
        "now": now_line,
        "use_next": uniq_next,
        "tiers": tiers,
        "plans": plans,
        "flow_budget": flow_budget,
        "deadlines": deadlines,
        "routing_summary": [
            "T0 reserved (no free tier currently — SuperGrok ended 2026-07-18)",
            "T1 free overflow (Agnes serial · IAMHC)"
            + (" — OFF in confidential" if confidential else ""),
            "T2 paid workhorse: minimax-m3 default on ZenMux (Flash when warm)",
            "T3 escalate: deepseek-v4-pro only when needed",
            "T4 interactive T1: Z.ai GLM-5.2 / Claude plan / Codex plan (demote if HOT)",
            "SKIP: GLM-5.2/Claude-GPT volume on ZenMux Starter flows",
            "T0 reserved (no active free tier — SuperGrok ended 2026-07-18, free-router retired 2026-07-20)"
        ],
        "source": "stack-planning 2026-07-14 live ZenMux rates + trial docs",
        "copy_ready": [
            {"label": "M3 default", "value": "minimax/minimax-m3"},
            {"label": "DS Flash", "value": "deepseek/deepseek-v4-flash"},
            {"label": "Agnes free serial", "value": "agnes-2.0-flash"},
        ],
    }


def format_glance_lines(
    data: Dict[str, Any],
    *,
    hot_items: Optional[Sequence[str]] = None,
    warn_items: Optional[Sequence[str]] = None,
    width: int = 28,
) -> List[str]:
    """Render build_suggest() payload as ambient glance right-rail lines."""
    w = max(20, width)
    lines: List[str] = []
    lines.append("SUGGEST")
    lines.append("─" * w)

    fb = data.get("flow_budget") or {}
    rem5, rem7 = fb.get("rem5"), fb.get("rem7")
    if rem7 is not None:
        fl5 = f"{float(rem5):.0f}" if rem5 is not None else "?"
        lines.append(f"Flows 5h {fl5} · 7d {float(rem7):.0f} left")
        lines.append("─" * w)

    now = str(data.get("now") or "").strip()
    if now:
        # Strip leading "NOW: " for the rail header if present
        body = now[5:].strip() if now.upper().startswith("NOW:") else now
        lines.append(f"NOW: {body}"[: w + 2])
        lines.append("─" * w)

    if data.get("confidential"):
        lines.append("mode: confidential")

    tiers = data.get("tiers") or []
    if tiers:
        for tier in tiers:
            t = str(tier.get("tier") or "")
            name = str(tier.get("name") or "")
            # Compact header: "T0 free power" not full name if long
            if t == "T0":
                header = "T0 free power"
            elif t == "T1":
                header = "T1 free overflow"
            elif t == "T2":
                header = "T2 paid workhorse"
            elif t == "T3":
                header = "T3 escalate"
            elif t == "T4":
                header = "T4 interactive"
            elif t == "SKIP":
                header = "Skip / avoid"
            else:
                header = f"{t} {name}".strip()
            lines.append(header[:w])
            for m in (tier.get("models") or [])[:3]:
                mid = str(m.get("id") or "")
                note = str(m.get("note") or "")
                # Prefer short id + short note
                if note and len(mid) < 18:
                    s = f"· {mid}  {note.split('·')[0].strip()}"
                else:
                    s = f"· {mid}"
                lines.append(s[:w])
    else:
        lines.append("Tiers")
        lines.append("· no live plans detected")

    lines.append("")
    lines.append("Skip / hot")
    hot = list(hot_items or [])
    if hot:
        for s in hot[:3]:
            lines.append(f"· {s}"[:w])
    else:
        lines.append("· none ≥85%")
    # Always remind Starter sub-killers
    lines.append("· no GLM-5.2/Claude-GPT vol")

    lines.append("")
    lines.append("Deadlines")
    shown = 0
    for d in data.get("deadlines") or []:
        days = d.get("days_left")
        if days is None or days < 0 or days > 60:
            continue
        label = str(d.get("label") or "").split()[0][:10]
        date_s = str(d.get("date") or "")[:10]
        lines.append(f"· {label} → {date_s}"[:w])
        shown += 1
        if shown >= 5:
            break
    if shown == 0:
        lines.append("· none ≤14d")

    if warn_items:
        lines.append("")
        lines.append("Alerts")
        for wmsg in list(warn_items)[:2]:
            lines.append(f"· {str(wmsg)[: w - 2]}")

    lines.append("")
    lines.append("Tip: Suggest tab = full map")
    lines.append("· ~0.4 fl / med M3 turn")
    lines.append("· claim IAMHC free credits daily")
    return lines


# =============================================================================
# Prototype scoring layer (Phase 1, ported 2026-07-28).
#
# The build_suggest() policy brain above is unchanged and remains the source of
# the existing /api/suggest pick/fallbacks/tiers contract (consumed by the web
# Suggest tab and the TUI SUGGEST rail in glance.py). The functions below port
# the generic numeric scorer from kdash-ts-prototype/src/core/state.ts and are
# surfaced as ADDITIONAL keys (recommendations / free_pool / alerts) on the
# /api/suggest response. Existing keys and behaviour are untouched.
#
# Honest gaps vs the prototype (kdash has no telemetry producer for these yet):
#   - latency_ms / error_rate default to 0  -> their penalty terms are no-ops.
#   - spend_24h is not tracked anywhere     -> runway_days is None, runway
#                                              alerts do not fire.
#   - On the default persistent DB path, amount_remaining / expires_at are not
#     stored (schema only persists 11 cols), so balance / funds_ok / expiry
#     alerts are optimistic (None -> ok) rather than invented. The terms still
#     engage the moment a fresh in-memory observation carries the field.
# All ported rules are verbatim against state.ts:19-206; numbers always come
# from the live engine, never from seeded mock data.
# =============================================================================

# Tier ladder for the recommend() loop. FREE is intentionally excluded here
# (mirrors prototype types.ts TIERS): free-tier models surface only via
# free_pool_view, never as a Recommendation.
SCORE_TIERS: List[str] = ["T1", "T2", "T3", "VISION"]


# Curated registry of models the scorer evaluates. kdash is provider-centric,
# so there is no auto-discoverable model inventory; this list is the active set
# and is the one maintenance surface for the scoring layer. Each entry carries
# the fields kdash does NOT collect (tier / source / max_concurrency); runtime
# fields (quota_pct, balance, cost_out, health, enabled) are joined at call
# time from quota_state() / pricing_db.json in build_scored_state().
#
# `provider` is the kdash quota_state() provider key used to join live quota;
# `pricing_slug` (defaults to slug) is the key looked up in pricing_db.json for
# the cost_out (output rate) term.
RegistryEntry = Dict[str, Any]
DEFAULT_REGISTRY: List[RegistryEntry] = [
    # --- FREE (free lanes, no balance draw) ---
    {
        "slug": "agnes-2.0-flash",
        "name": "Agnes 2.0 Flash",
        "provider": "agnes",
        "tier": "FREE",
        "source": "free",
        "max_concurrency": 1,
    },
    {
        "slug": "iamhc-default",
        "name": "IAMHC free",
        "provider": "iamhc",
        "tier": "FREE",
        "source": "free",
        "max_concurrency": 1,
    },
    # --- T2 paid workhorse (ZenMux Starter subscription burn-first) ---
    {
        "slug": "minimax/minimax-m3",
        "name": "MiniMax M3",
        "provider": "zenmux",
        "tier": "T2",
        "source": "subscription",
        "max_concurrency": 4,
    },
    {
        "slug": "deepseek/deepseek-v4-flash",
        "name": "DeepSeek V4 Flash",
        "provider": "zenmux",
        "tier": "T2",
        "source": "subscription",
        "max_concurrency": 4,
    },
    {
        "slug": "qwen/qwen3.7-plus",
        "name": "Qwen 3.7 Plus",
        "provider": "zenmux",
        "tier": "T2",
        "source": "subscription",
        "max_concurrency": 4,
    },
    {
        "slug": "kuaishou/kat-coder-pro-v2",
        "name": "KAT Coder Pro v2",
        "provider": "zenmux",
        "tier": "T2",
        "source": "subscription",
        "max_concurrency": 4,
    },
    # DeepSeek direct PAYG API — API-sourced, gated on funds_ok.
    {
        "slug": "deepseek/deepseek-v4-flash",
        "name": "DeepSeek V4 Flash (PAYG)",
        "provider": "deepseek",
        "tier": "T2",
        "source": "api",
        "max_concurrency": 4,
    },
    # --- T3 escalate ---
    {
        "slug": "deepseek/deepseek-v4-pro",
        "name": "DeepSeek V4 Pro",
        "provider": "zenmux",
        "tier": "T3",
        "source": "subscription",
        "max_concurrency": 2,
    },
    {
        "slug": "claude-sonnet",
        "name": "Claude (plan)",
        "provider": "claude",
        "tier": "T3",
        "source": "subscription",
        "max_concurrency": 2,
    },
    {
        "slug": "codex-default",
        "name": "Codex (plan)",
        "provider": "codex",
        "tier": "T3",
        "source": "subscription",
        "max_concurrency": 2,
    },
    # --- VISION (none wired today; recommend() reports the gap honestly) ---
]


def _pct(used: float, limit: float) -> float:
    """Clamped percentage. Matches prototype format.ts pct(): 0 when limit<=0."""
    if not limit or limit <= 0:
        return 0.0
    return max(0.0, min(100.0, (used / limit) * 100.0))


def _days_until(unix_ts: Optional[int], now: Optional[float] = None) -> Optional[float]:
    """Fractional days until a Unix timestamp. None on missing/invalid.

    Mirrors prototype format.ts daysUntil (which can return negative for past
    dates — alerts intentionally still fire).
    """
    if unix_ts is None:
        return None
    try:
        ts = int(unix_ts)
    except (TypeError, ValueError):
        return None
    base = now if now is not None else datetime.now(timezone.utc).timestamp()
    return (ts - base) / 86400.0


def score_model(m: Dict[str, Any], balance_by_provider: Dict[str, float]) -> Dict[str, Any]:
    """Pure scoring: higher is better. Availability is a hard gate (a flag, not a
    score-zeroer). Verbatim port of state.ts:20-38.

    Input dict fields (defaults applied where kdash lacks telemetry):
        quota_used, quota_limit -> quota_pct (0 when limit<=0)
        health ("ok"|"degraded"|"down"), latency_ms (def 0), error_rate (def 0),
        cost_out (def 0), source ("subscription"|"api"|"free"), provider,
        enabled (def True).
    """
    quota_limit = float(m.get("quota_limit") or 0)
    quota_used = float(m.get("quota_used") or 0)
    quota_pct = _pct(quota_used, quota_limit) if quota_limit > 0 else 0.0
    health = str(m.get("health") or "ok")
    health_penalty = 0 if health == "ok" else (25 if health == "degraded" else 100)
    provider = str(m.get("provider") or "")
    source = str(m.get("source") or "api")
    funds_ok = source != "api" or (balance_by_provider.get(provider, 0.0) > 0.5)
    enabled = bool(m.get("enabled", True))
    available = enabled and health != "down" and quota_pct < 97 and funds_ok

    score = 100.0
    score -= quota_pct * 0.55
    score -= health_penalty
    score -= min(20.0, float(m.get("latency_ms") or 0) / 200.0)
    score -= min(20.0, float(m.get("error_rate") or 0) * 2.5)
    score -= min(15.0, float(m.get("cost_out") or 0) * 0.35)
    if source == "subscription":
        score += 8  # sunk cost: burn it first
    if source == "free":
        score += 4
    if not funds_ok:
        score -= 60

    out = dict(m)
    out.update(
        quota_pct=quota_pct,
        available=available,
        funds_ok=funds_ok,
        score=max(0, round(score)),
    )
    return out


def recommend(
    scored_list: List[Dict[str, Any]],
    preferences: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Per-tier recommendation. Verbatim port of state.ts:40-70.

    Returns one entry per tier in SCORE_TIERS with {tier, preferred, pick,
    pick_name, reason, fallbacks}. pick/fallbacks hold slugs; pick_name is the
    human name. FREE is excluded (surfaces via free_pool_view).
    """
    prefs = preferences or {}
    out: List[Dict[str, Any]] = []
    for tier in SCORE_TIERS:
        candidates = sorted(
            (m for m in scored_list if str(m.get("tier")) == tier),
            key=lambda x: x.get("score", 0),
            reverse=True,
        )
        preferred = prefs.get(f"pref.{tier}")
        pref = next((m for m in candidates if m.get("slug") == preferred), None)
        usable = [m for m in candidates if m.get("available")]
        if pref and pref.get("available"):
            pick = pref
        elif usable:
            pick = usable[0]
        else:
            pick = None

        if pick is None:
            reason = "no healthy model available in this tier"
        elif pref and pick.get("slug") == pref.get("slug"):
            reason = f"preferred model healthy ({round(100 - pick.get('quota_pct', 0))}% quota left)"
        elif pref and not pref.get("available"):
            reason = (
                f"{pref.get('name')} unavailable ({pref.get('health')}, "
                f"{round(pref.get('quota_pct', 0))}% quota used) -> failover"
            )
        else:
            reason = "highest score by quota, health, latency and cost"

        pick_slug = pick.get("slug") if pick else None
        fallbacks = [
            m.get("slug")
            for m in usable
            if m.get("slug") != pick_slug
        ][:3]

        out.append(
            {
                "tier": tier,
                "preferred": preferred,
                "pick": pick_slug,
                "pick_name": pick.get("name") if pick else None,
                "reason": reason,
                "fallbacks": fallbacks,
            }
        )
    return out


def free_pool_view(scored_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Free-pool safe-concurrency estimate + graduated advice.

    Verbatim port of state.ts:72-87. Concurrency = sum over AVAILABLE free-tier
    models of max(0, round(max_concurrency * (1 if ok else 0.4) * (1 - quota_pct/100))).
    """
    pool = [m for m in scored_list if str(m.get("tier")) == "FREE"]
    usable = [m for m in pool if m.get("available")]
    total_concurrency = 0
    for m in usable:
        health_factor = 1 if str(m.get("health")) == "ok" else 0.4
        total_concurrency += max(
            0,
            round(float(m.get("max_concurrency") or 0) * health_factor * (1 - float(m.get("quota_pct") or 0) / 100.0)),
        )
    healthy_count = sum(1 for m in pool if str(m.get("health")) == "ok")
    if total_concurrency == 0:
        advice = "free pool exhausted - do not spawn swarm agents"
    elif total_concurrency < 8:
        advice = f"spawn at most {total_concurrency} free agents; keep retries low"
    else:
        advice = f"safe to fan out ~{total_concurrency} free agents across {len(usable)} endpoints"
    return {
        "models": pool,
        "concurrency": total_concurrency,
        "healthy_count": healthy_count,
        "advice": advice,
    }


def runway_days(balance: Optional[float], spend_24h: Optional[float]) -> Optional[float]:
    """balance / spend_24h rounded to 1 decimal; None when spend_24h <= 0.

    Verbatim port of state.ts:142.
    """
    if not balance or not spend_24h or spend_24h <= 0:
        return None
    return round(balance / spend_24h, 1)


def build_alerts(
    subs: List[Dict[str, Any]],
    apis: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Flat alert list. Verbatim port of state.ts:194-206.

    subs:  [{plan, pct, window_label, expires_at}, ...]
    apis:  [{provider, health, latency_ms, runway_days, trial_ends_at}, ...]
    Dates are Unix timestamps (seconds); None means unknown and suppresses the
    corresponding alert (mirrors daysUntil null behavior).
    """
    alerts: List[Dict[str, str]] = []
    for s in subs:
        pct_val = s.get("pct")
        if pct_val is not None and float(pct_val) >= 85:
            alerts.append(
                {
                    "level": "crit",
                    "text": f"{s.get('plan')}: {float(pct_val):.0f}% of {s.get('window_label') or 'window'} used",
                }
            )
        d = _days_until(s.get("expires_at"))
        if d is not None and d < 3:
            alerts.append(
                {
                    "level": "warn",
                    "text": f"{s.get('plan')} renews/expires in {d:.1f}d",
                }
            )
    for a in apis:
        if str(a.get("health")) != "ok":
            alerts.append(
                {
                    "level": "warn",
                    "text": f"{a.get('provider')} API {a.get('health')} ({a.get('latency_ms') or 0}ms)",
                }
            )
        runway = a.get("runway_days")
        if runway is not None and runway < 10:
            alerts.append(
                {
                    "level": "crit",
                    "text": f"{a.get('provider')} balance runway {runway}d at current burn",
                }
            )
        t = _days_until(a.get("trial_ends_at"))
        if t is not None and t < 5:
            alerts.append(
                {
                    "level": "warn",
                    "text": f"{a.get('provider')} free trial ends in {t:.1f}d",
                }
            )
    return alerts


def _health_from_provider_block(block: Optional[Dict[str, Any]]) -> str:
    """Map a quota_state() provider block to the health enum ok|degraded|down."""
    if not isinstance(block, dict):
        return "ok"  # provider not observed: optimistic (no telemetry == ok)
    status = str(block.get("status") or "").lower()
    if status == "ok":
        return "ok"
    if status in {"unavailable", "disabled", "error"}:
        return "down"
    return "degraded"  # stale, estimated, local_plan, etc.


def _peak_from_block(block: Optional[Dict[str, Any]]) -> Optional[float]:
    """Peak used_percent across a provider block's buckets (None if unknown)."""
    if not isinstance(block, dict):
        return None
    buckets = block.get("buckets")
    if not isinstance(buckets, list):
        return None
    peak: Optional[float] = None
    for b in buckets:
        if not isinstance(b, dict):
            continue
        used = b.get("used_percent")
        if used is None:
            continue
        try:
            v = float(used)
        except (TypeError, ValueError):
            continue
        if peak is None or v > peak:
            peak = v
    return peak


def _balance_by_provider_from_quota(quota: Dict[str, Any]) -> Dict[str, float]:
    """Sum amount_remaining per provider from quota_state() bucket rows.

    On the default persistent DB path amount_remaining is not stored, so this is
    frequently {} (-> funds_ok optimistic). It engages on the in-memory path and
    whenever a fresh snapshot carried a balance.
    """
    out: Dict[str, float] = {}
    providers = quota.get("providers") or {}
    if not isinstance(providers, dict):
        return out
    for name, block in providers.items():
        if not isinstance(block, dict):
            continue
        for b in block.get("buckets") or []:
            if not isinstance(b, dict):
                continue
            amount = b.get("amount_remaining")
            if amount is None:
                continue
            try:
                out[name] = out.get(name, 0.0) + float(amount)
            except (TypeError, ValueError):
                continue
    return out


def _cost_out_for(slug: str, pricing_db: Any) -> float:
    """Look up the output rate ($/M tokens) for a slug from pricing_db.json.

    Returns 0.0 when unknown (cost term becomes a no-op rather than invented).
    """
    if pricing_db is None:
        return 0.0
    try:
        rate = pricing_db._resolve_pricing(slug)  # private but stable API
    except Exception:
        return 0.0
    if not isinstance(rate, dict):
        return 0.0
    try:
        return float(rate.get("output") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _free_pool_output(
    pool: Dict[str, Any], live_concurrency: Optional[int]
) -> Dict[str, Any]:
    """Assemble the /api/suggest free_pool block.

    When a live free-pool concurrency signal is available it takes precedence
    over the static registry estimate: the registry's two free lanes are long
    dead, while the real pool is a rotating local LiteLLM proxy. ``None`` keeps
    the registry estimate unchanged, so the pure scorer and its differential
    tests are never affected by live infrastructure.
    """
    if live_concurrency is None:
        return {"concurrency": pool["concurrency"], "advice": pool["advice"]}
    c = max(0, int(live_concurrency))
    if c == 0:
        advice = "free pool exhausted - do not spawn swarm agents"
    elif c < 8:
        advice = f"spawn at most {c} free agents; keep retries low"
    else:
        advice = f"safe to fan out ~{c} free agents across the live pool"
    return {"concurrency": c, "advice": advice}


def build_scored_state(
    quota: Dict[str, Any],
    *,
    registry: Optional[List[RegistryEntry]] = None,
    pricing_db: Any = None,
    preferences: Optional[Dict[str, str]] = None,
    subs: Optional[List[Dict[str, Any]]] = None,
    apis: Optional[List[Dict[str, Any]]] = None,
    free_pool_concurrency: Optional[int] = None,
) -> Dict[str, Any]:
    """I/O bridge: join the curated registry to live quota/pricing and run the
    prototype scorer. Returns the additive keys for /api/suggest:

        generated_at, recommendations, free_pool {concurrency, advice},
        alerts, scored_models
    """
    reg = registry if registry is not None else DEFAULT_REGISTRY
    providers = quota.get("providers") if isinstance(quota, dict) else None
    if not isinstance(providers, dict):
        providers = {}
    balance_by_provider = _balance_by_provider_from_quota(quota)

    scored: List[Dict[str, Any]] = []
    for entry in reg:
        slug = str(entry.get("slug") or "")
        provider_key = str(entry.get("provider") or "")
        block = providers.get(provider_key)
        peak = _peak_from_block(block)
        # quota_used/quota_limit reconstruction: peak IS the used percentage, so
        # set quota_limit=100, quota_used=peak to feed score_model faithfully.
        if peak is not None:
            quota_used = float(peak)
            quota_limit = 100.0
        else:
            quota_used = 0.0
            quota_limit = 0.0  # _pct -> 0 when limit<=0 (no observation)
        health = _health_from_provider_block(block)
        enabled = bool(block.get("network_enabled", True)) if isinstance(block, dict) else True
        cost_out = _cost_out_for(entry.get("pricing_slug") or slug, pricing_db)
        model = {
            "slug": slug,
            "name": entry.get("name") or slug,
            "provider": provider_key,
            "tier": str(entry.get("tier") or "T2"),
            "source": str(entry.get("source") or "api"),
            "max_concurrency": int(entry.get("max_concurrency") or 1),
            "quota_used": quota_used,
            "quota_limit": quota_limit,
            "health": health,
            "enabled": enabled,
            "latency_ms": 0,   # not tracked by kdash yet
            "error_rate": 0.0,  # not tracked by kdash yet
            "cost_out": cost_out,
        }
        scored.append(score_model(model, balance_by_provider))
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)

    recommendations = recommend(scored, preferences)
    pool = free_pool_view(scored)
    alerts = build_alerts(subs or [], apis or [])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recommendations": recommendations,
        "free_pool": _free_pool_output(pool, free_pool_concurrency),
        "alerts": alerts,
        "scored_models": scored,
    }
