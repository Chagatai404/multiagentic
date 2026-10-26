# eng 1.0.0 - release notes

eng is a provider-independent engineering orchestrator: it turns a task or a plan of
tasks into isolated Git worktrees, runs a coding agent, and decides completion only from
real project checks (plus independent review and explicit approval where risk requires
them). Nothing is pushed, deployed, merged into your branch or cleaned up without an
explicit command.

## What is in 1.0.0

| Milestone | Capability |
|---|---|
| M0-M1 | Typed contracts, state machine, SQLite state, worktrees, checks, cancellation, recovery |
| M2 | Codex and Claude Code adapters, capability registry, project discovery |
| M3 | Adaptive classification, planner/engineer/debugger/reviewer, approvals, bounded repair |
| M4 | Opt-in Claude Code / Codex prompt hooks, idempotent triggers, detached runner |
| M5 | Streaming redacted artifacts, usage accounting, role models, reported-usage stops, benchmarks |
| M6 | Parallel plans, ownership, verified integration, gated promotion, Git/CI triggers, command providers, MCP |

Start with the [README](../README.md); design is in [ARCHITECTURE](../ARCHITECTURE.md) and
[M6_PLAN](M6_PLAN.md); evidence is in [VALIDATION](VALIDATION.md).

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

## Release checklist

| Step | Status |
|---|---|
| Full offline suite, Python 3.12 / 3.13 / 3.14 | 554 passed, 3 skipped on each |
| Concurrency stress (6 CPU burners on 4 cores, 6 runs, 63 tests) | pass after the starvation fix |
| Ruff, strict mypy (linux + win32), `uv lock --check` | pass |
| Source + wheel build, wheel-to-source byte comparison | pass (52 files) |
| Fresh-wheel end-to-end smoke (plan lifecycle, MCP, hooks, verify-ref) | pass |
| MCP official-SDK interoperability | pass (mcp 2.3.0, scratch env) |
| GitHub Actions on the pushed branch (ubuntu/windows x 3.12/3.14, MCP, package) | pass, run 9 on `c4cd75d` (6/6 jobs); earlier runs 7-8 found two test-side issues, fixed |
| Live provider smoke test with credentials | **not run - owner action** (`ENG_LIVE_CODEX=1` for Codex) |
| Merge to `main`, Git tag `v1.0.0`, GitHub Release | done: fast-forward merge, then the manual `release` workflow tagged `cc4d2d4` and attached the sdist and wheel |
| Package index (PyPI) upload | **not done - owner action** (no credentials here) |

Remaining steps (not performed): run a bounded live trial with your provider, and if you
want a package-index release, upload the artifacts attached to the `v1.0.0` release (or
`python -m build`) with your credentials.
