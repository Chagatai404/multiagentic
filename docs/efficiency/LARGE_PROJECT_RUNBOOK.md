# Large-project runbook

1. Configure trusted, confirmed required checks. Record scope, acceptance and interface
   decisions in repository documentation. Keep credentials out of context/evidence.
2. Split narrow ownership patterns into a dependency DAG. Parallel nodes must have
   provably disjoint ownership; use dependency edges when one node needs another's
   interface. Keep architectural decisions explicit rather than copying full histories.
3. Assign separate node budgets and role sublimits. Start at concurrency 1; inspect
   `eng plan preview plan.yaml -p .` for initial role calls and insufficient allocations.
   Preview is hypothetical and performs no model call, approval or state creation.
4. Create the plan, inspect saved effective allocations, then use the existing human
   run/approval commands. Optionally set `context_reuse: true` and declare node
   `interfaces`; after reviewing each node spec, `eng plan attest PLAN_ID NODE` to skip
   its initial planner call (high-risk nodes are refused; review and checks still run). High risk still requires explicit human approval. There is
   no model-callable approval or promotion endpoint.
5. Inspect `eng plan usage PLAN_ID`: known subtotals, missing telemetry, check history,
   role outcomes and saved allocations. With plan-wide reported thresholds, launches
   serialize. A single in-flight invocation can still exceed a token/cost threshold.
6. At a pause, read the reason and bounded artifacts. Unknown outcomes require manual
   inspection and the existing explicit `eng resume TASK_ID --verify-only` procedure.
   Extend/clear limits only through human CLI actions; do not replay uncertain calls.
7. Verify each milestone before expanding concurrency or budgets. Nodes have independent
   worktrees; integration is serialized and rechecks the merged tree. Inspect the final
   diff and evidence before the separate human promotion command. Nothing pushes.

No live paid calibration is authorized by these steps. Use
`eng benchmark --efficiency --repetitions 1 --seed 0` for offline fixture evidence and
follow the [calibration protocol](BENCHMARKS.md) only after explicit owner confirmation.
Fixture success establishes policy/transport behavior, not real-model savings.

E2 plan/context reuse is implemented as described in [CONTEXT_AND_PLAN_REUSE.md](
CONTEXT_AND_PLAN_REUSE.md). E3 automatic provider/model routing, E4 new retry
optimizations and E5 preset flags are deferred. Existing role_models remains explicit configuration.
No dispatch settings change in this efficiency slice: per-client/manual defaults stay
as configured; the earlier top-level keyword installer behavior remains an existing
owner opt-in. No hooks are installed or enabled as part of this upgrade.
