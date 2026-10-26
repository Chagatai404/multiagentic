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
- **M6:** dependency scheduling, ownership, max-three concurrency, independent worktrees,
  safe integration and approvals, Git/CI triggers, more providers and optional MCP.

Later milestones must not weaken completion or recovery guarantees to improve speed.

Provider tool/turn usage and hard in-flight spend caps remain unsupported. Successful
live model editing, live-client hook firing and POSIX runtime behavior are not
established by Windows offline verification.
