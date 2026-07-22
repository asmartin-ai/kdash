# NEXT — kdash (resynced 2026-07-22)

*Renamed from `tokdash-fork` 2026-07-20. Resynced from upstream v1.3.1
(`6deb1ed`) 2026-07-22 — see `docs/RESYNC-2026-07-22.md` for the full postmortem.*

## Current focus

Branch `resync-from-upstream` is ready for cutover. All 8 upstream releases
absorbed (Kimi Code 0.26+ support, K3 pricing, Codex subagent usage fix,
quota-refresh improvements, statusline, 10 themes, PWA, SQLite index, setup
wizard, Tailscale). Custom layer re-applied on top as 9 clean commits.

## Status
- **650 tests pass, 0 fail, 8 skip** (8 skips are intentional: 3 codex-HUD
  removal, 5 ambient/snapshot fixture skips).
- Branch: `resync-from-upstream` — 10 commits ahead of `upstream/main`.
- Remote topology: `origin` → `github.com/asmartin-ai/kdash.git` (new fork),
  `upstream` → `github.com/JingbiaoMei/Tokdash.git`.
- Pre-resync backup branch: `add-zcode-litellm-zed` at `d7b661d` (tagged
  `pre-resync-snapshot`).
- Single canonical copy at `K:/Projects/llm-stack/kdash/`; `K:/Projects/kdash`
  is a junction to it.

## Next actions
1. **Cutover**: fast-forward `main` to `resync-from-upstream` and push to origin
   (the new `asmartin-ai/kdash` fork). Tag `v1.3.1.kdash1`.
2. **Re-install editable**: `pip install -e K:/Projects/kdash` so the .pth
   resolves to the new working tree (currently the .pth is fine — it points
   at `K:\Projects\kdash\src` which the junction routes to this tree).
3. **Smoke test on machine**: `kdash glance` (one-shot + `--watch`), `kdash status`,
   web GUI at `http://127.0.0.1:55423`, confirm Quota tab shows Codex/Claude/
   ClinePass/Z.ai cards (no Antigravity), Tools/Usage tab still has
   `antigravity_cli`.
4. **Delete backup branch** after one cycle of confidence: `git branch -D
   add-zcode-litellm-zed` (and remove the `pre-resync-snapshot` tag).

## Optional follow-ups (icebox)
- Bump `pyproject.toml` version to `1.3.1.kdash1` (or similar fork-suffix
  scheme) so `pip show tokdash` clearly shows the kdash variant.
- Consider renaming internal Python package `tokdash` → `kdash` for full
  rebrand (pyproject.toml `project.scripts`, `[project] name`).
- The `clinepass-implementer.md` Zcode subagent at `~/.zcode/agents/` is
  ready but blocked on ClinePass's DS V4 Flash route returning empty
  content (transient, monitor and retry).
- Drop `glance.py`'s SuperGrok + Freebuff fetchers to match the suggest.py
  cleanup (consistency — currently glance.py still has these sections but
  they're not called by build_suggest anymore).
