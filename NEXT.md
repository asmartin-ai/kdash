# NEXT — kdash (resynced 2026-07-22)

*Renamed from `tokdash-fork` 2026-07-20. Resynced from upstream v1.3.1
(`6deb1ed`) 2026-07-22 — see `docs/RESYNC-2026-07-22.md` for the full
postmortem. Further post-resync work: ZenMux quota card added, then
claude/zai/codex API replaced with omp.*

## Status
- **618 tests pass, 0 fail, 7 skip** (7 skips include 3 codex-HUD removal,
  3 ambient/snapshot fixtures, 1 codex session snapshot).
- Branch: `main` — 12 commits ahead of `upstream/main`.
- Remote topology: `origin` → `github.com/asmartin-ai/kdash.git`, `upstream`
  → `github.com/JingbiaoMei/Tokdash.git`. Tagged `v1.3.1.kdash1`.
- Pre-resync backup branch: `add-zcode-litellm-zed` at `d7b661d` (tagged
  `pre-resync-snapshot`).
- Single canonical copy at `K:/Projects/llm-stack/kdash/`; `K:/Projects/kdash`
  is a junction to it.
- Live serve on `:55423` currently healthy — all 5 Quota cards populated
  (Claude, Codex, ClinePass, Z.ai, ZenMux). Consent keys: `omp_api`,
  `clinepass_api`, `zenmux_api`.

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
