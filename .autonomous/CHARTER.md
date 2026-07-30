# Run Charter — 2026-07-30 Local TypeScript migration

## Objective
Complete the local TypeScript engine migration through Phase 6 with differential
fidelity, while keeping the Python implementation runnable as the reference.

## In scope
- Finish every functional Phase 5 parser supported by an available schema.
- Port quota snapshot types, configuration, collection, and state shaping.
- Port `usage_store.py` to `bun:sqlite`.
- Port compute orchestration, CLI commands, and the local HTTP server.
- Add Python reference commands and TS differential/integration coverage for
  every observable contract.
- Use free-pool for bounded analysis where useful; independently verify output.
- Update existing project status files only after verified behavior works.

## Out of scope
- Publishing or updating PRs, pushing, deploying, or any outward-facing action.
- Deleting the Python implementation, branches, tags, or shared/global state.
- `pricing_db.json` changes, `onboard/`, or new Python runtime dependencies.
- A fake Amp implementation without a stable schema and non-empty fixture.

## Pre-authorized irreversible actions
None.

## Done-when
- All Phase 6 quota, store, compute, CLI, and serve paths have functional TS
  counterparts with differential or end-to-end verification.
- The TypeScript CLI can compute usage and serve the dashboard locally.
- The full TypeScript test suite reports zero failures.
- Python remains available as the local reference pending explicit deletion
  approval; publication remains deferred.

## Abort-on
- A baseline test fails for reasons unrelated to the migration.
- The same implementation step fails three times without a new diagnosis.
- A required external schema is unavailable after source/docs investigation.
- A step would publish, push, deploy, delete Python, or mutate shared state.
