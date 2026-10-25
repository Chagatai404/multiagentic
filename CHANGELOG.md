# Changelog

## Unreleased - M2

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
