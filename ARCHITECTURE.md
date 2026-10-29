# Architecture

## Native plugin path (2.0 beta)

User conversation → shared skill/spec → validated DAG and packets → host-native
workers → coordinator integration and verification. One canonical skill directory is
packaged through root `plugin.json`, Claude/Codex compatibility manifests, OpenCode's
plugin export and Pi's package manifest. No native adapter imports the Python runner,
launches an agent CLI, or installs an MCP server.

`skills/multiagentic-engineering/scripts/core.mjs` is a pure planning layer: contract
validation, conservative path ownership/read dependencies, digest-bound state, ready
waves and compact packets. `files.mjs` confines local plan/state reads. The small
`plan.mjs` executable is a model-free validator, not a runtime agent launcher.

Claude Code and Codex use their session's native tools through skills. OpenCode's
adapter registers tools/agents/skill paths through its configuration hook, preserving
existing user definitions; native Task/subagent tools retain execution/permissions.
These hosts follow a protocol: ownership and state are coordinator responsibilities,
not enforcement by an external process. A helper result is not test evidence.

Pi lacks the same built-in subagent interface. Its extension creates SDK sessions in
process with fresh histories, inherited model/thinking settings, default stored auth,
no loaded extensions/skills, no shell, and ownership-checked edit/write tools. Repository
context instructions remain discoverable. Parent handles checks/deletion/renames.
The user command binds authorization to a plan digest; dispatch writes running state
before model calls and serializes waves with a project lock. Crash locks are deliberately
not auto-cleared. Cancellation and timeouts abort children, retain partial edits and
block downstream work. Completed output still requires coordinator verification.

Boundaries: local files/commands are trusted; authorization state is not tamper-proof.
File guards detect invalid paths and symlinks but are not OS sandboxes (external
concurrent mutations/hardlinks are outside the guarantee). No hard billing ceiling,
account-shared token cap or cross-host lock enforcement is claimed. Only Pi SDK dispatch
uses the project lock; all hosts require one coordinator per plan. Read pointers guide
context selection, not filesystem read isolation. Current Pi custom parent-only auth
and provider extensions are not propagated; use stored credentials or skill-only mode.

The legacy runner remains a separate opt-in architecture and retains its existing
SQLite/worktree/approval semantics; plugin state never reuses its approvals or records.

### Orca workspace profile

Orca is the selected IDE, layered over the existing host packages. Its profile selects
one scheduler: the underlying coding agent's native subagents, or Orca's supervised
Run/task/dispatch layer. The package supplies planning and mapping guidance and relies
on Orca's runtime-provided control guide; it assumes no separate JS plugin API. App
completion never substitutes for coordinator verification. Worker packets select the
worker role immediately, so Pi or other host adapters cannot create a nested worker
pool. The concurrency budget applies across the run. No live Orca certification is
claimed; see `docs/ORCA.md` for worktree/account/WSL and acceptance requirements.

## Legacy external runner (1.x)


Dependency direction: CLI → engine shell → subsystem contracts and adapters. The
functional core is `core/models.py`, `core/policy.py`, `core/accounting.py`, `core/workflow.py`,
`core/plan.py`, `core/reuse.py`, `core/routing.py`, `core/presets.py` and `core/refs.py`: Pydantic
contracts, legal transitions, and evidence-based completion. `core/engine.py` is
explicitly the imperative orchestration shell; it injects a Provider and Store.
Models/policy import no provider, subprocess, filesystem execution, or storage code.

