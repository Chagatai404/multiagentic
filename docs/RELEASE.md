# eng 1.1.0 - release notes

eng is a provider-independent engineering orchestrator: it turns a task or a plan of
tasks into isolated Git worktrees, runs a coding agent, and decides completion only from
real project checks (plus independent review and explicit approval where risk requires
them). Nothing is pushed, deployed, merged into your branch or cleaned up without an
explicit command.

## What is new in 1.1.0

| Slice | Capability |
|---|---|
| Install | `eng install` / `eng uninstall` for the user (default) or a project; hooks for Claude Code, Codex, Gemini CLI and Cursor; portable workflow skill; multi-agent keyword routing |
| E0 | Usage report schema 2: native usage coverage, selected vs actual model, measured packet sizes and timings, outcomes; unknown stays unknown |
| E1 | Additive per-node budgets and role sublimits frozen at plan creation; plans default to one worker; limited plans serialize launches with durable reservations; `eng plan preview` |
| E2 | Digest-bound dependency handoffs, opt-in `context_reuse`, node `interfaces`, human-only `eng plan attest` replacing a node's initial planner call |
| E3 | Explicit `routing` rules choose models per role call and providers per task/node by classification; explicit choices win; every decision is logged |
| E4 | Opt-in `workflow.repair_headroom` and `workflow.stop_unchanged_repairs` |
| E5 | `--preset` / plan `preset`: economy, balanced, rigorous, with calls derived from required roles |

Design records: [ADR-001](efficiency/ADR-001.md) to [ADR-005](efficiency/ADR-005.md).
Evidence: [E0/E1](efficiency/VERIFICATION.md), [E2](efficiency/VERIFICATION_E2.md),
[E3-E5](efficiency/VERIFICATION_E3_E5.md). Defaults stay conservative: without `context_reuse`,
attestations, routing rules, workflow economies or a preset, role workflows are the
1.0.0 ones; the E0/E1 reporting and budget changes above (including concurrency 1 as
the new plan default) apply to everyone.

## Included from 1.0.0

| Milestone | Capability |
|---|---|
| M0-M1 | Typed contracts, state machine, SQLite state, worktrees, checks, cancellation, recovery |
| M2 | Codex and Claude Code adapters, capability registry, project discovery |
| M3 | Adaptive classification, planner/engineer/debugger/reviewer, approvals, bounded repair |
| M4 | Opt-in Claude Code / Codex prompt hooks, idempotent triggers, detached runner |
| M5 | Streaming redacted artifacts, usage accounting, role models, reported-usage stops, benchmarks |
| M6 | Parallel plans, ownership, verified integration, gated promotion, Git/CI triggers, command providers, MCP |

Start with the [README](../README.md); design is in [ARCHITECTURE](../ARCHITECTURE.md);
evidence is in [VALIDATION](VALIDATION.md).

## Guarantees (each backed by tests)

- COMPLETED requires every required check to PASS; model confidence never completes work.
- A plan node is integrated only if ownership and protected-path rules hold, the merge
  is clean and the project's checks pass on the integrated tree; otherwise the branch
  is rolled back.
- Your branch moves only through `eng plan promote --approve`, as a verified fast-forward.
  eng never pushes and never removes a workspace.
- At most three plan nodes / verifications run per project at any time.
- Approvals (high-risk work, promotion) are human CLI actions; the MCP server and hooks
  expose no way to grant them.
- Hooks fail open and never overwrite hooks they did not write; blocking pre-push blocks
  only a definitive required-check failure.
- Missing usage stays unknown; no price, cost or speed claim is made without data.
- 1.1.0 reuse, routing, repair economies and presets never waive required checks,
  independent review, high-risk approval, ownership or manual promotion. Plan
  attestations, like approvals, are human CLI actions with no MCP or hook path.

## Known limitations (read before relying on it)

1. **No live provider editing has been validated.** Codex and Claude adapters are tested
   with protocol emulators; the one live Codex attempt (M1) could not edit files because
   of a Windows workspace restriction. Run your own bounded trial (`eng run ... --provider
   claude` on a scratch repository) before trusting it with real work.
2. Hooks were never fired inside live Claude Code/Codex sessions; CI triggers were never
   delivered by a real CI service; command providers were never run against a real CLI.
3. Worktrees are not security sandboxes. Provider and check commands are trusted code.
4. Redaction is pattern- and known-secret-based, not a general secret scanner.
5. No hard spend cap: limits stop *new* calls from reported usage; providers that do not
   report usage pause conservatively. Provider tool/turn limits are unsupported.
6. Plans need Git 2.40+, a clean source checkout while they run, and one confirmed
   required check. Integration reuses your checks, so a weak suite gives weak integration.
7. M6 passes the full offline suite on Windows in CI, but only with emulated providers and
   local Git; deep Windows paths can still fail closed (see M3 notes).
8. The context cache is opt-in and was slower on the measured fixture; no benchmark of M6
   scheduling exists.
9. Runtime parallelism shares one SQLite database and one Git object store; three
   concurrent nodes is a deliberate ceiling.
10. **No efficiency claim is established for 1.1.0.** Dependency handoffs, attested
    planning, routes, repair economies and presets reduce orchestration calls in offline
    fixtures only. Their effect on real tokens, cost and quality is unmeasured; the
    owner-authorized live protocol in `docs/efficiency/BENCHMARKS.md` has not been run.
11. E2-E5 were verified on Linux locally and by the CI matrix below; there was no
    separate independent review of those slices. Expanded usage dashboards are not
    included.

## Release checklist

| Step | Status |
|---|---|
| Full offline suite (Linux, CPython 3.13, local) | 713 passed, 2 skipped, 1 deselected |
| Ruff, strict mypy, `uv lock` | pass |
| Source + wheel build, installed-wheel smoke | pass |
| GitHub Actions on the pushed branch (ubuntu/windows x 3.12/3.14, MCP, package) | CI_PENDING |
| Live provider smoke test with credentials | **not run - owner action** |
| Fast-forward `main`, Git tag `v1.1.0`, GitHub Release | via the manual `release` workflow |
| Package index (PyPI) upload | **not done - owner action** (no credentials here) |
