# Changelog

## M5 - verified offline

- Stream redacted provider/check artifacts with bounded excerpts, explicit capture
  failures and completeness metadata; bound protocol parsing separately from disk logs.
- Add per-invocation selected models, `eng usage`, native-field coverage, manually
  versioned pricing estimates, role model routing and reported-usage stop/resume limits.
- Add opt-in in-memory content-hash context reuse (default off) and reproducible
  scripted A/B/C benchmarks. Windows cache measurements show no speed improvement.
- Preserve completion/review/approval and unknown-outcome protections. Live editing,
  live client hooks, runtime scheduling and Git/CI triggers remain unvalidated/deferred.
- Offline suite: 429 passed, 1 opt-in paid live test skipped (400.49 seconds);
  final build and fresh-wheel smoke passed. Historical results below are unchanged. See docs/VALIDATION.md for the measured fixture evidence.

## M4 - verified offline

- Add normalized TriggerEnvelope contracts with pure, high-precision routing: `eng:`
  requests route in every mode; adaptive/full modes add imperative change requests;
  questions, slash commands, ambiguous prose and reentrant (ENG_ACTIVE) prompts bypass.
- Add SQLite migration 3 with atomic trigger claims, id-based idempotency and a
  120-second content-digest window; records keep digests and redacted envelopes.
- Add the fail-open `python -m eng.integrations.hook` entry point for Claude Code and
  Codex `UserPromptSubmit`; it never exits 2 and blocks a prompt only once a detached
  `eng start` runner is working on it.
- Add `eng hooks install|uninstall|status`, `eng trigger`, `eng triggers` and
  `eng start`. Installers write only project-local client files, preserve other hooks,
  bind the hook to the installed project and keep the checkout clean via
  `.git/info/exclude`.
- Tests set `GIT_CEILING_DIRECTORIES` to the parent of each test's temporary
  directory, so Git discovery from inside it cannot reach an enclosing checkout, and
  e2e hook runs default to the fake provider.
- Verified offline: 341 passed, 1 opt-in live test skipped; see docs/VALIDATION.md.
  No live client hook firing is claimed.

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
- Mitigate deep Windows paths with a shallow snapshot root (plus Git `core.longpaths`,
  which alone was insufficient; very deep trees still fail closed), separate
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
