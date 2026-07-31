# NEXT — kdash

## Current focus
- **Cutover COMPLETE (2026-07-31):** Python retired, fork severed, kdash-ts is
  the sole runtime serving :55423. Decision record + verification evidence:
  `docs/TS-Cutover-Plan-2026-07-30.md` (marked complete).
- Python preservation: tag `python-retired-1.3.1` + branch `python-retired`
  (pushed to origin) pin the final Python tree; 119 commits remain in history.
- This repo is now documentation/scripts only (no Python package).

## Next actions
1. **Logon durability:** from an interactive terminal run
   `bun src/cli.ts setup --auto` (in the kdash-ts repo) so the winsched task
   gets a LogonTrigger — currently one-shot (non-interactive shells are denied
   logon-trigger creation). The live service otherwise stays up via
   `supervisor-ts.pyw` on-demand.
2. Retire the dead `TokdashSupervisor` scheduled task + `scripts/supervisor.pyw`
   (Python rollback path is now moot) — needs explicit approval.
3. Consider filing the three forfeited upstream PRs as standalone TS features
   (omp quota, ZCode parser, Zed parser) if wanted.

## Open decisions
- Nothing blocking. Deferred: internal package rename, TUI enhancements,
  distribution of kdash-tui beyond the local exe.

## Caveats / icebox
- winsched task XML must be UTF-16 LE (schtasks rejects UTF-8); LogonTrigger
  creation needs an interactive shell (environmental, both stacks).
- Live-corpus differential tests need `TOKDASH_LIVE_CORPUS=1` + a Python
  install (retired reference; opt-in by design).
- Derive branch, remote, worktree, and push state with Git; do not freeze it here.
