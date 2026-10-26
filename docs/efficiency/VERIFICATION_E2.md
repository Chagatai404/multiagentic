# E2 verification checkpoint — 2026-10-26

Scope: [ADR-002](ADR-002.md) dependency handoffs, opt-in dependency-scoped packets,
interface contracts and human plan attestations. Offline only. No paid provider,
live client, push, deployment, promotion or destructive cleanup was performed.

## Tested source identity

- Branch: `claude/funny-hamilton-p4v8ki` (local), based on the E0/E1 checkpoint
  `1090be9fe89a94b04520d90d0cd5ebfd7c8572f2` from `agent/codex/efficiency-e0-e1`.
- Implementation commit: `d1046d8` (local, not pushed). This report and the
  coordination update are a separate documentation commit; no runtime file changed.
- Environment: Linux 6.18 container, CPython 3.13.17, Git 2.43.0, `uv` managed venv.

## Results

| Gate | Command | Result |
|---|---|---|
| Complete offline suite | `uv run pytest -m 'not live' -q -p no:cacheprovider -rs --basetemp <scratch>/pt` | **683 passed, 2 skipped, 1 deselected**, 118.75 s |
| Focused E2 | `uv run pytest tests/unit/test_reuse.py tests/integration/test_plan_reuse.py tests/integration/test_mcp.py` | 6 + 10 new tests, MCP guard; passed |
| Lint | `uv run ruff check .` | Passed |
| Strict types | `uv run mypy --strict src/eng` | Passed, 53 source files |
| Wheel and sdist | `uv build --out-dir <scratch>/dist` | Passed; sdist contains ADR-002, `core/reuse.py` and E2 tests |
| Installed-wheel smoke | isolated venv, `python -I`: import `eng.core.reuse`, validate a `context_reuse` plan with `interfaces`; `eng plan attest --help` | Passed |
| Diff whitespace | `git diff --check` | Passed |

Skips: `tests/integration/test_mcp_sdk.py` (optional `mcp` SDK not installed) and
`tests/unit/test_runner.py` job breakaway (Windows-only). Deselected: the opt-in paid
Codex smoke. `ruff format --check` reports three files that were already unformatted
on the base commit (`providers/claude.py`, `providers/codex.py`,
`verification/runner.py`); they were left unchanged to keep the diff in scope.

## What the new tests establish

- Scope and policy digests: node and task digests agree; every scope field and every
  policy field (checks, protected paths, instructions) changes the digest; budgets and
  repair limits do not.
- Dependency handoffs: recorded on integration with bounded summary/files, review
  verdict and interfaces; rendered only for dependents when `context_reuse` is on;
  re-changed files marked stale; tampered digests, policy changes and unknown
  revisions are omitted with a manifest reason and never crash the coordinator.
- Uncached path: with reuse off, no prompt contains handoffs, no manifest event is
  written and task specs carry no reuse data.
- Attestations: an attested complex node runs engineer and reviewer (no planner
  invocation record) and completes with checks and review passing, against
  planner/engineer/reviewer for the same node unattested. Owned-path edits after
  attestation, scope/policy mismatch, unknown revisions and high risk fall back to
  the model planner with an event. High-risk and launched nodes are refused;
  revocation is all-or-nothing and clears an unplanned launched task. The CLI
  `--all` skips high-risk and launched nodes. The MCP tool list contains no
  attest/approve/promote/resume tool.

## Not established

Real token, cost or quality effects of shorter planning or dependency summaries; live
provider editing; live client hooks; real CI delivery; Windows runtime for E2 (only
Linux was run here). No separate independent reviewer pass was run for this slice;
the author re-read the diff and fixed two findings (attestation check moved after
workspace safety checks; non-fatal revision checks) before the final gate. E3–E5
remain deferred.