| Layer | Implementation | Boundary |
|---|---|---|
| Interface | `cli.py` | Normalize requests, output JSON, meaningful exit codes |
| Triggers | `core/triggers.py`, `integrations/` | Pure routing/idempotency; client hook I/O, installers, detached runner |
| Orchestration | `core/engine.py` | Sequential workflow and checkpoint recovery |
| Agents/providers | `agents/`, `providers/`, Role enum | Capabilities, request/result, provider-specific transport |
| Project/context | `projects/`, `context/` | YAML snapshot, tracked selective context, character budget |
| Execution/verification | `execution/`, `verification/` | Worktrees, process lifecycle, real check evidence |
| Persistence/telemetry | `storage/` | SQLite transactions, migrations, events, artifact references |
| Plans | `core/plan.py`, `scheduling/`, `execution/integrate.py` | Pure DAG/ownership policy; coordinator, slot locks, serialized integration, promotion |
| Git/CI/MCP | `integrations/git*.py`, `integrations/mcp.py`, `core/refs.py` | Commit verification, Git hooks, CI failure routing, read-only MCP |

## Contracts and invariants

Task ID identifies the objective; each continuation gets a separate execution ID.
ProviderRequest includes role, objective context, working directory, model and
timeout. ProviderResult normalizes success/error/timeout/cancellation, usage and
duration. Unavailable token/cost fields remain null. There is no fake token
estimation. FakeProvider implements deterministic fixture edits. Codex CLI handles its
own tool loop. API and local inference need distinct future adapters, not an
assumption that a text completion can edit a repository. The Protocol is the provider
extension point; capability booleans declare only features the adapter exposes. Roles
are recognized in the contract, but M3 executes Planner, Engineer, Debugger and
Reviewer through explicit role contracts. Verifier runs configured deterministic
checks rather than a model. A provider registry constructs fake, Codex and Claude
adapters without execution effects. Capability listing does not probe model access;
doctor runs bounded version probes and leaves authentication `not_checked`. Explicit
selection overrides configuration; recovery uses the saved provider.

Classification deterministically separates task type, complexity and risk. Bounded
word/path cues and non-downgrading overrides select a workflow; changed paths can
escalate safeguards. Questions return a direct-conversation message without a
workspace/provider call. Small low-risk work runs Engineer then checks. Complex work
runs Planner first and Reviewer after checks; medium/high risk requires review, and
high risk requires explicit human task approval. The sequential state machine supports
planning, implementation, verification, review and focused debugging. Nonterminal
states may pause, fail, or cancel. Terminal states are immutable to execution. All
transitions and checkpoints are transactional. COMPLETED requires at least one
required check and PASS for every required check; SKIPPED, UNAVAILABLE, ERROR and FAIL
cannot satisfy the gate. Required planning, approval and review must also pass; review
and verification are bound to matching workspace digests. Model confidence cannot
satisfy these gates. Acceptance criteria are passed to the engineer and retained;
their semantic evaluation is human-owned.

## Checkpoints and side effects

An OS advisory lock gives each task one active runner and releases on process death.
Cancellation is a separate durable database flag; saving stale task data cannot erase
another process's cancellation. Its acknowledgement is recorded as CANCELLED.

Role-specific bounded packets carry objectives and focused evidence. Planner and
reviewer return strictly parsed handoffs and execute in retained standalone Git
snapshots without shared task Git metadata, kept under the ignored, shallow
`.engineering/artifacts/snapshots/` root to stay below Windows path limits. Task and snapshot content digests detect
mutation; this is detection, not an OS sandbox. Engineer/debugger may edit the task
worktree. Repairs require actionable required-check FAIL evidence or explicit review
findings, default to at most two attempts, and stop on identical failure signatures.
Unavailable/error checks block. Attempts are persisted before side effects.

`prepared` is safe to continue before an invocation. `provider_started` is committed
before invoking the provider. A crash or timeout at that point has an unknown outcome;
resume refuses replay and requires explicit `--verify-only` after inspection.
`implemented` can rerun deterministic verification. `planned`, `verified` and
`reviewed` preserve role progress. Verify-only never calls a model and retains due
planning/review, pausing until explicit continuation can run them. Migration 4 adds
requested-model metadata to per-invocation role, status and result within an
execution,
migrating historical rows. Pending role/identity is durable before each call;
successful handoff and checkpoint are committed with its result. A crash after
worktree creation but before its checkpoint leaves an orphan, detected conservatively
instead of deleted. Interrupted verification can be retried only in a trusted project
with rerunnable checks; arbitrary user-defined checks may have side effects, so review
their semantics. Workspaces and artifacts are retained for manual inspection and
integration.

