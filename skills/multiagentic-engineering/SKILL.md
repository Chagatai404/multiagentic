---
name: multiagentic-engineering
description: Plan and implement substantial coding tasks with independent native subagents. Use for multi-agent engineering, parallel implementation, or a thorough implementation plan. Co-plan with the user, minimize repeated context, and verify integrated results.
---

# Multiagentic engineering

If assigned a `mae/1` worker packet, implement only that slice and return its handoff;
skip coordinator planning and delegation. The following workflow is for the coordinator.

Keep the conversation's agent as coordinator. Use the host's native delegation tools;
never start another agent CLI, `eng`, a background daemon, or a paid API to emulate them.
Read only [the current host adapter](references/hosts.md). In Orca, also read
[the Orca profile](references/orca.md) to select exactly one scheduling layer.
If delegation is absent,
say so and execute the same plan sequentially when implementation is authorized.

## Plan with the user

1. Inspect repository instructions, status, relevant entry points and existing tests.
   Reuse the user's plan and known decisions; do not start a second planning process.
2. For material unknowns use the bundled `interview` skill. Ask only questions whose
   answers change scope, interfaces, acceptance, or cost. Record assumptions separately.
3. Write `.plans/<slug>.md`: goal/non-goals, current behavior and evidence, desired
   behavior, decisions/tradeoffs, interfaces, risks, acceptance checks, integration
   order and rollback. Use [the spec template](assets/spec.template.md) when useful.
   Preserve the user's priorities. Thorough means decision-complete,
   not long. Small/local tasks need only a short plan and one worker (often yourself).
4. For parallel work, read [the plan contract](references/planning.md) and create
   `.plans/<slug>.json` from [the example](assets/plan.example.json). Prefer small vertical
   slices: one verifiable behavior across the necessary layers, including tests. Split
   by exclusive write ownership; establish shared interfaces before their consumers.
   Assign shared config/lockfiles to one owner. For architecture choices, wide refactors,
   testing strategy or final review, read [engineering practices](references/engineering.md).
5. Validate with the bundled `scripts/plan.mjs` helper or native `mae_plan` tool.
   Show the user the decisions, task/dependency table, concurrency and expected checks.
   Map every acceptance ID to a slice and a check; put unresolved decisions in
   `open_questions`. An unresolved prerequisite blocks dispatch even if files are disjoint.
   If they asked to co-plan or plan only, wait for their approval of this concrete plan.
   Otherwise use existing implementation authorization; never invent a user approval.
   A material scope/interface/budget change returns to the user. Pi's dispatch extension
   additionally requires the user command `/mae-approve .plans/<slug>.json`.

## Execute ready slices

Read [execution and recovery](references/execution.md) only when implementing.
Use validated ready packets, one per worker. Start at most the planned concurrency
(default 2, maximum 3), and only when dependencies are verified in the shared base.
Use one worker for tightly coupled or small work; parallelism must justify its added
context and review cost. Do useful independent integration work while workers run.
Do not recursively delegate. Keep the user informed of decisions and blockers.

## Spend context deliberately

Keep the spec canonical on disk. Send a worker only its objective, owned paths,
acceptance checks, interface contracts, relevant file pointers and direct dependency
handoffs. Do not fork the full conversation, send the repository, load all skills,
or repeat sibling reports. Start with scoped search and line ranges. A worker requests
missing context instead of guessing. Output a compact handoff: changed files, checks
and results, interface changes, blockers. Persist detail once; pass references onward.

Set packet character limits, report limits, worker count and retry ceiling in the plan.
Character counts bound packets, not tokens or bills. Keep actual tokens/cache/cost
unknown unless the host reports them. Record those fields with their provider semantics;
never claim savings without comparable measured runs and equal quality checks.

## Finish

Integrate serially; inspect ownership and diffs, then run the planned checks on the
combined result. Review risky interfaces and behavior independently where useful.
Repair a concrete failure once by default; stop on the same failure or missing evidence.
Report changes, verification evidence, unresolved risks and any unavailable capabilities.
No passing claim from a worker alone establishes completion. Preserve user edits and
the host's permission boundaries. Commit/publish/deploy only within user authorization.
