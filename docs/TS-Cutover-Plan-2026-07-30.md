# kdash → TypeScript cutover & Python retirement plan (2026-07-30)

Requested scope: **full cutover — retire/delete Python**. Assessment: a safe
deletion is **not a one-shot**; several load-bearing subsystems have no TS
counterpart and the differential safety net itself depends on the Python
package. This plan is the route to a safe deletion. Do **not** `rm` Python until
every gate in §5 is green and the fork decision in §2 is made explicitly.

Repos:
- `K:/Projects/kdash` (junction → `K:/Projects/llm-stack/kdash`) — Python reference (`tokdash`, FastAPI). 694 pass / 7 skip.
- `K:/Projects/llm-stack/kdash-ts` — TS/Bun target (`bun:sqlite`). 178 pass / 1 known flake (§4).
- `K:/Projects/llm-stack/kdash-tui` — TS ANSI TUI (successor to Python `glance`), consumes `/api/quota` + scored `/api/suggest`.

---

## 1. Done already (this session, 2026-07-30)

- **Free-pool "exhausted" bug fixed** in both stacks. Root cause: the scorer's
  free tier was two dead static lanes (`agnes`, `iamhc`) with no link to the
  real LiteLLM pool at `:8788`. Added `sources/free_pool.py` /
  `core/free_pool.ts` reading the pool's `state.json` (env
  `TOKDASH_FREE_POOL_STATE`), counting distinct healthy **swarm budgets**
  (mirrors `freepool width`), injected at the I/O bridge only so the pure
  scorer + all differential/unit tests stay byte-identical. Now reports
  concurrency ≈ 11.
- **"Recommendations off" fixed** (shared `index.html`, both copies identical):
  recommendation cards for tiers with **zero registered candidates** (T1/FREE →
  shown in the pool banner; VISION → unwired) are no longer rendered as an
  alarming "no healthy model" card. Tiers that have models but none available
  (e.g. T2 all quota-maxed) still show their honest empty state. T3 picks Claude.
- **Amp deprecated**: unregistered from both trackers (`coding_tools.py`,
  `tracker.ts`). Parser code + differential tests retained (git-reversible); no
  `~/.amp` on this box, so it contributed nothing. Excluded from the parity
  gate below.
- Verified: Python 694/7; TS 178 pass /1 flake; Models tab renders correctly on
  both the Python (`:55426` scratch instance) and Bun (`:55425`) dashboards.

**Not yet applied to the live service:** the user's running dashboard is
`pythonw -m tokdash serve` (an installed editable service, was PID 2548 on
`:55423`). It holds the fixed code on disk but ran it from memory pre-edit —
it needs a restart to pick up the fixes. That restart is the user's call (it's
a managed long-lived instance).

---

## 2. The one irreversible decision (make explicitly before Phase D)

**G1 — accept permanent severance of the upstream fork?** `kdash` is a fork of
`JingbiaoMei/Tokdash` (resynced from v1.3.1, `upstream` remote live) with three
still-unfiled upstream PRs in the backlog (omp quota, ZCode parser, Zed parser).
Deleting Python ends resync forever and moves 100% of parser maintenance (new
tools, format churn) to us. Deletion is downstream of this "yes".

If the answer is **no / not yet**, stop at Phase C: run TS as the primary
dashboard with Python kept as a fallback + upstream anchor (non-destructive).

---

## 3. Blockers to a safe deletion (each is a required port or decision)

| # | Blocker | Where it lives (Python) | TS status | Work |
|---|---|---|---|---|
| B1 | Onboarding / lifecycle: `setup`, `doctor`, `update`, `uninstall` | `onboard/engine.py` (69 KB) | **absent** | Port CLI verbs + engine, or replace with a documented manual install |
| B2 | Service installers: systemd / launchd / **winsched** / tailscale | `onboard/{systemd,launchd,winsched,tailscale}.py` | **absent** | Port the installer(s) actually used (this box = winsched). The live service depends on this |
| B3 | Distribution of the TS runtime | — | **undecided** | `bun build --compile` to a binary, or a `bun`-based service unit; then install it as the `:55423` service replacing `pythonw -m tokdash` |
| B4 | `glance` Python TUI + its narrative brain `build_suggest` (~1450 lines: pick/tiers/plans/deadlines/now/copy_ready) | `glance.py`, `suggest.py` | **not ported** (only the numeric scorer is) | Retire `glance` in favour of `kdash-tui` (already scored-key-only), or port. No browser UI consumes the narrative half |
| B5 | Differential test suite depends on the Python package | `kdash-ts/tests/diff_shim.py` imports `tokdash.*` | n/a | Before deletion, freeze parity as **golden fixtures** (snapshot Python outputs to JSON) so TS tests survive without Python |
| B6 | CLI verb parity | Python: `balance`, `stack`, `version`, `glance` (+ B1 verbs) | TS CLI has `serve/export/stats/quota/db` only | Add missing verbs (or drop intentionally, documented) |
| B7 | `stack.ts` health panel shells to Python | `kdash-ts/src/core/stack.ts` → `doctor.py`, `python.exe` | partial | That `doctor.py` is agent-hub's, not kdash's — OK to keep, but confirm it's not kdash Python being deleted |
| B8 | Full browser + write-path parity not yet proven | all `/api/*` incl. session detail, CSRF-guarded writes | representative only | Complete the §5 matrix |

