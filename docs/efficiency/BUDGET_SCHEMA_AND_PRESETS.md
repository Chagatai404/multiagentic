# Budget schema and operator examples

E1 adds partial `BudgetOverrides` at `PlanSpec.node_budgets` (plan defaults) and
`PlanNodeSpec.budgets` (node overrides). Omitted/null fields inherit. Effective
budgets and repair policy are saved when a plan is created, so later project edits
do not silently change new node allocations on resume. Existing saved plans remain
readable. `PlanRecord.budget_schema_version=1` (legacy/default) preserves the old
full-replacement `node_budgets`, including explicit null thresholds; it does not
inherit project thresholds that the old replacement cleared. Newly created plans
store schema 2 with additive inheritance and effective allocation snapshots.

Precedence: engine defaults → optional user YAML → project YAML → plan defaults →
node override. Explicit task CLI options apply to separately created tasks; there is
no additional per-node CLI override layer. `--user-config FILE` on plan create and
preview explicitly supplies user YAML; no hidden user config discovery is implied.
Role threshold fields inherit independently. An explicit CLI resume extension or
clear action is required to change saved limits.

To recover a role call stop, use a repeatable explicit role extension. To remove a
role's call and reported-token/cost sublimits, use a repeatable targeted clear:

```sh
eng resume TASK_ID --extend-role-model-calls reviewer=1
eng resume TASK_ID --clear-role-limits reviewer
```

Extensions require an existing call allocation and cannot raise it above the overall
task call cap. Extend the overall task cap explicitly as well when needed; no role
action extends task or plan limits automatically. `--clear-reported-limits` clears
only enclosing task reported thresholds and retains role limits. Conversely,
`--clear-role-limits` retains enclosing task and plan thresholds, so missing overall
usage can still pause. Clearing and extending the same role together is rejected.
All proposed changes are validated before persistence or approval events and audited
as explicit CLI actions. Verifier is excluded; no MCP/model recovery action is added.

| Field | Meaning |
|---|---|
| `model_calls` | Orchestrator role invocations; includes durable unfinished reservations, not internal provider turns |
| `wall_seconds` | Active task wall budget across continuations |
| `provider_seconds` | Per-invocation timeout including role setup |
| `context_chars` | Orchestrator packet cap, not total provider input tokens |
| `reported_input_tokens`, `reported_output_tokens` | Native counters, before-next-call stops |
| `reported_cost_usd` | Provider-reported-cost threshold only |
| `role_limits` | Optional role call/token/cost sublimits, subordinate to task totals |
| `max_repairs` / `node_max_repairs` | Node / plan repair ceiling, 0–10; cannot waive required review or checks |

`role_limits` accepts planner, engineer, debugger and reviewer. Verifier executes
configured checks and cannot receive model allocations. Role limits never increase
the overall task allowance. If initial required roles do not fit the call budget,
execution pauses for an explicit extension; the preview shows the mismatch.

Example user YAML (`user.yaml`):

```yaml
budgets:
  model_calls: 5
  context_chars: 12000
  role_limits:
    reviewer:
      model_calls: 1
```

Example plan (`plan.yaml`), with a trusted project's required checks already configured:

```yaml
name: narrow-interface-change
concurrency: 1
node_budgets:
  wall_seconds: 600
  provider_seconds: 180
node_max_repairs: 1
nodes:
  - id: css
    description: Adjust the button color
    acceptance: ['The button uses the agreed blue']
    owns: ['web/button.css']
    budgets:
      model_calls: 1
    max_repairs: 0
  - id: core
    description: Refactor the cross-module architecture
    acceptance: ['Existing interface tests pass']
    owns: ['src/core/**', 'tests/core/**']
    budgets:
      model_calls: 6
      context_chars: 20000
      role_limits:
        debugger:
          model_calls: 1
```

```sh
eng plan preview plan.yaml --user-config user.yaml -p .
eng plan create plan.yaml --user-config user.yaml -p .
eng plan usage PLAN_ID
```

Preview constructs no provider, database or worktree. Its initial role-call count is
hypothetical: changed-path risk escalation, repairs and repeated review may add work.
Token/dollar projections remain null. Review proposed scope and allocations before
the separate human `plan run` action.

Plans default to concurrency 1; explicitly configured concurrency 2–3 remains
supported. A plan with any reported usage threshold serializes launches and checks
the shared history before each role. There is no defensible token reservation
estimate, so it reserves a single launch slot rather than inventing token amounts.
SQLite launch reservations persist crashes; unknown usage blocks later launches.
In-flight overshoot remains possible. Inspect unknown provider outcomes and use the
existing explicit verify-only/resume path; never replay an uncertain side effect.

Economy/balanced/rigorous are operator-authored examples, not implemented preset
flags or evidence of optimality. For a small low-risk task an economy configuration
might use one call, no repairs and concurrency 1. A balanced configuration might
allow five calls and one repair; a rigorous one might allow eight calls and two
repairs. Choose enough calls for mandatory planner/reviewer roles. All three retain
the same inferred risk, independent review, human approval and required checks.
