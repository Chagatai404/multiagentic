# M5 - Resource visibility and measured optimization

## Primary goal

Users can inspect complete redacted evidence and resource usage across every role,
stop further model work at explicit resource limits, and compare workflows on the
same reproducible engineering fixtures without invented cost or quality claims.

## Phase 0 - Discovery (complete)

How this serves the primary goal: establish the real transport, accounting and
verification contracts before optimizing them.

Base: Claude's M4 commits `9283fb7`, `55afd35`, inspected locally. Implementation is
isolated on `agent/codex/m5-observability`; Claude's checkout remains untouched.
Three discovery agents inspected `execution/process.py`, provider parsers,
`core/models.py`, `core/engine.py`, `storage/store.py`, `context/packet.py`,
`benchmarks/offline.py`, existing tests, architecture and the original build prompt.
Current artifacts truncate at 2 MB; task.usage is latest-result only; authoritative
invocations need model metadata. No context cache or repeated A/B/C harness exists.

## Phase 1 - Parallel implementation

How this serves the primary goal: independent owners deliver evidence, safe resource
decisions and a measurable optimization against unchanged completion safeguards.

### A - Transport and artifacts (medium reasoning)

Own `execution/process.py`, new execution capture helpers, `providers/codex.py`,
`providers/claude.py`, `verification/runner.py`, and focused new transport tests.
Copy lifecycle/cleanup patterns from run_process and provider contracts. Add optional
redacted disk sinks, bounded diagnostic excerpts, byte/truncation/completeness metadata.
Redact before writing, including credentials split across chunks and long values.
Keep draining or terminate/reap on artifact failures. Preserve argv/env isolation.
Providers consume complete artifacts or bounded incremental protocol state, never a
silently truncated prefix. Oversized protocol records fail explicitly and preserve
complete redacted artifacts; no unbounded readback. Existing parse functions and
artifact names remain compatible. Check output is also streamed. No adapter flags
change; no live provider invocation.

### B - Accounting, budgets and routing (high reasoning)

Own `core/models.py`, new pure `core/accounting.py`, `core/engine.py`,
`storage/store.py`, `cli.py`, and focused new accounting/engine/CLI tests.
Copy transactional reservation/checkpoint patterns from Store and Engine. Add a
backward-compatible migration for per-invocation selected model and an invocation
query across executions. Aggregate per provider/model/role with field-level known
subtotals and missing coverage. Retain native cache semantics, latest task.usage and
unknown crash outcomes; no universal input+cache token sum.
Explicit project role_models select a model only when TaskSpec.model is absent.
Record selection before effect. Optional user-supplied pricing is versioned/labeled
estimation with declared inclusive/exclusive input semantics; no hardcoded current
prices or inferred measured spend. Expose reporting through `eng usage`.
Add optional reported-token and reported-cost stop thresholds, checked before the
next model invocation; unknown coverage pauses conservatively. Initial call can run
with no prior usage. Thresholds cannot cap in-flight CLI usage and must say so.
Persist checkpoints before pausing; retain deterministic verification, verify-only,
approval and unknown-outcome replay protections. Explicit resume extensions supported.
Record context/cache and role elapsed events without claiming inference timing.
Wire `eng benchmark` to C's harness after its API is ready.

### C - Context cache and benchmark harness (medium reasoning)

Own `context/packet.py`, new `context/cache.py`, narrow Git stdout normalization in
`execution/workspace.py`, new `eng/benchmark.py`, `benchmarks/*` and focused new tests.
Copy bounded selective context and protected/symlink checks. Add an injected in-memory
content-hash cache, no persistent plaintext context store. Hash current bounded source
bytes on each retrieval, reuse decoded material only on content matches; same-size,
same-mtime edits, policy changes, deletion, branch/workspace changes must invalidate.
Cache static references only; never cache objectives/evidence/diffs/role handoffs.
Keep build_packet default behavior/API compatible, optional cache keyword allowed.
Preserve leading whitespace in NUL Git filenames. Reviewer packets exclude engineer
and debugger prose, including nested repair handoffs. Structured role contracts remain.
Compare cached/uncached packet content and instrument hits/misses/hash/decode work.

A/B/C uses six seeded scenario categories: small bug, medium feature, large refactor,
failing tests, cross-module integration, architecture violation. Same initial files,
acceptance and external evaluator for every arm. A/B run standalone benchmark paths,
never weaken production Engine. C uses adaptive Engine. Deterministic scripted edits
are fixtures, not model intelligence. Record raw rows, verified success, first-pass
success, calls, repairs, intervention, escaped defects, runtime median/P95, and unknown
usage/cost. Repeatable seed/order, clean disposable repositories and Git ceiling.
Expose `run_benchmark(...)` with validated bounded repetitions/scenario selection and
JSON-serializable report; CLI integration owned by B. Measure cached/uncached context
microbenchmark with equal packets; any speed claim follows actual data.

Verification: focused pytest, Ruff, strict mypy for each slice; report files and exact
commands. No commits by implementation owners, paid calls, hook installation in the
real checkout, or changes to another slice's files.

## Phase 2 - Independent verification and review

How this serves the primary goal: prevent apparent resource savings from weakening
correctness, leaking credentials or concealing missing measurements.

Fresh agents run the full offline suite, Ruff, strict Windows/Linux mypy, lock check,
source/wheel build and fresh-wheel CLI smoke. Review actual diff and adversarial
chunk-boundary output, missing/failed/unknown usage, budget recovery, cache invalidation
and unchanged completion/approval protections. Run a repeated six-scenario A/B/C report
and the context cache comparison. Preserve raw evidence and report sample sizes.

## Phase 3 - Documentation and local handoff

How this serves the primary goal: users can reproduce measured results and understand
which limits and provider behavior are established.

A low-reasoning documentation agent updates README, architecture, roadmap, changelog
and validation with verified results/limitations. A low-reasoning commit agent commits
only after verification and review pass. No push or deployment. Runtime parallelism,
Git/CI triggers and unsupported provider tool/turn telemetry remain M6/future work;
live-client hooks and successful live model editing remain unvalidated. Do not claim
offline fixture savings demonstrate real-model cost or task-quality improvements.

## Verification outcome

The offline full run passed 429 tests with the paid live test skipped. A subsequent
bounded failure-log tail fix passed 33 affected regression tests, including three
new cases. Independent review rechecked secret overlap, JSON numeric preservation,
monetary boundaries and the bounded tail. See `docs/VALIDATION.md` for package checks
and exact evidence. The 54-observation scripted benchmark is preserved under
`benchmarks/results/`. Cache reuse measured slower here and remains opt-in.
The repository's own test timeout and wall budget were raised to fit its measured
400-second suite; global defaults remain unchanged. No paid calls or pushes ran.
