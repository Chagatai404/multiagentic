# Roadmap

- **M0 — delivered:** requirements, architecture, typed task/provider/project/result
  contracts, transitions, verification policy, initial security model and benchmark design.
- **M1 — delivered:** sequential execution, Typer CLI, SQLite, FakeProvider, Codex CLI,
  isolated worktrees, context packets, checks/evidence, cancellation and safe checkpoints.
- **M2 - verified offline:** Claude Code permission/output adapter,
  capability registry and explicit provider switching, conservative command discovery,
  and Python/JavaScript portability through both adapter transports using CLI emulators.
  Successful live editing is not established. Detected commands require confirmation.
- **M3 - verified offline:** deterministic independent task-type,
  complexity and risk classification; role registry, bounded planning and independent
  review, explicit high-risk task approval, targeted repairs and repeat-failure stops.
  Per-role invocation persistence retains conservative recovery. No live validation
  claimed; `eng plan`/`eng debug` deferred.
- **M4 - verified offline:** opt-in project-local `UserPromptSubmit` hooks for Claude Code
  and Codex, normalized trigger envelopes, idempotency keys, deduplication, reentrancy
  guards, read-only bypass and detached runners, tested with emulated client input.
  Live hook firing inside real clients is not validated; Git/CI triggers move to M6.
- **M5 - verified offline:** streaming redacted artifacts with bounded
  parsing/excerpts and completeness metadata; all-role native usage coverage, manual
  pricing estimates, role models and reported-usage stops before new calls. Opt-in
  content-hash caching defaults off (slower on the measured Windows fixture).
  Repeated scripted A/B/C results are preserved; no live-model cost/quality claim.
- **M6 - verified offline:** dependency-scheduled plans with enforced ownership,
  max-three concurrency (per plan and per project), independent worktrees based on the
  integrated head, serialized merge-tree integration with post-merge verification and
  rollback, approval-gated fast-forward promotion, Git hook / `verify-ref` / CI-failure
  triggers, configured command providers and an optional read-only MCP server.
  Tested on disposable repositories, emulated CI events, real Git hooks and the official
  MCP client SDK. No live provider, CI-service or client-hook validation is claimed.
- **1.0.0 release:** M0-M6 complete; see [release notes](docs/RELEASE.md) for the
  evidence and the list of what is deliberately not claimed.

Later milestones must not weaken completion or recovery guarantees to improve speed.

- **Efficiency E0/E1 — current slice:** versioned usage/coverage reports, final packet
  UTF-8 measurements, honest outcome/acceptance gaps, offline quality control cases,
  inherited per-node budgets, subordinate role limits, saved allocations, conservative
  plan-wide launch/call stops and a provider-free hypothetical preview. Validation
  evidence is recorded in `docs/VALIDATION.md`; no paid-model savings are claimed.
- **Efficiency E2 — verified offline:** digest-bound dependency handoff index,
  opt-in dependency-scoped packets with stale-file marking, declared interface
  contracts, and human `eng plan attest` attestations that replace only a node's
  initial planner call, invalidated on scope, policy, revision or owned-path change.
  Review, checks, approval and ownership are unchanged; no live savings are claimed.
- **Efficiency E3 — verified offline:** explicit operator routing rules select models
  per role call (re-evaluated after risk escalation) and providers per task or plan
  node, with capability validation and recorded decisions. Explicit selections win;
  workflow gates are unchanged. No route is shown to save cost or keep quality.
- **Efficiency E4 — verified offline:** opt-in `repair_headroom` (admit repairs only
  when the debugger and required review fit the remaining calls/allocations) and
  `stop_unchanged_repairs` (pause instead of re-checking/re-reviewing an unchanged
  tree). Defaults are unchanged; no required role, check or inspection is dropped.
- **Efficiency E5 — verified offline:** `--preset` / plan `preset` economy, balanced and
  rigorous bundles; calls derived from required roles plus allowed repairs, explicit
  settings win. Not evidence of optimality. Expanded dashboards were not added;
  existing in-memory cache remains off by default.

Provider tool/turn usage and hard in-flight spend caps remain unsupported. Successful
live model editing, live-client hook firing and real CI-service delivery are not
established. POSIX runtime behavior was verified on Linux for M5/M6, and the M6 suite passes on
Windows in CI (emulated providers only).
