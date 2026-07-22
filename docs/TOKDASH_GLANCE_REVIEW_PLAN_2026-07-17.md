> **DEPRECATED 2026-07-21:** `scripts/tokdash_glance.py` removed; canonical location is now `src/tokdash/glance.py`. The historical review notes below are retained as-is. References to `scripts/tokdash_glance.py` and `tests/test_tokdash_glance.py` (the `importlib`-based loader) describe the pre-refactor layout — the tests now live in `tests/test_glance.py` and import the package module directly.

# Tokdash Glance review plan — 2026-07-17

## Scope and decision

Reviewed the current worktree, the `tokdash-glance` capture supplied on 2026-07-17,
and the uncommitted Suggest feature. Original review was **plan only**.

**Status update (same day, post-other-session):** P0–P2 below were implemented and
committed on `add-zcode-litellm-zed` (not pushed):

| Commit | Summary |
|--------|---------|
| `93308c8` | `docs: document Pi and Oh My Pi session paths` |
| `fe94087` | `feat(suggest): add shared recommendation policy and dashboard` |
| `e8832d5` | `feat(glance): add policy rail and resilient provider meters` |

Focused tests: `tests/test_tokdash_glance.py` + `tests/test_suggest.py` +
`tests/test_suggest_api_contract.py` → **24 passed** (2026-07-17). Tree clean after
those commits.

Remaining work in this doc is the **Codex Free usage** follow-up (user request after
the three commits landed) plus small review notes.

---

## Confirmed Claude bug (fixed)

In `scripts/tokdash_glance.py`, `_glance_claude_plan_body()` had one path that
recorded cached quota meters before it recorded the `CLAUDE` section heading:

```python
if now_m - _CLAUDE_OAUTH_LAST_CALL < _CLAUDE_OAUTH_COOLDOWN_S:
    if _load_claude_usage_cache() and _render_claude_cached():
        section("CLAUDE", f"plan={plan} · cached")
```

`_render_claude_cached()` emitted meter records using the current section. In compact
mode that current section was still the previous provider (normally `ZENMUX`), so
the cached Claude rows could be grouped and placed before their heading. Live and
fallback paths used `finish()`, which emits the Claude heading first.

**Fix landed:** cooldown uses `finish("cached", …)` so section is recorded first.
Covered by `test_cooldown_records_claude_section_before_meters`.

---

## Implementation plan (original P0–P2)

### P0 — correct record ordering — DONE

1. Focused `tests/test_tokdash_glance.py` via `importlib`.
2. Cooldown case with prior `ZENMUX` section; assert first Claude record is section
   and every Claude meter has `section == "CLAUDE"`.
3. Cooldown/cache branch routes through `finish("cached", …)`.
4. Companion assertions for live, 401/frozen, 429/backoff paths.

Acceptance: refresh during OAuth cooldown never puts a Claude bar under ZenMux.

### P1 — compact rendering testable/robust — DONE

1. Layout fixtures at 72/80/100/140 cols; rail column stable; lines fit width.
2. `sanitize_display()` on section/meter/info/warn/err (strip CR/LF/CSI).
3. Unicode display-cell width **deferred** — no fixture failure required `wcwidth`.

### P1 — Suggest contract — DONE

1. API tests for `get_suggest()` schema (`schema_version` / `pick` / `fallbacks`).
2. Reload contract: `?refresh=1` → `force_refresh=True` on `_cached_route`.
3. Static UI emits `?refresh=1` when `opts.force`; shows `response_cache`.
4. Policy errors → 500; missing live ZenMux still returns static policy.

### P2 — documentation and hygiene — DONE (with notes)

1. `docs/Suggest-Design-2026-07-14.md` Phase 1 next-action updated.
2. `NEXT.md` rewritten for glance + Suggest landing.
3. AppData live glance copy sync is operator step (not in Git).

**Hygiene still open (non-blocking):**

- Trailing whitespace in `docs/Suggest-Design-2026-07-14.md:99` (`git diff --check`
  reported on the suggest commit).
- P2 test gap: `test_401_freeze_and_429_backoff_section_order` asserts a CLAUDE
  section exists but does not assert meter ownership under CLAUDE (only cooldown +
  live paths do). Easy strengthen later.
- Smell: `render()` provider order + key gates are a duplicated table; extract a
  single provider-spec list **before** adding Codex as a first-class glance section.

---

## Codex Free plan usage (new — next feature slice)

### Why this is next

User is on ChatGPT/Codex **Free** (`chatgpt_plan_type=free` in `~/.codex/auth.json`
id_token / access_token claims as of 2026-07-17). Codex session
`019f7178-9a50-7bc3-8e4e-2c34d679565f` hit the Free usage wall mid-turn
(“try again at Aug 16th, 2026 2:07 PM”). Stack docs already record the plan as
free/TBD; tokdash should **mirror live Free windows**, not invent tier limits.

### What already exists (do not reimplement)

| Surface | Behavior |
|---------|----------|
| `sources/quota/codex.py` | API + session snapshots; `plan_type` on buckets; primary≈5h, secondary≈7d; reset credits |
| `quota_state()` | `providers.codex.plan` via `_codex_plan_label` — **already maps `free` → `Free`** |
| Dashboard Quota tab | Codex cards when `codex_api` consent / session rows present |
| Glance `PLAN_APPS` | default `claude,codex` — tools row tags codex as **plan** (no $) |
| Suggest `get_suggest` | reads `quota_state` peaks for claude/codex/zai/cline **but only passes** claude/cline/zai into `build_suggest` — **codex peak is dropped** |

### Gaps

