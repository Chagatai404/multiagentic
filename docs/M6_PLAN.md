# M6 - Parallel plans, safe integration, Git/CI triggers, providers and MCP

## Primary goal

A user can split a change into a dependency graph of owned work items, run up to three
of them concurrently in independent worktrees, have each verified result integrated
into an eng-owned branch with fresh verification of the integrated state, and promote
that branch into their own branch only through an explicit approval. Git and CI events
can start verification or repair work, additional coding CLIs can be attached
declaratively, and an optional MCP server exposes read-only state. No completion,
recovery, approval or credential guarantee of M0-M5 is weakened.

## Non-goals and invariants

- No automatic push, merge into the user's branch, deployment or destructive cleanup.
  Promotion is a separate human command, fast-forward only, never pushes.
- A node is only integrated after its own task reaches COMPLETED through the unchanged
  M3/M5 completion gate. Integration adds a second, independent gate: required checks
  must pass on the integrated tree, otherwise the integration is rolled back.
- Concurrency is bounded by `MAX_CONCURRENCY = 3`, enforced both per plan (validation)
  and per project across processes (slot locks).
- Pure policy (`core/plan.py`) imports no I/O. Git, threads, locks and storage live in
  `scheduling/` and `execution/integrate.py`.
- Live provider editing, live client hook firing and live CI delivery are not claimed;
  everything is verified offline with the fake provider, CLI emulators and disposable
  repositories.

## Contracts

`PlanSpec` (YAML/JSON file): `name`, `nodes[]`, `concurrency` (1-3), optional per-node
`node_budgets` and plan-level reported-usage limits. `PlanNodeSpec`: `id`, `description`,
`acceptance[]`, `depends_on[]`, `owns[]` (repository-relative patterns, required),
optional `provider`, `model`, `context_paths`, `risk`.

Validation (pure): unique ids; known, acyclic dependencies; at most 50 nodes; safe
patterns (no absolute paths, `..`, `.git`/protected roots); and **any two nodes that
are not ordered by dependency must have provably disjoint ownership**. Overlap analysis
is conservative: when disjointness cannot be shown, the plan is rejected.

`TaskSpec.owned_paths` (empty = unrestricted, the M0-M5 behaviour) is enforced by the
engine next to the protected-path check: any changed path outside ownership (including
the old side of a rename) FAILS the task before verification. `TaskSpec.base_commit`
lets a node start from the integration head instead of the checkout HEAD.

## Execution

1. `eng plan create` validates, records the base commit, creates branch
   `eng/plan/<id>` and an integration worktree `.engineering/worktrees/plan-<id>`.
2. `eng plan run` (single coordinator per plan, OS lock) launches nodes whose
   dependencies are all INTEGRATED, at most `concurrency`, each as an ordinary task in a
   worker thread with its own store connection, event loop and worktree based on the
   current integration head. Project-wide slot locks cap total concurrent nodes.
3. A COMPLETED node task is snapshotted into a commit (temporary index, node worktree
   untouched), checked against ownership/protected paths, merged with
   `git merge-tree --write-tree` (no worktree mutation on conflict), then the project's
   required checks run on the integrated tree. Failure or conflict rolls the branch back
   and BLOCKS the node; integration is serialized.
4. Failure policy: by default no new nodes start after a node fails, pauses or blocks
   (`--keep-going` continues independent branches); dependents of FAILED/CANCELLED nodes
   are SKIPPED. PAUSED/BLOCKED nodes wait for `eng plan resume` / `eng plan approve`;
   unknown provider outcomes still require `eng resume TASK --verify-only`.
5. `eng plan promote PLAN --approve` requires: every node INTEGRATED, last integration
   verification PASS, branch tip equal to the recorded verified commit, clean checkout on
   a named branch that is an ancestor of the plan head. It then runs `git merge
   --ff-only`. Without `--approve` it only reports what would happen.

## Triggers

- `eng verify-ref REV`: checks a commit in a throwaway worktree with the project's
  confirmed checks and records the outcome (`eng refs` lists them).
- `eng hooks install git`: `post-commit` (non-blocking, detached) and optional
  `pre-push --block`. Existing non-eng hooks are never overwritten; hooks always fail
  open except an explicit blocking pre-push with a definitive FAIL.
- `eng ci-trigger`: a CI failure (run id/attempt idempotency key) becomes a normalized
  trigger envelope that routes one repair task through the M4 claim/dedup/runner path;
  success, cancellation and unknown conclusions bypass.

## Providers and MCP

- `command` providers declared in `project.yaml` (`command_providers`): fixed argv,
  prompt on stdin, scrubbed environment, exit-code/timeout/cancel handling, usage stays
  unknown. No vendor flags are baked into eng.
- `eng mcp serve`: stdio JSON-RPC server, no extra dependency. Read-only tools by
  default; `--allow-submit` adds one tool that routes a task through the same trigger
  path. There is deliberately no approval, promotion or resume tool: approvals stay human.

## Verification

Unit tests for pure plan logic and overlap analysis; integration tests on disposable
repositories for concurrency (observed overlap, never above three), ownership
violation, conflict/rollback, dependency bases, resume/cancel, promotion refusal and
success; trigger e2e; MCP protocol tests, additionally checked against the official
MCP client SDK in a scratch environment. Full suite, Ruff, strict mypy, build and a
fresh-wheel smoke test run before handoff.

## Outcome (as built)

All items above are implemented and verified offline; see `docs/VALIDATION.md` for the
evidence and `docs/RELEASE.md` for limitations. Differences from the plan, found while
building and testing:

- `plan create` also refuses a project without a confirmed required check, and
  `plan resume --clear-limits` is the explicit override for plan-wide usage limits.
- Slot locks are shared by plan nodes and `verify-ref`; ad-hoc `eng run` and hook-started
  tasks are user-initiated and not counted. A coordinator starved of slots waits and
  retries (load testing showed that giving up abandoned ready work).
- Git hooks scrub repository-local `GIT_*` variables before spawning the verifier.
- `changed_paths` uses `--no-renames` for every task (M1-M5 included) so both sides of a
  rename are visible to protected-path and ownership checks.
- Command providers require credential-like `env_allow` names so forwarded values are
  always redacted; `eng providers`/`eng doctor` accept `--project` to include them.
- A CI job checks the MCP server against the official client SDK and another installs the
  built wheel; neither dependency is part of eng.
