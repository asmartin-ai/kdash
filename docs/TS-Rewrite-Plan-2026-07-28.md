# kdash → TypeScript migration plan (2026-07-28)

> Snapshot as of 2026-07-28.

Source prototype: `K:/Projects/llm-stack/kdash-ts-prototype/` (a Next.js/Postgres
scaffold produced by Opus 5 low via arena.ai; pristine zip archived in that dir).

---

## 1. Gate result — is TypeScript actually more performant?

**Yes, but only for shell-invoked surfaces.** Measured on this box, 5 runs each:

| Path | Python today | Bun | Verdict |
|---|---|---|---|
| CLI invocation (`tokdash --help`) | **385–403 ms** | ~40 ms | **~10× win, user-perceptible** |
| kdash's own heavy imports, in-process | 65 ms | — | not the bottleneck |
| Refresh cycle (quota poll) | `omp usage --json` subprocess + HTTP | same | **no win — I/O bound** |
| Transcript parsing over real corpus | **unmeasured** | unknown | needs a benchmark (gate G2) |
| Serving the dashboard, 1 user | FastAPI/uvicorn, adequate | faster on paper | irrelevant at this scale |

The load-bearing detail: kdash's *own* modules import in 65 ms, yet the CLI takes
~390 ms. The missing ~300 ms is **FastAPI + uvicorn + pydantic import cost**, paid
on every single invocation. So:

- A **CLI/TUI** in TS is a genuine ~350 ms-per-invocation win.
- The **long-lived server** has nothing to gain.
- A **big-bang engine rewrite is not justified on performance** as measured today.

## 2. What a full rewrite must pay for (the prototype hides all of this)

1. **Permanent upstream fork.** kdash is a fork of `JingbiaoMei/Tokdash`, resynced
   from v1.3.1 on 2026-07-22, 12 commits ahead, `upstream` remote live — and
   NEXT.md's icebox holds **three planned upstream PRs** (omp quota, ZCode parser,
   Zed parser). A rewrite ends resync permanently and transfers 100 % of
   parser maintenance (new tools, format churn) to us.
2. **618 passing tests** to re-earn.
3. **UI surface mismatch.** The live UI has **5 tabs** — Overview, Sessions, Stats,
   Quota, Pricing (`static/index.html:927-931`). The prototype has **4 different
   screens** — Dashboard, Subscriptions, APIs, Models. It **omits Sessions, Stats
   and Pricing** and adds three new views. It is *additive*, not a replacement.
4. **i18n.** Every label carries `data-i18n`; `README_CN.md` exists (upstream is
   Chinese-maintained). The prototype has none.
5. **Theming.** `themes.css` (45.7 KB) + `theme-config.js` + CSS custom properties
   (`--color-label`). The prototype is plain Tailwind.
6. **PWA/offline.** `manifest.webmanifest` + `sw.js`.
7. **`onboard/`** — 69 KB engine plus systemd / launchd / winsched / tailscale
   installers.
8. **`pricing_db.json`** (76.6 KB) + pricing logic.

## 3. Strategy — strangler fig, value at every phase

The hybrid below is **not an alternative to the rewrite; it is its first three
phases.** Each ships standalone value, and stopping at any boundary still leaves
us better off. Only Phases 4+ require accepting the fork cost.

### Architecture decisions (made)

- **Storage: `bun:sqlite`, never PostgreSQL.** kdash is a single-user local tool
  that ships service installers; requiring a PG server is an operational
  regression. The prototype's `pgTable` schema does not port as-is.
- **React yes, Next.js no.** Adopt `src/components/screens/*.tsx` (plain React),
  serve via `Bun.serve` + a Vite bundle. Next adds a server runtime and build
  chain to something that currently ships static files, and fights the existing
  service-worker story. The Next-specific parts (`app/layout.tsx`, `app/page.tsx`,
  `api/*/route.ts`) are 228 B–4.4 KB stubs — cheap to replace.
- **i18n and theming are acceptance criteria, not follow-ups.** An adopted screen
  must render through the existing CSS-variable theme and carry i18n keys, or it
  is a regression.
- **Differential testing is the no-functionality-loss mechanism.** Every ported
  module runs against the Python original on the same real inputs; outputs must
  match before any Python is retired.
- Drop the `nextjs-postgresql-template` package identity.

---

## 4. Phases

### Phase 0 — Decide + baseline · size **S** · 1 sitting