1. **No glance CODEX section.** Provider `order` in `render()` has zenmux/claude/… —
   no `glance_codex()`. Free windows are invisible in the TUI unless the user opens
   the browser Quota tab.
2. **Suggest ignores Codex Free.** Policy brain has SuperGrok/Hy3/Agnes/ZenMux free
   lanes but no Codex Free entry, no `codex_peak_pct` / `codex_plan` inputs, and no
   routing when Free is exhausted until a distant reset.
3. **Do not hardcode Free limits.** Limits and reset times come from
   `rate_limits.primary` / `secondary` (and usage API). Free vs Plus only changes
   plan label + whatever windows the API returns — treat `plan_type` as an enum
   already handled by `_CODEX_PLAN_LABELS`.

### Implementation plan

#### P0 — glance CODEX meters (mirror quota, section-before-meters)

1. Add `glance_codex()` that prefers live tokdash data:
   - Prefer `GET {TOKDASH}/api/quota` (or equivalent already used elsewhere) when
     the ambient server is up; else optional local `quota_state()` import if cheap.
   - If neither works / no codex rows: skip silently (same as key-gated providers)
     **or** show one info row when `~/.codex/auth.json` exists — pick one and test it.
2. Render `section("CODEX", f"plan={label}")` **before** any meters (reuse Claude
   invariant). Label from provider plan (`Free` / `Plus` / …).
3. Meters for each bucket with `used_percent` / remaining (5h, 7d, extra windows if
   present). Sanitize labels via `sanitize_display`.
4. Register in the single provider order table (extract table if adding a third
   key-gate pattern would grow the `if name == …` chain further).
5. Tests: section before meters; Free plan subtitle; empty/unavailable skip;
   compact width still holds with a CODEX block present.

Acceptance: during Free cooldown / exhausted window, glance shows CODEX with
remaining % and reset hint, never under ZENMUX.

#### P1 — Suggest: wire Codex Free into the policy brain

1. Extend `build_suggest(...)` with:
   - `codex_peak_pct: Optional[float] = None`
   - `codex_plan: Optional[str] = None`  # raw or label; normalize to lower
   - optional `codex_reset_hint: Optional[str] = None` if already available
2. In `get_suggest` fetch path: keep scanning `providers["codex"]`; **pass** peak +
   plan into `build_suggest` (today peak is computed then discarded).
3. Policy rules (Free-first, no invented caps):
   - When `codex_plan` in `{free, Free}` **and** peak is None/low: inventory row
     under free/power or “interactive plan apps” — Codex Free is a **time-boxed
     interactive** lane, not a serial free executor like Agnes.
   - When peak ≥ hot threshold (reuse ZenMux/Claude hot bands or a dedicated
     constant): demote Codex in `pick` / `fallbacks`; surface reset in `use_next`
     / deadlines if reset time known.
   - When plan is Plus/Pro/etc.: still pass peak for demotion, but do not label as
     free overflow.
4. Tests: Free + low peak includes Codex; Free + hot peak demotes; missing codex
   provider unchanged; schema_version bump only if agent contract fields change
   (prefer additive inventory fields without bump if possible).

Acceptance: `/api/suggest` reflects Free exhaustion the same day the API does;
agents do not need to parse glance strings.

#### P2 — docs / stack cross-link

1. tokdash `NEXT.md`: Codex Free glance + Suggest as next 1–3 actions.
2. Optional one-line in `docs/Suggest-Design-2026-07-14.md` addendum: Codex Free is
   live-window-driven, not a static free slug list.
3. LLM-dev pricing row already notes free JWT claim — no change unless plan type
   changes after re-auth.

### Commit plan (Codex Free slice)

Keep separate from the landed three commits:

1. `feat(glance): show Codex plan windows in compact HUD`
2. `feat(suggest): route on Codex Free quota peak`

Or one commit if both stay under ~200 LOC — prefer two if tests are large.

### Verification

- Focused: new glance + suggest tests + existing 24.
- Manual: `tokdash-glance` with ambient `tokdash serve` and `codex_api` consent on;
  confirm Free label + 5h/7d during limit.
- `GET /api/suggest?refresh=1` after a Codex limit event shows demotion / reset hint.
- Do **not** push `add-zcode-litellm-zed` unless asked.

### Non-goals

- Scraping ChatGPT marketing pages for Free monthly caps.
- Auto-upgrading or re-auth flows inside tokdash.
- Treating Codex Free as a drop-in for ZenMux free slugs or SuperGrok.

---

## Original commit plan (executed)

Do **not** re-land. Historical:

1. `docs: document Pi and Oh My Pi session paths` → `93308c8`
2. `feat(suggest): add shared recommendation policy and dashboard` → `fe94087`
3. `feat(glance): add policy rail and resilient provider meters` → `e8832d5`

---

## Verification checklist (landed work)

- [x] Three commits on `add-zcode-litellm-zed`
- [x] Focused Suggest + glance tests (24 passed)
- [ ] Full suite green (one pre-existing period-semantics failure may remain)
- [ ] Manual `tokdash-glance --watch` during Claude cooldown
- [ ] Suggest tab Reload freshness after `tokdash serve` restart
- [ ] AppData `glance.py` synced to repo script

## Verification checklist (Codex Free — implemented 2026-07-17)

- [x] `glance_codex` section-before-meters tests
- [x] Suggest passes `codex_peak` / `codex_plan` (buckets peak helper fixed)
- [x] Free hot peak demotes Codex in T4 / SKIP / `use_next`
- [ ] Manual glance + `/api/suggest` after Free limit (operator)
- Focused suite: 32 passed (`test_tokdash_glance` + `test_suggest` + contract)
