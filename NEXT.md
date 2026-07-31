# NEXT — kdash

## Current focus
- Target decided: **full cutover to TypeScript, retiring Python** — but a safe
  deletion is multi-phase. Route + gates: `docs/TS-Cutover-Plan-2026-07-30.md`.
- Python remains the runnable reference until the cutover plan's deletion gate
  is green. Do not delete `src/tokdash` before then.
- Verification baseline: Python 694 pass / 7 skip; TypeScript 178 pass / 1 known
  date flake (see plan §4).

## Next actions
1. **Restart the live dashboard service** (`pythonw -m tokdash serve` on :55423)
   to pick up today's free-pool + recommendations fixes — currently running
   pre-edit code in memory.
2. Cutover Phase A: fix the `stack` day-count differential flake (plan §4) and
   convert the differential suite to golden fixtures so TS tests survive without
   Python.
3. Cutover Phase B: port the onboard/service lifecycle (setup/doctor/update/
   uninstall + winsched installer) to kdash-ts — the biggest gap.

## Open decisions
- **G1 (blocks deletion):** accept permanent severance of the `JingbiaoMei/Tokdash`
  upstream fork? Deletion is downstream of an explicit "yes".
- Distribution for the TS runtime (`bun build --compile` vs a bun service unit).
- Publication candidates still needing per-PR approval: omp quota, ZCode parser,
  Zed parser (worthless after fork severance — file first if ever).

## Caveats / icebox
- **Amp deprecated** 2026-07-30: unregistered from the tracker (no `~/.amp` here).
  Parser code + tests retained, git-reversible; excluded from the parity gate.
- Free-pool signal reads `K:/Projects/free-pool/state.json` (override
  `TOKDASH_FREE_POOL_STATE`); returns None → static registry estimate.
- Internal package rename and optional TUI enhancements remain deferred.
- Derive branch, remote, worktree, and push state with Git; do not freeze it here.