## Triggers and client hooks

Every trigger is a normalized `TriggerEnvelope` (origin, session, client turn id,
cwd, prompt, receive time). `core/triggers.py` is pure. In `route_trigger`, an
`ENG_ACTIVE` environment is reentrant and never routes; otherwise an `eng:` prefix
routes in every mode. Slash commands, manual-mode prose, M3 questions and
ambiguous prompts bypass. The `keywords` mode adds bounded, case-insensitive
multi agent / multi-agent / multiagent / multiple agents phrases in coding requests.
Adaptive and full modes include keyword routing and also route high-confidence
imperative change requests; full raises the risk floor to medium so review runs.
Keyword requests set the complex classification floor and a minimum of three model
calls, selecting planner, engineer, deterministic checks and reviewer. This is the
sequential role workflow; parallel plans still require their separate human approval.
Idempotency keys use the client's prompt/turn id; without one a prompt digest
deduplicates for 120 seconds only. SQLite migration 3 stores trigger records with
digests and redacted envelopes; `claim_trigger` is atomic under `BEGIN IMMEDIATE`.

`integrations/hook.py` is the client-facing entry point. Supported clients block a
prompt on exit code 2, so it parses arguments leniently, fails open (exit 0 with a
`systemMessage`) on every error, and prints one JSON object or nothing. Order per
routed prompt: installed-project binding, ignored runtime state, clean checkout and
provider checks, claim, create a CREATED task, spawn a detached `eng start`, mark
started, then block the prompt with a reason naming the task. Only a started claim
blocks a redelivery; failed or interrupted claims let the prompt through. Installers
add their per-user files to `.git/info/exclude` so they never dirty the checkout. The runner holds none of the hook's pipes (stdin null, output appended to
`runner.log`); Windows uses `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` and tries
`CREATE_BREAKAWAY_FROM_JOB`, POSIX a new session. Installers support project-bound
hooks and unbound user-wide hooks which discover the repository from client context;
user-wide hooks silently bypass unconfigured repositories. Claude Code uses
`.claude/settings.local.json` in projects or `.claude/settings.json` for the user
(exec-form `args`, no shell); Codex uses `.codex/hooks.json` (`command` plus
`commandWindows`). Gemini uses `.gemini/settings.json` grouped `BeforeAgent` hooks
with millisecond timeouts and `decision: deny` output. Cursor uses `.cursor/hooks.json`
flat `beforeSubmitPrompt` entries with `continue: false` output; its single workspace
root and conversation/generation IDs are normalized. Multi-root Cursor workspaces fail
open. Installers preserve other
entries, write atomically and keep one backup. Codex runs the hook only after the
user trusts it with `/hooks`; eng never bypasses hook trust.

`eng install` defaults to user scope and keyword routing, installs all supported hooks
and copies the bundled workflow skill into shared/Claude/Copilot skill roots. Project
scope uses local shared/Claude/GitHub roots; `--skill-dir` supports future clients.
`integrations/skills.py` replaces/removes only marked eng skill files. Unknown clients
get skill/CLI interoperability, without a claim of deterministic hook support. Client
hook support is separate from engine provider adapters: Gemini/Cursor use project
provider configuration, whereas Claude/Codex hooks select their own provider by default.

## Security policy

