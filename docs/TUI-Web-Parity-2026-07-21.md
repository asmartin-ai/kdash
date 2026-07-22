# TUI ↔ Web GUI Parity — 2026-07-21

*Investigation from the 2026-07-21 code review. Scope: identify where the
terminal dashboard (`tokdash glance` / `src/tokdash/glance.py`) and the web
GUI (`/`, `src/tokdash/static/index.html`) diverge, and what it would take
to bring them to parity.*

## TL;DR

Both surfaces share the **suggestion brain** (`tokdash.suggest.build_suggest`)
but use **completely different data paths** for provider meters:

| Surface | Suggest brain | Provider meters (ZenMux, Claude, etc.) | Usage/cost (tools) |
|---------|---------------|----------------------------------------|--------------------|
| Web GUI | `/api/suggest` → `build_suggest` | `/api/quota` → `sources/quota/*` (cached, polled by background daemon) | `/api/usage`, `/api/tools` → `usage_store` |
| TUI     | `_import_suggest()` → `build_suggest` | **Direct provider API calls** (`glance_zenmux()`, `glance_claude_plan()`, …) — no caching layer, no `/api/quota` | `/api/tools` (only tokdash API call the TUI makes) |

So the TUI is **fresh-but-fragile** (live API call every refresh, rate-limit
prone) and the web GUI is **cached-but-stale** (depends on the poll daemon's
interval). Neither is wrong; they serve different needs.

---

## Detailed surface comparison

### Shared layer (already at parity)

1. **Suggestion/routing brain** — `tokdash.suggest.build_suggest()`.
   Both call it with provider peak % and flow counts. Output shape:
   `{pick, fallbacks, tiers, now, copy_ready}`. Single source of truth.
2. **Pricing DB** — `pricing_db.json`. Shared by both via `pricing.py`.
3. **Health endpoint** — `/health` (used by supervisor and self-heal wrapper).

### Provider meter divergence (the core parity gap)

The web GUI has a **structured quota layer**: `src/tokdash/sources/quota/*`
with per-provider modules (claude.py, codex.py, antigravity.py, config.py)
behind a polling daemon (`_start_quota_poll_daemon` in cli.py:536). State is
cached in a JSON store; `/api/quota` reads from cache, `/api/quota/refresh`
forces a refetch, `/api/quota/history` returns time-series.

The TUI has **inline fetchers** in `glance.py`, one per provider:
`glance_zenmux`, `glance_claude_plan`, `glance_clinepass`, `glance_zai`,
`glance_freebuff`, `glance_agnes`, `glance_moonshot`, `glance_iamhc`,
`glance_fireworks`, `glance_openrouter`, `glance_deepseek`.

Each TUI fetcher hits the provider API directly on every render. The Claude
fetcher has its own throttle/cooldown/429-backoff logic (lines 29–37 of
glance.py) that **duplicates** what `sources/quota/claude.py` already does.

**Providers covered by TUI but NOT by web quota layer:**
- ZenMux subscription/flow meters
- ClinePass plan limits
- Z.ai quota
- Moonshot/Kimi balance
- Freebuff rate limits
- IAMHC usage
- Fireworks billing
- OpenRouter credits
- DeepSeek balance

These show in `kdash glance` but have **no equivalent in the web GUI**. The
web GUI only exposes Claude/Codex/Antigravity quota (the three modules under
`sources/quota/`).

### Usage/cost parity (near-parity)

- **Web GUI**: `/api/usage` (calendar chart, per-day bars), `/api/tools`
  (summary), `/api/sessions` (per-session drill-down).
- **TUI**: `glance_tools()` calls `/api/tools` only. No session drill-down,
  no calendar view — by design (terminal is one-screen).

This gap is **intentional** — the web GUI's session browser and calendar
don't fit a 80×40 terminal.

### Interactivity parity

| Feature | Web GUI | TUI |
|---------|---------|-----|
| Refresh quota | Reload button (`/api/quota/refresh`) | Auto every render |
| Toggle quota consent | Settings UI (`POST /api/quota/consent`) | Not exposed |
| Drill into session | Click handler (`/api/session`) | Not applicable |
| Open browser to dashboard | N/A | **Not exposed** ← only real TUI gap |

---

## The one concrete parity fix worth doing

**"Add tokdash web link to TUI"** (the user's explicit request):

The TUI has no way to say "open the web GUI." A one-line addition to the TUI
header — `tokdash-glance  http://127.0.0.1:55423  (press o to open)` — plus
an `o` keybinding in `watch_loop` (alongside the existing `q`/`r`/`space`)
would close the gap. Cost: ~15 LOC in `glance.py`.

---

## Bigger parity questions (icebox — not recommended now)

1. **Unify provider meters under `sources/quota/`.** Move the 11 glance_*
   fetchers into `sources/quota/<provider>.py` modules, expose them via
   `/api/quota`, retire glance.py's direct calls. The TUI would then read
   `/api/quota` like the web GUI.
   - **Pro:** single caching/throttle/backoff layer; web GUI gains ZenMux,
     ClinePass, etc. meters; less code duplication.
   - **Con:** big refactor (~11 new modules + glance rewrite + test
     migration). TUI loses its live-fetch resilience — if tokdash serve is
     down, the TUI currently still works (direct API calls); after this
     refactor it would be dead too.
   - **Recommendation:** defer. The current split has a real resilience
     benefit. Revisit only if the quota layer's poll cadence proves
     inadequate.

2. **Share the Claude throttle/backoff code.** `glance.py` lines 29–37 +
   `_glance_claude_plan_body()` (lines 795–940) reimplement what
   `sources/quota/claude.py` does. Extracting a shared `_claude_oauth.py`
   helper would remove ~150 LOC of duplication.
   - **Recommendation:** worth doing if either file is touched for another
     reason; not on its own.

3. **Session/calendar in TUI.** Not worth doing — terminal is the wrong
   shape.

---

## Recommended next action

Just the web-link-to-TUI item. Everything else is either intentional
(session drill-down) or a large refactor with a real downside (unified
quota layer). Add a `Press o to open web dashboard` line + keybinding to
`glance.py`'s `header_lines()` and `watch_loop()`.
