# Roadmap

- **M0 — delivered:** requirements, architecture, typed task/provider/project/result
  contracts, transitions, verification policy, initial security model and benchmark design.
- **M1 — delivered:** sequential execution, Typer CLI, SQLite, FakeProvider, Codex CLI,
  isolated worktrees, context packets, checks/evidence, cancellation and safe checkpoints.
- **M2 - verified offline:** Claude Code permission/output adapter,
  capability registry and explicit provider switching, conservative command discovery,
  and Python/JavaScript portability through both adapter transports using CLI emulators.
  Successful live editing is not established. Detected commands require confirmation.
- **M3 - next:** deterministic task/risk classification, role registry and bounded planner,
  debugger and independent reviewer workflows; repeat-failure detection and targeted retries.
- **M4:** supported opt-in hooks, normalized trigger envelopes, idempotency keys,
  deduplication and tested reentrancy guards. No automatic interception claims.
- **M5:** complete stream-to-disk artifacts, provider usage aggregation, pricing estimates
  separated from measured spend, finer budgets, cache invalidation and reproducible A/B/C
  benchmarks for verified success, latency, cost, retries and human intervention.
- **M6:** dependency scheduling, ownership, max-three concurrency, independent worktrees,
  safe integration and approvals, CI triggers, more providers and optional MCP.

Later milestones must not weaken completion or recovery guarantees to improve speed.