No shell interpolation: subprocesses receive argv arrays and bounded output. Windows
Codex npm shims resolve to Node plus the observed installed JS entry point. Claude
resolves supported native or legacy JS entries. npm verification shims resolve only
supported layouts to Node plus npm-cli.js; unsupported layouts are UNAVAILABLE. npm
executes package scripts through its own shell, so review scripts before confirmation.
Taskkill is a startup fallback; Windows Job Objects own child-process lifetime and
kill remaining descendants when their handle closes. POSIX children run in their own
process group. Checks receive a small environment allowlist, not provider credentials.
Provider auth uses the installed CLI's normal mechanism. Context rejects
escaping/symlink paths and protected files. Provider output is untrusted and strictly
parsed. Check commands are snapshotted before execution; repository instructions
cannot replace system policy. Mandatory protected paths are checked before and after
verification. Worktree HEAD must match the saved base. These are policy checks, not an
OS sandbox or access control over a malicious provider. Run untrusted tasks inside an
externally restricted system. The engine never pushes, merges, deploys, or cleans user
workspaces. Integration and merge/deployment approval policies remain deferred.
Explicit high-risk task approval is persisted separately from model output and does
not authorize integration.

## Telemetry and resource accounting

SQLite events measure context construction, provider duration, check durations, active
task elapsed time, calls and outcomes. JSONL is exported from the authoritative events
at the end of each execution. Usage is stored with each invocation; those records are
authoritative. `task.usage` is the latest provider result, not an aggregate across
roles. Cache counters preserve provider-native semantics, including Claude cache
creation; they are not normalized into comparable billing totals. Missing values
remain null and `cost_source` defaults to `unknown`. Claude CLI `total_cost_usd` is
labeled `client_estimate`, not measured spend, and its adapter keeps
`cost_reporting=False`. The model-call budget defaults to one; extra role calls
require an explicit budget or resume extension. Active wall time, provider timeout,
model-call count and context size are bounded. A known budget stop pauses and
preserves progress. No dollar cap, tool/turn cap, exact crash duration, or
startup/inference decomposition is claimed when the provider does not expose it.

## Provider evidence

