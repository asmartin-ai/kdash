# NEXT — kdash

## Current focus
- **Web GUI retired, TUI-only (2026-07-31):** the browser dashboard is gone;
  kdash is consumed via `kdash-tui` + the loopback API. README rewritten
  TUI-first; removal record: `docs/WEB_GUI_RETIREMENT.md` (dated snapshot).
- This repo is documentation/scripts only (no Python package). Python
  preservation unchanged: tag `python-retired-1.3.1` + branch `python-retired`
  (pushed to origin).

## Next actions
1. **Logon durability:** from an interactive terminal run
   `bun src/cli.ts setup --auto` (in the kdash-ts repo) so the winsched task
   gets a LogonTrigger — currently one-shot. The live service otherwise stays
   up via `supervisor-ts.pyw` on-demand.
2. Retire the dead `TokdashSupervisor` scheduled task + `scripts/supervisor.pyw`
   (Python rollback path is now moot) — needs explicit approval.
3. Zed/OMP/aider usage parsers remain deferred (see
   `docs/WEB_GUI_RETIREMENT.md`); ZCode + LiteLLM parsers shipped 2026-07-31.

## Open decisions
- Nothing blocking. Deferred: internal package rename, kdash-tui distribution
  beyond the local exe.
