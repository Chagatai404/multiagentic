# Planning contract

Keep the human-readable spec separate from the small machine-readable dispatch plan.
The JSON plan is `version: 1`, with `id`, `goal`, `spec`, `base_revision`, `decisions`,
`constraints`, `open_questions`, `concurrency` (1–3), `limits`, and `tasks` (1–50). `base_revision` identifies
the inspected source revision, not a guarantee that the checkout is unchanged.

Each task has a stable `id`, `objective`, `depends_on`, `owns`, `reads`, `interfaces`,
`acceptance`, and `checks`. Ownership uses exact relative filenames or directory
prefixes ending in `/`; no globs. Case-insensitive write/write and write/read overlap between unordered tasks
is rejected. Include files to be created. A review-only task can own nothing. Reads
are pointers, not embedded file bodies. Workers must follow repository instructions.

Every acceptance item should name observable behavior. Checks are existing commands
or a concrete manual procedure, not a made-up passing test. The helper never executes
them. Record upstream/downstream interface shape, errors and edge cases before splitting.
If two slices need to discover the same interface, finish that discovery first.

Limits: `packet_chars` bounds each complete serialized packet; `report_chars` is the
worker handoff ceiling; `max_attempts` defaults to 1 (maximum 3); `worker_timeout_seconds`
defaults to 600. Reserve room for integration and one targeted repair if appropriate.
No fixed model is selected by the plugin. Use the user's host/model settings.

The helper produces `plan_digest`, ready task IDs and packets. Its JSON state has
`version: 1`, `plan_digest`, optional `authorization`, and `tasks` keyed by ID. Each
entry contains `status` (`pending`, `running`, `completed`, `verified`, `blocked`), `attempts`,
`summary`, and `evidence` (strings naming checks/results or artifacts). Absent = pending.
Any nonempty `open_questions` list blocks dispatch and Pi authorization. The empty
ready list during an unresolved interview is not completion. Only `verified` dependencies unlock consumers; `completed` means worker output awaits
coordinator inspection. Any running/blocked entry stops a new wave. A changed plan
invalidates old state. Reconcile it explicitly; never silently reuse stale authorization.

The coordinator records verification only after inspecting actual edits and checks.
State is a trusted local coordination record, not an authentication boundary or proof
that a check ran. It cannot replace host permissions. Pi writes dispatch state itself;
other hosts maintain it using their file tools after observable results.

For recovery, inspect the working tree before clearing `running`/`blocked` entries.
Preserve attempt counts and failed evidence. Explicitly set an inspected retry to
`pending` only when attempts remain. Reuse completed work; never automatically
replay an interrupted worker. Replan if contracts, ownership or acceptance changed.

Example helper calls (resolve the script relative to this installed skill):

```sh
node <skill>/scripts/plan.mjs inspect .plans/feature.json
node <skill>/scripts/plan.mjs inspect .plans/feature.json .plans/feature.state.json
node <skill>/scripts/plan.mjs packet .plans/feature.json api .plans/feature.state.json
```

If Node 20+ is unavailable, validate the same rules explicitly and report that the
deterministic helper was unavailable. Do not install an agent runtime to obtain it.