Adapter invocation was checked against installed `codex-cli 0.149.0 --help` and `codex
exec --help`. Event types and usage fields follow the official [non-interactive
documentation](https://developers.openai.com/codex/noninteractive). Version drift must
be checked before adding flags. Installed Claude Code 2.1.301 was checked against
installed help for the M2 print/JSON adapter. Its safe/restricted profile exposes only
Read/Edit/Write/Glob/Grep, suppresses permission prompts, loads no MCP servers and
uses no permission bypass. Checks run outside the provider tool loop. See the official
[CLI reference](https://code.claude.com/docs/en/cli-reference) and [permissions
documentation](https://code.claude.com/docs/en/permissions). No undocumented hook
interception is used. Transport-emulator tests do not establish successful live
editing or authentication.

Project discovery proposes pytest for explicit pytest configuration and npm test for a
nonempty package script. All discovered commands remain unconfirmed until reviewed.
The M2 portability matrix uses both adapters against Python and Node disposable Git
repositories, real subprocess edits and checks, and deterministic protocol emulators.
Development may use multiple agents; the product scheduler remains sequential until
M6.

## M5 resource and capture boundaries

`core/accounting.py` is pure: persisted invocation records produce native-field
coverage, provider/model/role groups and separate reported/client/pricing estimates.
Unknown values remain null, including old invocations without model metadata.
Invocation model metadata records the requested/selected model. Optional result
`actual_model` is reserved for explicit provider evidence; current built-in adapters
leave it unknown. E0 schema 2 adds optional result telemetry in existing JSON, keeping
legacy history readable without inventing historical packet sizes. The role runtime
measures the final adapter request after read-only path rewriting; engine timing
enrichment measures context construction and role setup/execution/mutation detection.
Adapter execute entry is not proof a CLI session launched. Reports preserve native
counter coverage, cost sources and unavailable account/turn/acceptance measurements.
User-supplied pricing rules declare version, label and inclusive/exclusive input
semantics; they are not account-spend measurements. The engine checks optional
reported input/output/cost thresholds before each new role call across all executions.
Unknown coverage pauses conservatively; the first call has no prior coverage to
check. Extensions or explicit clearing are saved before continuation. In-flight usage
cannot be hard-capped, and unknown provider outcomes still require inspection and
verify-only acknowledgement. Explicit task model selection precedes role_models.

`execution/capture.py` redacts incrementally before disk persistence, including
known-secret chunk overlaps. JSON numeric counters retain numeric protocol syntax.
Provider/check artifacts stream fully to disk; excerpts are bounded at 2 MB, summaries
at 64,000 characters, and parser buffers at 8,000,000 characters per Codex record or
Claude result. Oversized protocol input fails explicitly. Capture metadata records
byte counts, excerpt truncation, process reason and completeness; sink errors fail
explicitly while process cleanup and pipe draining remain required. Redaction is
pattern/known-secret based, not a general secret scanner; no raw temporary spool is
part of the capture path. Failure evidence seeks to at most the last 20,000 bytes
of a log before decoding and selecting its final 5,000 characters, so full disk
artifacts do not cause unbounded log reads for debugger context.

`context/cache.py` stores decoded static references in memory behind bounded-byte
content hashes. Current bytes and context policy determine reuse; objectives, role
handoffs and diffs are rebuilt. Engine constructor opt-in defaults to false; no CLI
cache switch is exposed. Windows fixture measurements found hashing/reuse slower
than uncached construction. Context and role elapsed events measure orchestration,
not an inferred startup/inference split. `eng.benchmark` runs independent scripted
A/B/C fixture workflows and reports raw observations with unknown token/cost fields;
it cannot establish live-model cost or quality improvements.

## M6 plans, integration, triggers, providers and MCP

**Plans** (`core/plan.py`, pure). A `PlanSpec` is a DAG of nodes with required ownership
patterns and `concurrency` 1-3. Validation rejects unknown/duplicate/cyclic dependencies
and any pair of nodes not ordered by a dependency whose ownership cannot be proven
disjoint (a segment-wise DP over `**`/wildcard patterns that errs toward "overlap").
Scheduling functions (`ready_nodes`, `skipped_nodes`, `derive_plan_status`) are pure:
a node is ready only when every dependency is INTEGRATED; no new node starts after a
node fails, pauses or blocks unless `keep_going`.

**Ownership** is a task-level invariant, not a plan feature: `TaskSpec.owned_paths` makes
the engine fail a task, before verification, if `changed_paths` (renames split, so both
sides count) leaves ownership. Empty ownership keeps the M0-M5 behaviour.
`TaskSpec.base_commit` starts the worktree from a given commit.

**Coordinator** (`scheduling/runner.py`). One coordinator per plan holds an OS lock
(`plan-ID`). Each launched node is a normal task executed by the unchanged engine in a
worker thread that owns its `Store` connection and event loop. Concurrency is capped per
plan and, via three `slot-N.lock` files, per project across processes and plans (plan
nodes and `verify-ref` share them; ad-hoc `eng run` and hook-started tasks are
user-initiated and not counted). Only the coordinator thread writes the plan record and
the integration branch. Crash recovery: nodes left RUNNING are resumed through the
engine's existing checkpoint rules, COMPLETED-but-unintegrated nodes are integrated, and
`reconcile` resets the eng-owned integration worktree to the last recorded verified head.
E1 partial plan/node overrides resolve and persist effective budgets and repair
ceilings at creation. Role allocations cannot increase overall task allowances.
New plans default to one worker, retaining the explicit max-three capability.
Plan-wide reported limits serialize node launches using durable SQLite reservations
and recheck aggregate invocation coverage before each role side effect; unknown
outcomes block subsequent work. No token/cost reservation estimate is invented and
in-flight overshoot remains possible. Provider-free `plan preview` applies pure
classification/budget resolution and labels role projections hypothetical.
See `docs/efficiency/` for schema and recovery boundaries.
E2 (`core/reuse.py`, pure) records a digest-bound dependency handoff when a node
integrates. With plan `context_reuse`, a launch revalidates its direct dependencies'
handoffs against the launch revision and policy fingerprint, marks re-changed files
stale and logs a `context_manifest`. Human-only `plan attest` binds node scope, policy
and revision; the coordinator and engine both revalidate it, and a valid one replaces
only the initial planner call. Any failed binding falls back to the uncached path.
E3 (`core/routing.py`, pure) applies explicit operator `routing` rules: the engine
selects each role's model from the current classification (explicit model first,
`role_models` last) and skips routes a provider without `model_selection` cannot
honour; providers are routed once at task/node creation and frozen per plan node.
Every decision is an event; routing never alters workflow gates. E4 adds opt-in
`workflow.repair_headroom` (repair admission requires calls/allocations for the
debugger and any required review) and `workflow.stop_unchanged_repairs` (repairs
record a base digest; an unchanged tree pauses at `implemented`). E5
(`core/presets.py`, pure) resolves named presets beneath explicit settings, deriving
calls from required roles; plans freeze each node's `effective_workflow`.

**Integration** (`execution/integrate.py`, `scheduling/integration.py`). A completed
node's worktree is captured as a commit object through a temporary index (the worktree is
never modified), its paths are re-checked against ownership and protected patterns,
and `git merge-tree --write-tree --merge-base` computes the merge without touching any
worktree. The merged commit becomes the integration branch head, the project's required
checks run on that tree, and failure restores the previous head (`reset --hard` and
`clean` apply only to the eng-owned plan worktree). Integration is serialized and is a
second completion gate on top of each task's own gate. **Promotion** is separate and
approval-gated: all nodes INTEGRATED, last verification PASS, branch tip equals the
recorded head, clean checkout on a named branch that is an ancestor of the plan head, then
`git merge --ff-only`. No code path pushes, creates a remote or removes a worktree.
SQLite migration 5 adds `plans`, `plan_events` and `ref_checks`.

