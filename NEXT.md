# NEXT — kdash

## Current focus
- Target decided: **full cutover to TypeScript, retiring Python** — but a safe
  deletion is multi-phase. Route + gates: `docs/TS-Cutover-Plan-2026-07-30.md`.
- Python remains the runnable reference until the cutover plan's deletion gate
  is green. Do not delete `src/tokdash` before then.
- **Phase A complete (2026-07-31):** stack date flake fixed (DST-immune UTC
  day math, `kdash-ts 379ea32`); differential suite converted to golden
  fixtures (`4b41d07`) — TS tests pass with `TOKDASH_NO_PYTHON=1`. Verification
  baseline: Python 694 pass / 7 skip; TypeScript 220 pass / 0 fail.
- **Phase B complete (2026-07-31):** `doctor`, `update`, `setup`, and
  `uninstall` (winsched) ported to kdash-ts with parity (dry-run plans
  byte-compatible; applied schtasks verified via stubbed tests).
  Verification baseline: Python 694 pass / 7 skip; TypeScript 227 pass / 0 fail.

## Next actions
1. **B3: decide distribution** — `bun build --compile` binary vs a bun service
   unit (open decision below).
2. Complete the §5 verification matrix against the Bun server, then install
   the TS service on :55423 (Phase C).
3. After Phase C: the G1 + deletion-gate decision (Phase D).

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
