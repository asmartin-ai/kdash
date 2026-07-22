# Tokdash Suggest design (2026-07-14)

Grilling outcome. **Do not treat this as “build everything now.”**
Phased plan below; Phase 0 is already largely landed.

## Product question

> Out of the compute I have available, what is the best tool for the job?
> How do I utilize subscriptions and trials while I have them?

## Locked decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Product boundary | **A+B lean A** — ambient HUD first; routing is a thin strong-suggestion layer |
| 2 | Ops authority | **B** — Tokdash is the **operational mirror** day-to-day; stack docs/skills follow or sync to it |
| 3 | Live shaping | **A + thin C** — peaks/flows demote/warn; light trial/budget nudges; no silent full optimizer |
| 4 | Job context | **A now** — inventory-default, **zero input for humans**. Future optional `job=` for agents (icebox) |
| 5 | Human vs agent surface | **A** — one payload `/api/suggest`; glance/UI only render. Future dedicated `/api/route` (icebox) |
| 6 | Agent-stable core (recommended, not built) | **B thin** — structured `pick` + `fallbacks` + `schema_version` from inventory only |

## Default answers for ungrilled branches

- **Confidential:** env `TOKDASH_CONFIDENTIAL=1` (and later query flag for agents); demotes free/trial lanes.
- **Trial burn order:** SuperGrok → Hy3 free → zenmux-free overflow → paid M3 (Flash when warm).
- **Quality default paid:** MiniMax M3 stays explicit policy; warm/hot only *nudges* Flash/pause.
- **Dual-copy glance:** keep sync/copy for now; junction is optional hygiene, not design.
- **Stack docs:** when Tokdash policy changes, update LLM-dev / orchestration skills in the same effort (mirror runs outward).

## Current state (Phase 0 — done)

- Single brain: `src/tokdash/suggest.py` (`build_suggest`, `format_glance_lines`)
- Live ZenMux flows/peaks into `/api/suggest`
- Glance rail consumes shared policy; flow budget near bars; Fireworks = 30d usage
- Suggest tab: NOW, flow card, tiers, footnotes, copy-ready ids
- Tests: `tests/test_suggest.py`
- Icebox notes in `NEXT.md` for `/api/route` and optional `job=`

## Phase 1 — Agent-stable pick (**landed 2026-07-14**)

**Goal:** agents can trust JSON without parsing `now` strings. Humans unchanged.

Landed in `build_suggest()`:
- `schema_version: 1`
- `pick: {model, via, tier, reason_code, reason, confidential_ok, expires?}`
- `fallbacks[]` (same shape, de-duped, max 5)
- Reason codes: `trial_burn`, `free_overflow`, `paid_default`, `warm_cheap`, `hot_pause`, `confidential`, `interactive`
- `now` derived from the same pick rules
- Suggest tab shows agent pick strip; tests cover trial/confidential/warm/hot

**Done when:** a skill can `GET /api/suggest` and use `pick.model` + `pick.via` with no string parsing; glance still looks the same. ✅

### Phase 1 follow-ups (**landed 2026-07-17**)

- `GET /api/suggest?refresh=1` skips the 600s route cache (`force_refresh`); dashboard Reload uses it.
- Response includes `response_cache: {status, served_from_cache, age_seconds}` so the UI can show freshness.
- API contract tests: `tests/test_suggest_api_contract.py` (+ existing `tests/test_suggest.py`).

**Recommended next action:** Phase 2 ops-mirror hygiene on the next rate/tier edit — not more Phase 1 schema work.

## Phase 2 — Ops mirror hygiene

1. When changing rates/tiers in `suggest.py`, checklist: update
   `LLM-dev/stack-planning` + `lightweight-orchestration` / aider skill if they hardcode models.
2. Optional: tiny drift test or script that greps hub skills for `minimax-m3` / SuperGrok end date.
3. Prefer junction or install step for AppData `glance.py` ↔ repo script.

**Done when:** one policy edit has a known outbound sync path (even if manual).

## Phase 3 — Thin budget nudges (thin C)

1. Visible thresholds only, e.g. 7d rem flows &lt; N → prefer Flash in `pick` with `warm_cheap` (already partial via peak %).
2. Expose threshold constants in payload (`policy.warm_pct`, `policy.hot_pct`, `policy.med_flow_per_turn`).
3. No black-box “cheapest model everywhere.”

**Done when:** nudge rules are listed in `/api/suggest` under `policy` and tested.

## Phase 4 — Optional job class (icebox → build when agent needs it)

- Same route: `?job=exec|review|draft|longctx&confidential=0|1`
- Omit job → Phase 1 inventory default
- Reshape `pick` only; keep tiers inventory-true
- Humans never required to pass job

## Phase 5 — Dedicated `/api/route` (icebox)

- Stricter schema, longer cache stability, no human chrome fields
- Implement only if agent consumers outgrow suggest JSON

## Explicit non-goals (for now)

- Free-text task routing / planner inside Tokdash
- Silent quality downgrades without reason_code
- Scraping glance terminal output as agent API
- Second policy table in glance

## Recommended next action

**Phase 1 landed** (`pick` / `fallbacks` / `schema_version` + API/UI contract tests).
Next additive ops-mirror: surface **Codex / ChatGPT plan windows** (Free included)
from live `quota_state` peaks — no hardcoded Free caps; demote T4 when hot.
Everything else stays icebox until an agent actually consumes suggest.
