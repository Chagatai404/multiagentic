# M3 parallel implementation plan

## Primary goal

Adapt engineering work to complexity and risk, run useful planning and independent
review only when needed, and repair actionable failures within explicit budgets while
preserving verification and crash-recovery guarantees.

## Phase 0 - Discover contracts (complete)

**How this serves the primary goal:** establish compatible interfaces before parallel edits.

Three discovery agents read current models/policy, engine/storage, adapters/context,
tests, architecture and the master prompt's workflow/debugging requirements. Baseline
0534c9a; no overlapping active ownership was found. New branch: agent/codex/m3-adaptive.
Existing provider calls are fresh sessions; no adapter flags need changing in M3.
Use installed code/contracts as the source; do not invent provider schemas or permissions.

## Phase 1 - Three parallel implementation slices

**How this serves the primary goal:** separate pure policy, role execution, and stateful
integration, with exclusive file ownership and explicit dependencies.

### A - Typed workflow and deterministic policy (medium reasoning)

Own core/models.py, core/policy.py, new core/workflow.py, dedicated policy/model tests.
Preserve old JSON defaults and Provider protocol. Agreed names:

- TaskType(change, question), Complexity(small, medium, complex), Risk(low, medium, high).
- Classification(task_type, complexity, risk, reasons); ClassificationOverrides optional
  values; WorkflowPolicy(max_repairs=2); WorkflowDecision(planner, reviewer,
  approval_required, max_repairs).
- RoleHandoff(role, summary, invocation_id, artifact=None, verdict=None,
  findings=[], steps=[], root_cause=None, changed_files=[]). Verdict is pass or
  changes_requested. RepairAttempt(number, failure_signature, handoff=None).
- ProjectConfig.workflow default policy; TaskSpec.classification_overrides default
  empty and human_approved=False. Task gains defaulted classification/workflow,
  handoffs/repairs, pending_role/pending_invocation_id, planning_completed=False,
  review_passed=False, verified_digest/review_digest optional. Checkpoints remain
  compatible; add planned and reviewed if needed.
- classify_task(spec), select_workflow(classification,policy), failure_signature(results),
  workflow_completion_gate(task). Keep existing completion_gate(results) unchanged.

Inference uses deterministic, documented rules. Overrides cannot lower inferred risk
or safeguards. Small low-risk work keeps one engineer invocation and checks. Complex
work plans and reviews; medium/high risk reviews; high risk requires explicit human
approval. Read-only questions bypass engineering with an actionable response and no
workspace/provider call. Unsupported questions must not be marked verified engineering.
Only actual required FAIL outcomes are actionable repairs; missing/unconfirmed/error
checks block. Identical failures stop repeat repair; maximum repairs is configurable.
Budgets.model_calls stays 1 by default; extra role calls require explicit budget.

Verification: old JSON loading, independent axes, non-downgrade rules, role selection,
approval gate, signatures and completion requiring actual checks plus due review.

### B - Role registry, context and guarded role execution (medium reasoning)

Own new agents/ modules, context/packet.py, providers/fake.py, dedicated role tests.
Use core RoleHandoff. RoleRegistry/get_role exposes all five built-in roles and permits
explicit registration without hidden execution. Verifier is deterministic, not a model.
Keep build_packet(task) compatible; extend build_packet(task,role=ENGINEER,*,evidence='').
Planner/reviewer use strict JSON summaries parsed through parse_handoff(role,summary,
invocation_id,artifact=None); planner requires steps, review requires explicit verdict
and consistent findings. Engineer/debugger prose is wrapped in a typed handoff.

Agreed runtime API: async execute_role(provider, request, task, artifact_dir, cancelled)
returns ProviderResult. For planner/reviewer, run in a separate retained standalone
snapshot of the current nonprotected tracked/nonignored contents, initialized as its
own Git repository rather than sharing the task repository's Git metadata. Fingerprint task
workspace and snapshot before/after; unexpected mutation fails closed. No OS sandbox
claim. Expose workspace_digest(workspace)->str for engine evidence binding.
Never follow escaping paths/symlinks when overlaying or constructing bounded packets.
Artifacts stay outside task workspace. Preserve stdin/argv provider contracts and
fresh-session behavior. FakeProvider must not apply fixture edits for read-only roles;
it may return clearly deterministic valid plan/review fixture handoffs.

Verification: strict malformed/negative review rejection, bounded role packets and
redacted focused failure excerpts, mutation detection/isolation, fake role behavior,
unchanged actual task workspace and independent provider requests. No paid model calls.

### C - Engine, storage, CLI and end-to-end workflows (high reasoning)

Own core/engine.py, storage/store.py, cli.py, dedicated M3 integration/migration tests.
This slice gets high reasoning because multiple role invocations, durable repair state,
approval and recovery must compose without silently replaying edits or bypassing review.

Use A's frozen contracts and B's APIs; coordinate interface changes before editing
others' files. Persist decisions, pending role and invocation identity before each
provider call. Migrate invocation persistence from one row per execution to unique
invocation identity plus role/status, preserving old rows and Store.invocation callers.
Each call gets its own artifact directory, preserving existing single-call artifact
paths where required by compatibility tests. Persist role results and repair history.

Flow: classify/approve -> prepare -> optional planner -> engineer -> deterministic
verification -> optional reviewer -> completion. Actionable check/review failures may
invoke a focused debugger, then checks/review again. Stop identical failures, retry
limit, unavailable checks, cancellation or resource limits without losing changes.
Inspect changed-path risk before acceptance and preserve mandatory protections.
Bind passing verification and review to workspace digests; stale/mutating review cannot
complete work. No provider result can override the deterministic completion gate.

Every provider_started outcome remains unknown after a crash. Resume never replays it
implicitly. --verify-only makes no model calls: it acknowledges inspection, runs checks,
and pauses with due planning/review retained. A subsequent explicit resume can perform
the pending role; review-required work cannot complete from checks alone. Uncertain
planner output must not be silently treated as a completed plan. Persist retries before
side effects so continuation cannot reset the limit. Retain task locks/cancellation.

CLI adds task type/complexity/risk overrides, max repairs, model call budget and explicit
--approve-high-risk. Resume supports explicit model-call budget extension and human
approval for a saved task; provider output cannot set approval. Automatic pushes remain
forbidden. eng plan/debug commands may remain deferred if run/resume expose the workflow.

Verification: trivial one-call path; complex plan/implement/check/review; high-risk gate;
successful targeted repair; two-attempt and identical-failure stops; reviewer failure,
malformed output and mutation; budgets/cancellation; crash checkpoints for every role;
verify-only retaining review; migration preserving existing invocations and all M2 tests.

## Phase 2 - Independent review and verification

**How this serves the primary goal:** validate combined behavior with real disposable
Git repositories and subprocess checks, not model confidence or overlapping mock tests.

Fresh low-reasoning verifier runs full offline pytest, Ruff, strict mypy Windows/Linux,
build/lock checks and wheel smoke. Fresh medium reviewer audits recovery, budgets,
approval, review independence and false-completion paths. A low-reasoning anti-pattern
audit checks boundaries, bounded context, no shell/bypass/provider flags in core and
no claims that M4 hooks or M6 parallel scheduling are operational. Route verified
findings to their owning slices. Documentation uses low reasoning and records actual
results/limitations. A low-reasoning agent commits only after verification and review.

## Deferred

Automatic hooks, parallel/subtask scheduling and integration, API/local adapters,
semantic indexing, fine-grained financial/tool budgets and live-model validation.
No paid calls are needed for deterministic M3 acceptance. No automatic publication.
