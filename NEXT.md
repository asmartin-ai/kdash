# NEXT — kdash (resynced 2026-07-22)

*Renamed from `tokdash-fork` 2026-07-20. Resynced from upstream v1.3.1
(`6deb1ed`) 2026-07-22 — see `docs/RESYNC-2026-07-22.md` for the full
postmortem. Further post-resync work: ZenMux quota card added, then
claude/zai/codex API replaced with omp.*

## Status
- **694 tests pass, 0 fail, 7 skip** (+41 from Phase 1 scoring port; 7 skips
  include 3 codex-HUD removal, 3 ambient/snapshot fixtures, 1 codex session
  snapshot).
- Branch: `main`, ahead of `upstream/main` (resolve with `git status -sb`).
- Remote topology: `origin` → `github.com/asmartin-ai/kdash.git`, `upstream`
  → `github.com/JingbiaoMei/Tokdash.git`. Tagged `v1.3.1.kdash1`.
- Pre-resync backup branch: `add-zcode-litellm-zed`, tagged
  `pre-resync-snapshot` (resolve with `git rev-parse pre-resync-snapshot`).
- Single canonical copy at `K:/Projects/llm-stack/kdash/`; `K:/Projects/kdash`
  is a junction to it.
- Serves on `:55423`; 5 Quota cards wired (Claude, Codex, ClinePass, Z.ai,
  ZenMux). Consent keys: `omp_api`, `clinepass_api`, `zenmux_api`.

## Quota architecture (2026-07-22)
- **omp.py** runs `omp usage --json` once per poll → covers Anthropic,
  Codex, and Z.ai (3 providers, 1 subprocess call, no OAuth/API keys).
- **clinepass.py** → ClinePass (CLINE_API_KEY env)
- **zenmux.py** → ZenMux Starter (ZENMUX_MANAGEMENT_API_KEY env)
- Unused: antigravity (commented out, re-enableable), codex session
  parsing (local files, still active for Tools/Usage tab).
- Deleted: claude.py, zai.py, codex.py API path (~500 LOC removed).

## Next actions
1. **Delete backup branch** after confidence: `git branch -D
   add-zcode-litellm-zed` (remove `pre-resync-snapshot` tag).
2. **Kill browser auto-open** (the wrapper opens a tab every time `kdash`
   is called — see `~/bin/kdash` self-heal logic). Options in the
   investigation from 2026-07-21.
3. **TypeScript migration — Phase 6 runtime parity complete** (plan:
   `docs/TS-Rewrite-Plan-2026-07-28.md`).
   - **Phase 1** (DONE 2026-07-28): scoring layer additive to `suggest.py`.
     `recommendations`/`free_pool`/`alerts`/`scored_models` + `?tier=` filter.
     41 new tests. Commit `8a722d0`.
   - **Phase 2** (DONE 2026-07-28): 3 new dashboard tabs (Subscriptions, APIs,
     Models) from existing `/api/quota` + `/api/suggest`. i18n en+zh, CSS vars.
     Commit `8a722d0`.
   - **Phase 3** (DONE 2026-07-29): `kdash-tui` shipped to its own repo
     (`c486ebb`). 4 screens, `bun build --compile`, cold-start ~82ms.
   - **Phase 4** (DONE 2026-07-29): 7 pure-leaf TS modules ported to
     `kdash-ts/` with byte-identical differential tests. 127→129 tests.
     G1 resolved: fork accepted. Commit `a06796e` (+ `adb9320` cleanup).
   - **Phase 5** (DONE, 11/11 functional): Codex, Gemini, Antigravity, Amp,
     Kimi, PiAgent, Copilot, Hermes, and Mimo have differential TS ports.
     PiAgent matches 18,549 real entries; locally absent corpora pass non-empty
     isolated fixtures rather than vacuous empty-array checks. Amp reads
     explicit `amp threads export` JSON from `~/.amp/exports` or
     `TOKDASH_AMP_EXPORT_DIR`; its fixture follows the verified public export
     schema and covers PowerShell UTF-8 BOM output.
   - **Phase 6 runtime parity** (DONE locally 2026-07-30): `kdash-ts` owns
     quota collection, `bun:sqlite` storage, compute/stats/OpenClaw
     orchestration, scored suggestions, session list/detail, stack/update,
     Bun CLI/server, static assets, and the complete dashboard API matrix.
     Full TS gate: **179 pass, 0 fail**. Python retirement now waits on
     representative real-corpus parity, browser cutover verification, and
     explicit deletion approval.

## Icebox
- **PR to upstream tokdash**: suggest reusing oh-my-pi's `omp usage --json`
  for quota tracking instead of per-provider OAuth/HTTP. omp already
  exposes the same data for Anthropic, Codex, and Z.ai with zero auth
  management. A PR adding an `omp_api` consent option (or a
  `sources/quota/omp.py` mirror) would simplify the upstream quota
  architecture the same way we just did for kdash. See `src/tokdash/
  sources/quota/omp.py` for the reference implementation (~170 LOC,
  mostly subprocess + JSON mapping).
- Bump `pyproject.toml` version to `1.3.1.kdash1`-style fork suffix
  (blocked on PEP 440 compliance — the format `1.3.1.kdash1` was rejected
  by setuptools).
- Rename internal Python package `tokdash` → `kdash` (full rebrand).
- Drop `glance.py`'s SuperGrok + Freebuff fetchers to match the suggest.py
  cleanup.
- The `clinepass-implementer.md` Zcode subagent at `~/.zcode/agents/` is
  wired but blocked on ClinePass's DS V4 Flash route returning empty
  content.
- **Add ZCode as an upstream-supported tool**: ZCode writes per-session
  `transcript.jsonl` + `metadata.json` under `~/.zcode/cli/agents/sess_*/`
  — a stable, documented format.  The kdash fork already has the path
  resolution (`clientpaths.zcode_root()`, `zcode_transcript_glob()`,
  `zcode_metadata_glob()`).  Still needed: a `ZcodeParser(BaseParser)` in
  `coding_tools.py`, a session handler in `sessions.py`, and the `zcode`
  entry in `SESSION_TOOLS` / the `--sources` default list.  A PR to
  upstream JingbiaoMei/tokdash adding this (alongside our existing
  OpenCode/Codex/Claude parsers) would make the fork unnecessary for this
  feature.
- **Add Zed as an upstream-supported tool**: Zed stores agent-thread
  token usage in `threads/threads.db` (SQLite with serialized thread JSON
  blobs).  The kdash fork has path resolution (`clientpaths.zed_data_dir()`,
  `zed_threads_db_paths()`, `zed_db_dirs()`).  A parser is more involved
  than JSONL (it's a SQLite DB), but paves the way for every Zed user.
  Same PR track as ZCode.
