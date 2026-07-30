# NEXT — kdash

## Current focus
- Python remains the runnable reference for the TypeScript strangler migration.
- Phase 5 is complete: all 11 coding-tool parsers have TS counterparts.
- Phase 6 is complete locally: quota, storage, compute, sessions, stack/update,
  CLI/server, static assets, and dashboard routes run on Bun.
- Verification baseline: Python 694 pass/7 skip; TypeScript 179 pass/0 fail.

## Next actions
1. Export representative Amp data into `~/.amp/exports` and acquire real
   corpora for Codex, Gemini, Antigravity, Kimi, Copilot, Hermes, and Mimo.
2. Run the Bun dashboard against those corpora and verify every browser tab,
   session detail path, guarded write, and CLI command end to end.
3. Decide Phase 7 only after that evidence: keep Python as fallback or approve
   its retirement explicitly.

## Open decisions
- Publication candidates requiring per-PR approval: omp quota, ZCode parser,
  and Zed parser.
- Distribution for `kdash-ts` and `kdash-tui` remains undecided.

## Caveats / icebox
- Amp reads explicit `amp threads export` snapshots; it never logs in or polls.
- Existing unrelated cleanup: browser auto-open behavior and the pre-resync
  backup branch/tag. Destructive removal still requires explicit approval.
- Internal package rename and optional TUI enhancements remain deferred.
- Derive branch, remote, worktree, and push state with Git; do not freeze it here.
