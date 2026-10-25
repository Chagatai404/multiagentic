# Architecture (M0 through M3)

Dependency direction: CLI → engine shell → subsystem contracts and adapters. The
functional core is `core/models.py`, `core/policy.py` and `core/workflow.py`: Pydantic
contracts, legal transitions, and evidence-based completion. `core/engine.py` is
explicitly the imperative orchestration shell; it injects a Provider and Store.
Models/policy import no provider, subprocess, filesystem execution, or storage code.

| Layer | Implementation | Boundary |
|---|---|---|
| Interface | `cli.py` | Normalize requests, output JSON, meaningful exit codes |
| Orchestration | `core/engine.py` | Sequential workflow and checkpoint recovery |
| Agents/providers | `agents/`, `providers/`, Role enum | Capabilities, request/result, provider-specific transport |
| Project/context | `projects/`, `context/` | YAML snapshot, tracked selective context, character budget |
| Execution/verification | `execution/`, `verification/` | Worktrees, process lifecycle, real check evidence |
| Persistence/telemetry | `storage/` | SQLite transactions, migrations, events, artifact references |

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
planning/review, pausing until explicit continuation can run them. Invocation schema
v2 records each unique invocation, role, status and result within an execution,
migrating historical rows. Pending role/identity is durable before each call;
successful handoff and checkpoint are committed with its result. A crash after
worktree creation but before its checkpoint leaves an orphan, detected conservatively
instead of deleted. Interrupted verification can be retried only in a trusted project
with rerunnable checks; arbitrary user-defined checks may have side effects, so review
their semantics. Workspaces and artifacts are retained for manual inspection and
integration.

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
