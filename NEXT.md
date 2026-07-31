# NEXT — kdash

## Current focus
- Target decided: **full cutover to TypeScript, retiring Python** — but a safe
  deletion is multi-phase. Route + gates: `docs/TS-Cutover-Plan-2026-07-30.md`.
- **Phase C complete (2026-07-31):** the TS service now serves :55423
  (TokdashTSSupervisor → supervisor-ts.pyw → bun). Python stays on disk as
  fallback (rollback: re-enable TokdashSupervisor task). Baseline: Python
  694 pass / 7 skip; TypeScript 227 pass / 0 fail.
- **Phase D (delete Python) is the remaining phase** — gated on G1 + deletion
  gate (§5). Do not delete `src/tokdash` before then.

## Next actions
1. Run `bun src/cli.ts setup --auto` from an INTERACTIVE terminal so the
   winsched task gets a LogonTrigger (non-interactive shells are denied
   logon-trigger creation) — gives the TS service reboot durability.
2. Decide **G1** (upstream-fork severance) — the gate to Phase D.
3. When G1 = yes and the deletion gate is green, remove `src/tokdash` +
   tests + upstream remote (explicit approval required).

## Open decisions
- **G1 (blocks deletion):** accept permanent severance of the `JingbiaoMei/Tokdash`
  upstream fork? Deletion is downstream of an explicit "yes".
- Publication candidates still needing per-PR approval: omp quota, ZCode parser,
  Zed parser (worthless after fork severance — file first if ever).

## Caveats / icebox
- **Amp deprecated** 2026-07-30: unregistered from the tracker (no `~/.amp` here).
  Parser code + tests retained, git-reversible; excluded from the parity gate.
- Free-pool signal reads `K:/Projects/free-pool/state.json` (override
  `TOKDASH_FREE_POOL_STATE`); returns None → static registry estimate.
- winsched task XML must be UTF-16 LE (both stacks' installers fixed 2026-07-31);
  LogonTrigger creation needs an interactive shell.
- Internal package rename and optional TUI enhancements remain deferred.
- Derive branch, remote, worktree, and push state with Git; do not freeze it here.
