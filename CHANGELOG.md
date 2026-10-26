# Changelog

## Unreleased - user-wide installation and keyword triggers

- Add `eng install` / `eng uninstall`, defaulting to user scope; preserve project scope
  with `--scope project` and existing per-client hook commands.
- Add keyword routing for multi agent, multi-agent, multiagent and multiple agents,
  selecting planner, engineer, required checks and reviewer with at least three calls.
- Add native Gemini CLI and Cursor hooks alongside Claude Code and Codex, plus a
  portable skill for Copilot and future clients using shared or custom skill roots.
- Preserve unrelated settings, backups, client trust, project checks and human approvals.
- Document persistent tool installation, client coverage and both installation scopes.

## 1.0.0 - M5 close-out and M6

M5 close-out
- Run the offline suite on Linux/POSIX for the first time; fix one platform-dependent
  test (directory-enumeration order). Claude adapter flags re-checked against installed
  Claude Code 2.1.310.

M6 - verified offline
- Add dependency-scheduled plans (`eng plan validate|create|run|resume|status|usage|
  approve|cancel|promote`): DAG validation, conservative ownership-overlap rejection,
  at most three concurrent nodes per plan and per project, independent worktrees that
  start from the integrated head, enforced task ownership (`TaskSpec.owned_paths`).
- Add verified integration: nodes merge serially into `eng/plan/ID` via
  `git merge-tree --write-tree`; required checks run on the integrated tree and any
  failure rolls back. Promotion into the user's branch is explicit, approval-gated,
  fast-forward-only and never pushes. Plan-wide reported-usage limits and explicit
  `--clear-limits`.
- Add Git/CI triggers: `eng verify-ref`/`eng refs`, `eng hooks git install|uninstall|
  status` (post-commit, optional blocking pre-push; never overwrites foreign hooks;
  scrubs Git's hook environment), and `eng ci-trigger` (failure -> one deduplicated
  repair task, CI output quoted as untrusted).
- Add configured command providers (`command_providers` in project.yaml), `eng providers
  -p`/`eng doctor -p`, and an optional dependency-free MCP server (`eng mcp serve`) with
  read-only tools, opt-in `eng_submit`, and no approval tools.
- `changed_paths` no longer detects renames, so both sides of a rename are visible to
  protected-path and ownership checks (a hardening of M1-M5 behaviour).
- SQLite migration 5 (`plans`, `plan_events`, `ref_checks`); `eng --version`; `py.typed`;
  CI jobs for MCP SDK compatibility and an installed-wheel smoke test.
- Not validated: live provider editing, live client hooks, real CI-service delivery,
  third-party command providers. The M6 suite passes on Linux and Windows in CI with
  emulated providers. See docs/RELEASE.md.

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