**Triggers.** `integrations/gitref.py` verifies a commit in a throwaway worktree using
the user's configuration (a commit cannot weaken its checks); `ref_outcome` yields PASS
only through `completion_gate`, FAIL only on a definitive required-check failure and
INCOMPLETE otherwise. `integrations/githook.py` is the fail-open hook entry point: it is
inert under `ENG_ACTIVE`, scrubs repository-local `GIT_*` variables Git exports to hooks
(they would otherwise redirect worktree operations in the detached verifier), and only an
explicit `--block` pre-push with a definitive FAIL exits non-zero. `gitinstall.py` writes
marker-tagged hooks and never overwrites or removes a hook it did not write.
`eng ci-trigger` builds a `CIEvent`; only failure/timeout routes, via the M4 claim/
dedup/detached-runner path keyed by CI system, workflow, run id and attempt, with the CI
output redacted and quoted as untrusted data.

**Providers.** `command_providers` in `project.yaml` register a `CommandProvider`: fixed
argv resolved by `resolve_command`, prompt on stdin, scrubbed environment plus only
declared credential-named variables, standard capture/redaction, exit/timeout/cancel
mapping, usage unknown. Doctor locates but never executes it.

**MCP.** `integrations/mcp.py` is a dependency-free stdio JSON-RPC server bound to one
project. Tools take ids only, output is redacted and bounded, and only the opt-in
`eng_submit` mutates (through `submit`). It exposes no approve/resume/cancel/integrate/
promote tool, so approval cannot be self-granted through it.

Limits: the full offline suite passes on Linux and Windows in CI (validation ran on Linux);
real CI-service delivery, live provider editing, live client hooks and
real third-party command providers are not validated; runtime parallelism shares one
SQLite database (WAL, 10-second busy timeout) and one Git object store.
