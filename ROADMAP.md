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

Provider tool/turn usage and hard in-flight spend caps remain unsupported. Successful
live model editing, live-client hook firing and real CI-service delivery are not
established. POSIX runtime behavior was verified on Linux for M5/M6; Windows runtime
behavior for M6 is exercised by CI only.
