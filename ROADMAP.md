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
- **M5:** complete stream-to-disk artifacts, provider usage aggregation, pricing estimates
  separated from measured spend, finer budgets, cache invalidation and reproducible A/B/C
  benchmarks for verified success, latency, cost, retries and human intervention.
- **M6:** dependency scheduling, ownership, max-three concurrency, independent worktrees,
  safe integration and approvals, CI triggers, more providers and optional MCP.

Later milestones must not weaken completion or recovery guarantees to improve speed.
