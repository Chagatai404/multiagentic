# Changelog

## M3 - verified offline

- Add deterministic independent task-type, complexity and risk classification;
  route questions without an engineering workspace or model call.
- Add role registry, bounded planner/reviewer packets and retained standalone
  snapshots with mutation detection; verifier remains deterministic.
- Add required planning/review, explicit high-risk task approval and bounded focused
  debugger repairs, stopping identical failures and unavailable verification.
- Persist per-role invocation identities/status/results, handoffs and repair attempts;
  preserve unknown-outcome recovery and checks-only continuation without review bypass.
- Expose classification, approval, repair and model-call budget CLI options, including
  explicit resume extensions. Default model-call budget remains one.
- Fix deep Windows paths for Git (`core.longpaths`, shallow snapshot root), separate
  `role_setup` from `role_mutation`, keep mutation evidence when a provider raises,
  report Git timeouts as Git failures, and keep a review-requested repair pending at
  budget exhaustion so an explicit extension runs the debugger.
- Verified offline: 249 passed, 1 opt-in live test skipped; see docs/VALIDATION.md.
  No live model editing or CI execution is claimed.

## M2 - verified offline

- Add Claude Code file-only safe/restricted CLI transport, conservative result/error
  parsing, provider-specific credential environments and client-estimate cost metadata.
- Register fake, Codex and Claude providers; expose capabilities and bounded version-only
  doctor probes without claiming authentication or model availability.
- Discover explicit Python pytest configuration and JavaScript test scripts as unconfirmed
  checks; resolve supported Windows npm launchers without eng shell interpolation.
- Add a Python/Node x Codex/Claude adapter transport-emulator portability matrix.
  Successful live editing remains unvalidated; the runtime workflow is sequential.

## 0.1.0 — 2026-10-25

Initial M0/M1 vertical slice: provider-independent contracts, explicit state machine,
sequential engine, SQLite persistence and event evidence, isolated Git worktrees,
Codex and deterministic fake adapters, bounded context and subprocess lifecycle,
configured verification, cancellation and conservative recovery. Includes offline
benchmark, contract/unit/integration tests and opt-in live Codex smoke coverage.
