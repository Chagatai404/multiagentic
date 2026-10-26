# Accounting and limits (report schema 2)

`eng usage TASK` and `eng plan usage PLAN` export JSON. Existing `invocations`,
`groups`, cost coverages and `measured_account_spend` fields remain available.
Each Coverage has `known_subtotal`, `reported` and `missing`; a subtotal is not a
complete total when `missing > 0`. No observations yields null, not zero usage.

| Quantity | Evidence and scope |
|---|---|
| Orchestration invocation | Durable reservation, before a role side effect; includes unfinished reservations |
| Provider execution | Measured entry to the adapter's `execute` method; not proof a CLI launched or authenticated |
| Provider CLI session / internal model or tool turns | Unavailable; one adapter invocation may perform many internal turns |
| Selected provider/model | Saved operator selection; `groups.provider` / `groups.model` |
| Actual model | `ProviderResult.actual_model`, only explicit provider evidence; current built-in adapters leave it unknown |
| Packet chars / UTF-8 bytes | Measured final request sent to the adapter, after read-only snapshot path rewriting; not hidden/system/tool context |
| Input/output/cache/reasoning | Native provider-reported counters; missing fields remain null |
| Reported cost | Provider-reported amount with `cost_source=reported`; not independently measured account spend |
| Client estimate | Separate `client_estimate_cost_usd`; Claude CLI's `total_cost_usd` belongs here |
| Pricing estimate | Only an explicit provider/selected-model pricing rule with version, label and cache semantics |
| Account spend / subscription allowance | Unavailable; no subscription-credit inference or implicit pricing |

Cache/read/creation/reasoning counters are never added to input/output to manufacture
billing totals. Pricing rules explicitly state whether input includes cache counters.
Pricing uses the selected-model key and cannot certify which model actually ran.

`totals` aggregates each native field and each measured metric independently.
`groups` retain provider/selected-model/role attribution, actual-model coverage,
persisted outcome counts and timing coverages. `tasks` attributes native counters by
task ID across executions, reports active wall time, repair attempts and completed
repair handoffs. A completed repair handoff is not proof of a repaired defect.
`human_acceptance` and `repaired_defects` remain null; COMPLETED records deterministic
workflow completion, never human acceptance or integration.

CLI reports include full saved check history, outcomes and durations. `checks_scope`
distinguishes supplied history from latest task results when the pure report API is
used without history. Task check outcomes describe the latest verification only.
`measurement_sources` declares measurement categories and `missing_telemetry` makes
coverage gaps explicit. Provider duration is process/adapter duration, not inference
time. Role duration includes setup and mutation detection. Active wall time excludes
idle time between executions; crash duration is not reconstructed.

New telemetry lives in existing invocation-result JSON; historical records remain
readable. Crashed reservations lack result telemetry and remain unknown. Context
events separately retain measured construction chars/bytes/timing even if the call
does not finish. Evidence retains the existing bounded, redacted artifact capture.

`budget_status` shows effective limits, configured remaining allowance, role call
counts, known threshold overshoots and pause reasons. It does not predict future
usage or account balance. Token/cost thresholds stop before the next invocation,
including between roles; the initial call or any in-flight call can exceed a limit.
Unknown required coverage stops further work until explicit inspection/extension or
clearing. Client estimates cannot satisfy a reported-cost threshold. Deterministic
checks and required review/approval gates remain independent of cost accounting.

Explicit role recovery uses `eng resume TASK --extend-role-model-calls reviewer=1`
or `--clear-role-limits reviewer`. These changes never raise enclosing task/plan caps;
the enclosing `--clear-reported-limits` option also leaves role sublimits intact.

See [budget schema](BUDGET_SCHEMA_AND_PRESETS.md) and [benchmark protocol](BENCHMARKS.md).