Two decision gates, both cheap:

- **G1: accept a permanent upstream fork?** Blocks Phases 4+; does *not* block 1–3.
- **G2: is there a second perf win in parsing?** The only unmeasured candidate.

**Next action:** `python -X importtime -m tokdash --help 2>&1 | sort -k2 -rn | head -20`
to confirm FastAPI dominates startup, then time one full refresh over the real
session corpus.
**Done when:** baseline table recorded here and G1 answered yes/no.

### Phase 1 — Adopt the prototype's *features* into today's Python · **M**

Zero risk, immediate value, no TypeScript required. Port from
`kdash-ts-prototype/src/core/state.ts`:

- `scoreModel` weights + the **burn-subscription-first** heuristic (`:34`) → `suggest.py`
- `recommend()` with a human **`reason`** string + ranked `fallbacks` (`:40-70`)
- `freePoolView` **safe-concurrency formula** + graduated advice (`:72-87`)
- `runwayDays` = balance ÷ spend24h, and trial/deal expiry fields (`:142`)
- flat `alerts[]` threshold model (`:194-206`)
- expose **`/api/suggest`** with the prototype's contract

**Next action:** open `src/tokdash/suggest.py` beside `state.ts:20-87` and diff the
ranking logic.
**Done when:** `/api/suggest?tier=T2` returns pick + reason + fallbacks +
free-pool concurrency on real data, with tests.

### Phase 2 — Adopt the prototype's *UI* as new tabs · **M**

Add **Subscriptions, APIs, Models** alongside the existing five tabs, reusing the
current theming, i18n and PWA. No framework change, nothing removed.

**Next action:** add a sixth `tab-btn` for Subscriptions at `static/index.html:931`
and render it from `/api/state`.
**Done when:** 8 tabs live, themes + i18n intact, PWA still installs.

### Phase 3 — TypeScript TUI as a thin client · **S/M** ← where the measured win lands

Adopt `kdash-ts-prototype/tui/` (dependency-free ANSI, already polls `--url`)
against the Python API. New project `K:/Projects/llm-stack/kdash-tui/`;
`bun build --compile` to a single binary.

**Next action:** `cd K:/Projects/llm-stack/kdash-ts-prototype && bun tui/kdash.ts --url http://localhost:55423`
and fix the first shape mismatch against the real API.
**Done when:** TUI renders live data across 4 screens and the compiled binary
starts in < 60 ms.

### Phase 4 — Port pure leaf logic to TS · **M** · gated on G1

`pricing`, `model_normalization`, `format`, scoring/`compute`, `dateutil`,
`clientpaths`. All pure functions with existing coverage.
**Done when:** byte-identical outputs vs Python across the corpus.

### Phase 5 — Port the parsers · **L** · gated on G1 + G2

`coding_tools.py` (98.7 KB) — the perf hot path and the biggest single chunk.
**Done when:** identical session/token/cost output on every fixture *and* the real
corpus, parser by parser.

### Phase 6 — Port quota sources + usage store · **L**

`sources/quota/{omp,clinepass,zenmux}.py`, `usage_store.py`, `compute.py`, on
`bun:sqlite`. Then `cli.py` + serve.

### Phase 7 — Cutover · **M**

Retire Python only when every tab, CLI command and onboard target has a
differentially-proven TS counterpart.

---

## 5. Recommendation

**Do Phases 1–3 regardless of G1.** They are pure gain, independent of the fork
decision, and they capture the only perf win the measurements actually support.
Answer G1 and G2 before committing to Phase 4+.

## 6. Risk register

| Risk | Mitigation |
|---|---|
| Ported parser silently mis-costs usage | differential tests on the **real corpus**, not fixtures alone |
| Adopting Tailwind-only screens drops i18n/theming/PWA | Phase 2 acceptance criteria |
| Fork lock-in | gate G1; land the three upstream PRs **before** Phase 4 |
| `pricing_db.json` staleness | keep as data, never reimplement |
| Perf claim overreach | only Phase 3 is justified by today's measurements |

## 7. Icebox

- `onboard/` installers — port last or keep in Python (least benefit, most OS risk).
- i18n message extraction for TS screens.
- Sessions / Stats / Pricing screens in TS (the prototype never modelled them).
- The three upstream PRs (omp quota, ZCode parser, Zed parser) — **worthless after
  a fork, so file them first.**
