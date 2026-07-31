# Web GUI Retirement — kdash is TUI-only (2026-07-31)

> Snapshot as of 2026-07-31. Records the removal decision and its follow-ups;
> current repo state (branches, tips, push status) is derived from git, not this file.

The browser dashboard (`kdash-ts/static/index.html` + assets) and its
browser-write machinery were removed on 2026-07-31. kdash is now consumed
entirely through the terminal UI (`kdash-tui`) and the loopback HTTP API
(`kdash-ts serve` on `127.0.0.1:55423`).

## What was removed

- **Web dashboard** — `static/index.html` (7,724 lines, 8 tabs: overview,
  quota, sessions, stats, models, pricing, subscriptions, apis), `themes.css`,
  `theme-config.js`, PWA assets (`sw.js`, `manifest.webmanifest`,
  `icons/{icon-192,icon-512,logo}.png`). CDN deps (Tailwind, Chart.js,
  Three.js, Flatpickr) no longer load anywhere.
- **Browser-write machinery** — CSRF token issuance (`/api/csrf-token`),
  `writeAllowed`/`csrfReadable`, the pricing-db editor (GET+PUT
  `/api/pricing-db`), quota consent/settings forms (POST
  `/api/quota/consent`, `/api/quota/settings`), and the static file routes
  (`/`, `/themes.css`, `/theme-config.js`, `/manifest.webmanifest`, `/sw.js`,
  `/icons/*`).
- **Commits**: `f090df3` (server removal + test retarget), `3c84383` (test
  timeout for the larger parser corpus), `7628a2f` (kept one loopback write).

## What survived

- **The HTTP API server** — `/health` (the supervisor's liveness probe,
  load-bearing), `/api/version`, `/api/usage`, `/api/tools`, `/api/openclaw`,
  `/api/stats`, `/api/suggest`, `/api/sessions`, `/api/codex/sessions`,
  `/api/session`, `/api/codex/session`, `/api/stack`, `/api/quota`,
  `/api/quota/history`, `/api/quota/refresh` (ungated POST), `/api/update-check`
  (GET).
- **One new loopback-only write**: POST `/api/update-check/consent` (no CSRF —
  the server is bound to 127.0.0.1) so the TUI's `u` key can opt in to update
  checks.

## Migrated to the TUI (kdash-tui)

- **Usage panel** — today's tokens/cost/messages/cache-hit/top-model on the
  Overview screen (was the web Overview tab).
- **Sessions explorer** — screen 6: tool cycle (`t`: codex/claude/opencode/
  pi_agent/mimo), period cycle (`p`: today/week/month), list with selection
  (`↑`/`↓`), per-session turn detail (Enter/Esc) (was the web Sessions tab).
- **Stats heatmaps** — screen 7: ASCII month + year contribution heatmaps
  (was the web Stats tab; the 3D calendar is gone — see below).
- **Quota refresh** — `r` now POSTs `/api/quota/refresh` then re-fetches
  (was the web refresh button).
- **Update badge** — header chip + `u` key for consent (was the web update
  badge).
- **Quota history sparklines** — 24h `used_percent` series on Subscriptions
  and APIs bucket rows (was the web quota charts).
- **Commits**: `c538ed1`, `669e642`, `5771307`.

## Not migrated (and why)

| Feature | Status | Migration path if revisited |
|---|---|---|
| 3D isometric calendar (Three.js) | replaced by ASCII heatmaps (screen 7) | render an iso projection in ASCII; low value |
| Pricing DB editor (PUT `/api/pricing-db`) | edit `~/.tokdash/pricing_db.json` directly | the override fully replaces bundled rates |
| Quota settings form (enable/poll-interval) | edit `~/.tokdash/config.json` `quota.*` keys | `quota.enabled`, `quota.poll_interval_minutes`, per-provider `quota.<key>` |
| PWA (sw.js, manifest, icons) | dead — no browser surface | nothing to port |
| Heatmap navigation + date-range pickers (Flatpickr) | TUI shows current month/year only | add period keys later if wanted |
| Antigravity pools UI | was already commented out in the web page | nothing lost |
| Zed / OMP / aider usage parsers | deferred (see below) | — |

## Deferred parsers

- **Zed** — usage lives in zstd-compressed `threads.db` blobs + workspace DBs
  + log scraping. Bun's stdlib has no zstd; needs a dependency decision. Port
  base: kdash git `7b8bf4f` (`src/tokdash/sources/coding_tools.py`, `ZedParser`
  ~line 2602) if revisited.
- **OMP harness** — no stable log format established yet.
- **aider** — no stable log format established yet.

## Survey items landed in the same change

- **LiteLLM proxy usage parser** (`litellm_proxy` source): TS port
  (`kdash-ts/src/parsers/litellm.ts`, commit `02f451f`) reads the sidecar JSONL
  written by the free-pool proxy callback
  (`K:/Projects/free-pool/custom/python_hooks/tokdash_callback.py`, commit
  `ca5d982`); the proxy was restarted with the callback wired in
  `config.yaml`. Live-verified: a real lane request appears in
  `~/.tokdash/litellm-proxy-usage.jsonl` and in `/api/tools`.
- **Pricing entries** (commit `7216229`): `qwen3.8-max-preview` and
  `macaron-v1-venti` — both $0 today (macaron is promo-free through
  2026-08-07; qwen3.8-max-preview is not on OpenRouter's public list yet).
  `lastUpdated` bumped to 2026-07-31.
- **ZCode transcript parser** (`zcode` source, commit `9f7bf99`): TS port
  reading `~/.zcode/cli/agents/sess_*/agent_*/transcript.jsonl` +
  `metadata.json`; live corpus verified (101 entries with token counts).
- **Novita balance collector** (commit `363ea23`): `GET
  https://api.novita.ai/openapi/v1/billing/balance/detail` (strings in 1/10000
  USD → `ok <usd> USD`); enabled via `quota.novita_api` in
  `~/.tokdash/config.json`; live balance $10.00 shown on the TUI APIs screen.

## Watchlist

- **macaron-v1-venti promo** ends 2026-08-07 — re-check the pricing entry is
  still accurate after that date.
- **Fireworks** — `stale_token` until a valid `FIREWORKS_API_KEY` +
  `FIREWORKS_ACCOUNT_ID` are provided; re-enabling also requires purging
  persisted `quota_snapshots` rows (`state.ts` force-enables providers with
  persisted `_api` snapshots).
- **Unpriced free-pool lanes** — the remaining lanes without pricing entries
  are $0-correct today; revisit if any starts charging.
- **First-parse latency** — the zcode parser reads ~308k transcript rows on a
  cold process; `/api/usage` and `/api/stats` can take ~3s on first hit after a
  server restart (cached 30s after).