---

## 4. Date flake — FIXED 2026-07-30 (kdash-ts `379ea32`)

~~`differential.test.ts` "stack catalog panels match Python" intermittently fails
by one day on `2099-01-01` (26453 vs 26452)~~ Root cause: Python uses `date`
ordinal arithmetic (DST-immune); TS computed `days_remaining` from two
local-midnight `Date` epochs, yielding a non-integer gap across a DST
transition (America/Chicago & Pacific/Auckland). Fixed in `collectExpiries` by
comparing **UTC midnights**; regression locked in `tests/stack.test.ts`
(fixed-`now` fixture, DST-transition date). Verified: differential passes today
and under forced TZ; full TS suite 181 pass / 0 fail.

---

## 5. Phased route to deletion

Each phase ships standalone value; stopping at any boundary leaves us better off.

### Phase A — Lock parity (size S)
- Fix B4-date bug (§4); make the stack differential deterministic.
- Convert the differential suite to **golden fixtures** (B5): snapshot every
  Python `diff_shim` output to committed JSON; switch TS tests to compare
  against fixtures, not a live Python import.
- **Next action:** fix `collectExpiries` day math + add fixed-`now` test.
- **Done when:** `bun test` is green with the Python package uninstalled.

### Phase B — Port the lifecycle (size L) — the real work
- Port B1 (`setup/doctor/update/uninstall`) and B2 (winsched installer, the one
  this box uses) to `kdash-ts`. launchd/systemd/tailscale only if wanted.
- Decide B3 distribution; produce the artifact.
- **Next action:** port `winsched.py` → `kdash-ts` + a `bun src/cli.ts setup`.
- **Done when:** a fresh install of the TS service can be set up, health-checked,
  updated, and uninstalled with no Python present.

### Phase C — Make TS the primary dashboard (size M, non-destructive)
- Complete the §5 verification matrix (below) against the Bun server.
- Install the TS service on `:55423`, replacing `pythonw -m tokdash serve`.
  Keep the Python checkout on disk as fallback + upstream anchor.
- Retire Python `glance` in favour of the compiled `kdash-tui` binary (B4).
- **Done when:** the user's daily driver is the Bun service; Python is unused
  but present. **This is the safe stopping point if G1 = no.**

### Phase D — Delete Python (size S, destructive, gated) — requires explicit go
- Only after G1 = yes and every gate below is green.
- Remove the `tokdash` package, tests that still import it, the `upstream`
  remote, and the junction. File the three upstream PRs first if ever (they are
  worthless post-fork).
- **Next action (do NOT run until approved):** `git rm -r src/tokdash tests` in
  the Python repo after golden-fixture conversion.

**Deletion gate — ALL must be true:**
- [ ] G1 (fork severance) answered **yes** in writing.
- [ ] TS suite green **with Python uninstalled** (golden fixtures).
- [ ] §5 browser + write-path matrix 100% parity.
- [ ] Lifecycle (install/doctor/update/uninstall) works in TS on this box.
- [ ] TS service installed and running as the daily driver for ≥ a few days.
- [ ] Explicit user approval for the `rm`.

### §5 verification matrix (Phase C gate)
Every tab (Overview, Sessions, Stats, Quota, Pricing, Subscriptions, APIs,
Models), every session-detail path (Codex/Claude/OpenCode/PiAgent/Mimo),
every CSRF-guarded write (pricing, quota consent, update consent), `/health`,
static assets/PWA, i18n (en + zh), and each CLI verb — TS output reconciled to
Python on the same real inputs.

---

## 6. Recommendation

Execute **A → B → C now**; they are pure gain and non-destructive. Answer **G1**
before **D**. Do **D** only behind the deletion gate with explicit approval —
that is the only irreversible step.
