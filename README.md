# multiagentic

A provider-independent engineering orchestrator with Codex, Claude Code, configurable
command-line and deterministic fake adapters, isolated Git worktrees, deterministic
verification, durable SQLite state, cancellation, bounded adaptive planning/review/
repair, conservative recovery, and (M6) dependency-scheduled parallel plans with
verified integration, Git/CI triggers and an optional MCP server.

Nothing is pushed, merged into your branch, deployed or cleaned up without an explicit
command; completion always rests on real check evidence, never on model confidence.

Requires Python 3.12+, Git (2.40+ for plans), and a trusted local repository with an initial commit.
Provider CLIs are optional for the offline demo. Adapter command baselines are Codex
0.149.0 and Claude Code 2.1.301. JavaScript checks require Node.js and npm.

## Quickstart: install once for your user

Install the current source with [uv](https://docs.astral.sh/uv/getting-started/installation/)
so `eng` is available in every terminal, in a persistent tool environment:

```sh
uv tool install "git+https://github.com/Chagatai404/multiagentic-engineering@main"
eng install
```

If `eng` is not on PATH, run `uv tool update-shell` and reopen your terminal.
Alternatively use `pipx install` with the same Git URL. For local development, run
`python -m pip install -e '.[dev]'` in a virtual environment and then `eng install`.
The hooks keep the installing interpreter's absolute path; keep that environment
in place and rerun `eng install` after moving, upgrading or recreating it.
**The tagged `v1.0.0` predates this installer; the commands here require the updated source.**

`eng install` defaults to **user-wide**, without needing a repository or administrator
access. It installs prompt hooks for all four supported clients, including clients you
install later, and a portable `multiagentic-engineering` skill:

| Client | User-wide hook | Skill discovery |
|---|---|---|
| Claude Code | `~/.claude/settings.json` | `~/.claude/skills/` |
| Codex | `~/.codex/hooks.json` | `~/.agents/skills/` |
| Gemini CLI | `~/.gemini/settings.json` (`BeforeAgent`) | `~/.agents/skills/` |
| Cursor | `~/.cursor/hooks.json` (`beforeSubmitPrompt`) | `~/.agents/skills/` |
| GitHub Copilot CLI | Skill integration | `~/.copilot/skills/` and shared skills |

Each skill directory contains `multiagentic-engineering/SKILL.md`. `CODEX_HOME` and
`CLAUDE_CONFIG_DIR` overrides are respected for their clients' settings. Other settings
and hooks are preserved; existing settings get one `.eng-backup` copy. This is per OS
user on this machine: remote hosts and other OS accounts need their own installation.

Restart clients after installation. **In Codex, open `/hooks` and trust the eng entry.**
New or changed definitions need review again; installation never grants hook trust.
Gemini and Cursor keep their normal workspace and hook trust controls. Copilot chooses
the skill from its description; `/multiagentic-engineering` explicitly selects it.
Skill selection is model-driven; the four native hooks provide deterministic routing.

### Prepare each repository once

```sh
cd your-repo
eng init
```

Review `.engineering/project.yaml` and confirm meaningful required checks. Discovered
commands start as `confirmed: false`; without a confirmed required check nothing can
complete. For example, a Python project that uses pytest can set:

```yaml
checks:
  - name: tests
    argv: ['{python}', '-m', 'pytest', '-q']
    required: true
    confirmed: true
```

Commit the configuration and `.engineering/.gitignore`. The checkout must be clean
when routing; worktrees start from committed HEAD. User-wide hooks quietly pass through
repositories that have no eng configuration. They never initialize projects or confirm
checks on your behalf.

Install and log in to the provider CLI (`codex` or `claude`). `eng doctor` checks installed
versions, without testing authentication or making a model call. Claude Code hooks select
`claude`, Codex hooks select `codex`; Gemini, Cursor and the portable skill use the
project's `provider` (default `codex`). Client hook support does not add a Gemini or Cursor
model-provider adapter. Custom providers are configured in `command_providers`.

### Trigger the workflow naturally

```text
Use multi agent to fix the parser and its tests.
Fix the retry logic with multiple agents.
Implement the cache using a multi-agent workflow.
```

The default `keywords` mode recognizes **multi agent**, **multi-agent**, **multiagent**
and **multiple agents**, including plural forms, anywhere in a coding request,
case-insensitively. No `eng:` prefix is needed. Questions such as "What is a multi-agent
system?", slash commands and ordinary prompts pass through. `eng: fix the parser` remains
an explicit trigger in every mode.

A keyword request runs **planner → engineer → required deterministic checks → independent
reviewer**, with a minimum budget of three model calls. These roles run sequentially;
parallel independent tasks use the separately approved [plan workflow](#parallel-plans-m6).
Model calls may be billable. High-risk task approval remains a human CLI action.

The hook starts one background task in an isolated Git worktree and blocks the original
prompt so the interactive agent does not duplicate it. Follow the task with:

```sh
eng status
eng status TASK_ID
eng usage TASK_ID
```

Review the resulting worktree diff before applying it. If work is paused or blocked,
`eng status TASK_ID` explains why. eng never automatically pushes or deploys changes.
Hook failures pass your prompt through; eng-launched agents cannot recursively trigger it.

### Project-wide installation and advanced options

To install only for one repository, instead of using user-wide setup:

```sh
eng install --scope project -p /path/to/your-repo
```

This installs the same hooks under that repository's `.claude/`, `.codex/`, `.gemini/`
and `.cursor/` directories, plus project skills under `.agents/skills/`, `.claude/skills/`
and `.github/skills/`. Generated files are excluded locally through `.git/info/exclude`.
The hooks are bound to that repository; other repositories and worktrees bypass them.
Choose one scope unless you intentionally need both; settings from both scopes can run,
with duplicate delivery handled by eng's trigger claim.

```sh
eng install --client codex                            # one native hook, portable skills
eng install --mode adaptive                           # also clear imperative coding requests
eng hooks status codex --scope user
eng hooks install claude-code --scope user --mode keywords --provider codex
eng hooks install codex -p . --mode keywords           # project hook only (legacy command)
```

`manual` routes only `eng:`; `keywords` adds the multi-agent phrases; `adaptive` also routes
clear imperative requests; `full` adds a review floor to adaptive routing. Keyword requests
always select planning and review in every mode that accepts them.

Future clients that discover `~/.agents/skills/` can use the workflow without another
installation. For a client with its own skills directory, run:

```sh
eng install --skill-dir /path/to/new-agent/skills
```

This copies the portable skill there; it does not invent a prompt hook for an unknown
client. A client without skill support can call `eng trigger "Use multiple agents to fix
the parser" --mode keywords -p .` or integrate the documented CLI. See
[docs/CLIENTS.md](docs/CLIENTS.md) for client protocols and troubleshooting.

To remove only eng's managed entries and skills (other settings and resources stay):

```sh
eng uninstall                                        # user-wide
eng uninstall --scope project -p /path/to/your-repo    # project-wide
# Repeat --skill-dir when removing copies installed for another client.
```

Hooks are tested with emulated client input and real subprocesses on Windows. Installation
is separate from live client execution; successful paid provider edits and live hook delivery
are not established by those tests. Try a scratch repository before relying on automation.

## Use in a project

```sh
eng init --project /path/to/repository
```

Review `.engineering/project.yaml`. Detection proposes commands with `confirmed:
false`. Python detection proposes pytest only for explicit pytest configuration;
JavaScript detection proposes `npm test` only for a nonempty `scripts.test` in
package.json. Every discovered check requires review and confirmation. No dependencies
are installed. Use argument arrays, never shell command strings. `{python}` resolves
to the interpreter running eng, which is useful when a worktree shares an external
virtual environment.

```yaml
schema_version: 1
name: example
checks:
  - name: tests
    argv: ['{python}', '-m', 'pytest', '-q']
    timeout_seconds: 60
    required: true
    confirmed: true
```

Commit the configuration and `.engineering/.gitignore` before starting a task. The
source repository must be clean; worktrees start from committed HEAD. Dependencies
must already be available to the check command; no installation occurs automatically.
Both the provider and verification commands execute trusted code on your machine.

```sh
eng providers
eng doctor
eng run 'Fix the addition function' --accept 'Addition returns the sum' --provider codex
eng run 'Fix the addition function' --accept 'Addition returns the sum' --provider claude
eng status TASK_ID
eng cancel TASK_ID
eng resume TASK_ID
eng resume TASK_ID --verify-only --extend-seconds 120
eng verify TASK_ID
```

Specify `--model` to override the provider default; no model name or pricing is
hardcoded. `--wall-seconds`, `--provider-seconds`, and `--context` bound execution and
select extra tracked files. `--user-config` adds an explicit user defaults YAML.
Precedence is engine defaults, user defaults, project settings, then task options.
`--provider` overrides the configured provider; resume retains the saved task
provider. `eng providers` lists capabilities without invoking models. `eng doctor`
checks CLI versions only and reports authentication as `not_checked`; it does not
prove model access. Mandatory protected paths remain enforced across all levels.

The command prints task JSON, including its ID, workspace, checks, usage, and state.
Exit codes: 0 completed/successful inspection; 1 task incomplete; 2 invalid
input/setup. COMPLETED requires all configured required checks to pass, plus any
required planning, independent review and explicit high-risk task approval. It does
not prove every natural language acceptance criterion or replace human acceptance of
the change.

## Offline end-to-end demo

```sh
python benchmarks/offline.py
```

This creates a disposable repository, seeds a real failing check, repairs it through
FakeProvider, reruns the check in a worktree, and reports measured elapsed time. Fake
edits are explicit fixture operations, not simulated language understanding:

```sh
eng run 'Repair fixture' --accept 'answer.txt contains 42' --provider fake --fake-change answer.txt=42
```

## Adaptive workflow

Classification uses bounded deterministic description/path cues on three independent
axes: task type (`change` or `question`), complexity (`small`, `medium`, `complex`),
and risk (`low`, `medium`, `high`). Reasons are persisted. Complexity and risk options
set minimums; they cannot lower inferred safeguards. Acceptance text does not
determine classification. Observed changed paths can raise safeguards.

Questions return an actionable message directing the user to an assistant
conversation; eng creates no engineering workspace and makes no model call for them.
They are not reported as verified engineering work. Small low-risk changes use one
engineer call followed by real checks. Complex changes require a planner and
independent reviewer; medium/high risk requires review, and high risk requires
explicit human approval. Model confidence never substitutes for check evidence.

```sh
eng run 'Fix addition' --accept 'Addition returns the sum' --provider codex --model-calls 1
eng run 'Refactor complex parser architecture' --accept 'Existing parser checks pass' --provider codex --model-calls 3
eng run 'Update authentication checks' --accept 'Authentication checks pass' --provider codex --approve-high-risk --model-calls 2
eng resume TASK_ID --extend-model-calls 2 --extend-seconds 120
eng resume TASK_ID --approve-high-risk
```

`--task-type`, `--complexity` and `--risk` set classification overrides.
`--max-repairs` sets the repair limit (default 2, configurable from 0 to 10). The
default `--model-calls` budget is 1: planning, review and debugger calls all consume
it. The examples allocate the minimum successful path; repairs may need additional
calls and time. `--approve-high-risk` approves the saved engineering task only; it
grants no permission to merge, push or deploy.

Repairs target actual required-check FAIL evidence or explicit reviewer findings.
Missing, unconfirmed, unavailable, skipped or errored required checks block instead.
Each attempt is persisted before the debugger runs; identical failures stop further
automatic repair. Checks and any required review run again after an edit. Planner and
reviewer use bounded role-specific context and retained standalone Git snapshots.
Mutation checks detect unexpected changes to the snapshot or task workspace; these are
not OS sandboxes. The verifier is deterministic and makes no model call.

## Resource visibility

See [accounting semantics](docs/efficiency/ACCOUNTING_AND_LIMITS.md),
[budget examples](docs/efficiency/BUDGET_SCHEMA_AND_PRESETS.md),
[benchmark/calibration protocol](docs/efficiency/BENCHMARKS.md) and
[large-project runbook](docs/efficiency/LARGE_PROJECT_RUNBOOK.md). E0/E1 cover telemetry
and configured budgets; E2 adds [dependency handoffs and human plan
attestations](docs/efficiency/CONTEXT_AND_PLAN_REUSE.md) (`context_reuse: true`,
`eng plan attest PLAN_ID NODE`). E3 adds explicit
[classification routing](docs/efficiency/ROUTING.md). Preset flags remain future
work. Offline fixtures do not demonstrate real-model cost or quality improvements.

```sh
eng usage TASK_ID
eng run 'Fix addition' --accept 'Addition returns the sum' --reported-input-tokens 10000 --reported-output-tokens 2000
eng resume TASK_ID --extend-input-tokens 10000 --extend-output-tokens 2000
eng resume TASK_ID --clear-reported-limits
eng benchmark --repetitions 3 --seed 20261026
eng benchmark --efficiency --repetitions 1 --seed 0
```

`eng usage` aggregates all saved invocations across continuations by provider,
requested/selected model and role. Schema 2 adds measured packet character/UTF-8
sizes, timing coverage, task/role outcomes, saved check history, missing telemetry and
configured budget status. Human acceptance, measured account spend and subscription
allowance remain unknown. The selected model is the request metadata; when
the provider chooses its default, the actual model remains unknown. Built-in adapters
currently leave actual-model identity unknown even with explicit selection. Each
native counter has a known subtotal, reported count and missing
count; all-missing subtotals stay null. Cache/reasoning counters are not added to
input/output. Reported cost, client estimates and optional pricing estimates have
separate provenance. Nothing here measures account spend.

`--reported-input-tokens`, `--reported-output-tokens` and `--reported-cost-usd` stop
**new** calls after cumulative reported usage reaches the threshold. They cannot cap
an in-flight call. With no prior invocations the first call may run. Missing coverage
pauses further model work conservatively. Inspect evidence before extending an
existing limit; extensions do not resolve unknown coverage. Explicit
`--clear-reported-limits` removes those limits, including an unknown-coverage stop,
and cannot be combined with their extensions. Other completion, approval and recovery
gates still apply; estimates never satisfy a reported-cost threshold.

Project `role_models` maps `planner`, `engineer`, `debugger` and `reviewer` to model
names; an explicit task `--model` wins for every role. Optional project `pricing`
entries require provider, model, a user-defined `version` and `label`,
`input_semantics: inclusive|exclusive`, and input/output USD-per-million rates.
Optional `cached_input_per_million` and `cache_creation_per_million` preserve the
chosen native-counter semantics. These are manually supplied estimates, with no
built-in prices or claim that a version is a current market price. Incomplete or
incompatible counters leave the estimate unknown.

The benchmark uses scripted edits and external evaluators in disposable repositories;
it measures fixture behavior, not model intelligence or live-model savings. See
[benchmark design](benchmarks/README.md) and [validation](docs/VALIDATION.md).
An in-memory content-hash context cache is available through
`Engine(..., context_cache_enabled=True)` only, and defaults off. It rechecks bounded
source bytes; it never caches objectives, handoffs or diffs. The measured Windows
fixture was slower with caching, so no speed benefit is claimed.

## Parallel plans (M6)

A plan splits work into nodes with dependencies and **ownership** (the paths a node may
change). Each node is an ordinary task in its own worktree; at most **three** run at
once (also enforced across processes). Verified results are merged serially into an
eng-owned branch `eng/plan/PLAN_ID`; your branch moves only on explicit approval.

```sh
eng plan validate docs/plan.example.yaml          # no side effects
eng plan create docs/plan.example.yaml -p .       # branch + integration worktree, no model runs
eng plan run PLAN_ID -p .                         # schedule, run, integrate until idle
eng plan status PLAN_ID -p .                      # nodes, events, integration head
eng plan usage PLAN_ID -p .                       # native usage coverage across all nodes
eng plan approve PLAN_ID NODE -p .                # explicit high-risk approval for one node
eng plan attest PLAN_ID NODE -p .                 # human: node spec is its plan (no planner call)
eng plan resume PLAN_ID -p .                      # relaunch paused nodes, retry blocked integration
eng plan cancel PLAN_ID -p .
eng plan promote PLAN_ID -p .                     # dry run: reports every precondition
eng plan promote PLAN_ID -p . --approve           # fast-forward the checked-out branch
```

See [docs/plan.example.yaml](docs/plan.example.yaml) and [the M6 design](docs/M6_PLAN.md).

- **Validation.** Unique ids, known acyclic dependencies, at most 50 nodes, safe
  relative patterns (`**` spans directories, a trailing `/` means everything below;
  matching is case-insensitive, so `Src/A.py` and `src/a.py` count as the same). Any
  two nodes not ordered by a dependency must have *provably disjoint* ownership; when
  disjointness cannot be shown the plan is rejected.
- **Ownership is enforced**, not advisory: a node whose task changes any path outside its
  `owns` (including the old side of a rename) FAILS before verification. Nodes see the
  integrated work of their dependencies because they start from the integration head.
- **Integration is a second gate.** A COMPLETED node is snapshotted without touching its
  worktree, re-checked for ownership/protected paths, merged with `git merge-tree`
  (conflicts never touch a worktree), and the project's required checks must pass on the
  integrated tree. Any failure rolls the branch back and BLOCKS the node.
- **Failure policy.** No new nodes start after a node fails, pauses or blocks unless
  `--keep-going`; dependents of failed/cancelled nodes are SKIPPED. Unknown provider
  outcomes still need `eng resume NODE_TASK --verify-only` (see `eng plan status`).
- **Budgets.** `node_budgets` provides partial plan defaults; each node's `budgets`
  overrides individual fields. Optional `role_limits` remain subordinate to task limits.
  Effective allocations are saved at creation. New plans default to concurrency 1;
  explicit concurrency 2–3 remains supported. `limits` are plan-wide reported-usage
  stops checked before node launches and role calls (unknown coverage stops conservatively;
  `eng plan resume --clear-limits` is the explicit override). `--approve-high-risk`
  approves every node task for that run; prefer per-node `eng plan approve`.
  Plans with reported limits serialize launches because no defensible usage reservation
  estimate is available. In-flight calls may exceed thresholds. Preview without models
  or runtime state: `eng plan preview plan.yaml -p . --user-config user.yaml`;
  use the same optional user file with `eng plan create`.
- **Promotion** requires every node integrated, the last verification passing, an
  unmoved plan branch, a clean checkout on a named branch, and a pure fast-forward.
  eng never pushes, and there is no automatic cleanup: remove
  `.engineering/worktrees/plan-*` and `eng/plan/*` branches yourself when done.
- `plan create` refuses a project with no confirmed required check (no node could ever
  pass the completion gate), and the integration worktree runs your checks, so it
  inherits the trust you give them. Symlinks a node adds are preserved as symlinks.
- Git 2.40 or newer is required (`merge-tree --write-tree`). Running tasks use one
  clean source checkout: keep it clean while a plan runs (later nodes fail to start from
  a dirty checkout rather than guessing).

## Git and CI triggers (M6)

```sh
eng verify-ref HEAD -p .                  # checks in a throwaway worktree; exit 0 only on PASS
eng refs -p .                             # recorded verifications
eng hooks git install -p .                # post-commit + pre-push: detached, never blocking
eng hooks git install -p . --event pre-push --block   # waits; blocks only a definitive FAIL
eng hooks git status -p .
eng hooks git uninstall -p .              # removes only hooks eng wrote
eng ci-trigger -p . --workflow tests --run-id 4242 --conclusion failure --summary-file ci.log
eng ci-trigger -p . --from-github-env --conclusion failure --summary-file ci.log
```

Verification uses *your checkout's* configuration, never the commit under test, so a
commit cannot weaken its own checks. PASS needs every required check to pass;
unconfirmed, unavailable or errored checks are INCOMPLETE and never block a push. Git
hooks fail open, refuse to overwrite a hook eng did not write, and do nothing inside
eng-launched processes. `ci-trigger` turns a failing run into one repair task
(idempotent per CI system, workflow, run id and attempt); success, cancelled and skipped
runs do nothing. The CI summary is stored redacted and quoted to the model as untrusted
data. Routed work follows the same clean-checkout, claim and detached-runner path as
prompt hooks; pushes and merges stay manual. Real delivery from a CI service has not
been exercised; the flows are tested with emulated events and real Git hooks.

## More providers: configured commands (M6)

Attach any coding CLI declaratively in `.engineering/project.yaml`. eng bakes in no
vendor flags: you supply the argv, the prompt arrives on stdin, and the process runs in
the task worktree with a scrubbed environment.

```yaml
provider: mycli
command_providers:
  mycli:
    argv: ['mycli', 'agent', '--stdin', '--non-interactive']   # trusted, like a check
    model_flag: '--model'          # optional; without it --model/role_models are refused
    env_allow: [MYCLI_API_KEY]     # credential-like names only, so values are redacted
```

Exit code, timeout and cancellation map onto the common result; token usage and cost
stay unknown (so usage limits pause conservatively). Planner and reviewer roles must
print the strict JSON handoff as their entire stdout, so the simplest use is an
engineering provider with the default one-call workflow. `eng providers -p .` and
`eng doctor -p .` list it (doctor only locates the executable and never runs it).
Names cannot shadow `fake`, `codex` or `claude`. Not validated against any live CLI.

## MCP server (optional)

```sh
eng mcp serve -p .                  # stdio; read-only tools for this one project
eng mcp serve -p . --allow-submit   # adds eng_submit (starts ONE task; may be billable)
claude mcp add eng -- eng mcp serve -p /path/to/repository
```

Tools take ids, never paths: `eng_tasks`, `eng_task_status`, `eng_usage`, `eng_plans`,
`eng_plan_status`, `eng_triggers`, `eng_refs`, plus opt-in `eng_submit` (idempotent by
`request_id`). There is deliberately no tool to approve, resume, cancel, integrate or
promote: approvals stay human CLI actions, so a model using this server can never grant
itself approval. Output is redacted and bounded. The server needs no extra dependency and
was checked against the official MCP Python SDK client.

## Prompt hooks (opt-in)

Use `eng install` for user-wide keyword hooks and portable skills, or
`eng install --scope project -p .` for one repository. Claude Code, Codex, Gemini and
Cursor have native prompt hooks; Copilot and future compatible clients use the skill.
See the [quickstart](#quickstart-install-once-for-your-user) and
[client guide](docs/CLIENTS.md) for both scopes, routing modes, client trust and removal.

Routed prompts run in a detached `eng start TASK_ID` process and reuse trigger claims
on redelivery. `eng status TASK_ID` follows progress; `eng triggers` lists records with
prompt digests. Non-keyword tasks retain the project's model-call budget (default 1);
keyword requests have room for planner, engineer and reviewer. All tasks retain the
normal check, recovery and human approval gates.

## State, evidence, and recovery

SQLite is authoritative under `.engineering/state/eng.sqlite3`. Versioned migrations
store tasks, executions, transitions, checkpoints, invocations (including reported
usage), verification records, and artifact references. Migration 4 adds requested
model metadata to invocation identity, execution, role, status and result, preserving
older rows.
Logs and redacted diff evidence live under
`.engineering/artifacts/TASK_ID/EXECUTION_ID/`. Workspaces remain under
`.engineering/worktrees/TASK_ID/`. Inspect new files in the preserved workspace; the
diff artifact contains tracked changes only. Nothing is automatically committed,
merged, pushed, deployed, or removed.

Resume never replays an invocation whose outcome is unknown. Inspect the saved
workspace, then use `--verify-only` to acknowledge the outcome and continue with
checks. This makes no model calls and cannot satisfy due planning or review; use a
later explicit resume with sufficient budget to perform those roles. Verification uses
the saved configuration, so an agent cannot replace the configured checks by editing
project.yaml. BLOCKED checks can be rerun after manual repairs. Terminal tasks require
a new task. Cancellation is durable across CLI processes; an active runner polls it
and kills the subprocess tree. Ctrl+C pauses the run.

The wall-clock budget counts active execution time across continuations, not time
spent waiting for a person. Interrupted executions with no final timing record have
unknown time; they require outcome inspection and are not presented as exact timing.

## Safety and scope

Git worktrees isolate changes; they are **not security sandboxes**. Use only trusted
repositories and approved check commands, or provide an external OS/container sandbox.
Codex is launched in workspace-write mode with tool network access disabled and
approval requests denied. The provider still needs its normal service connection and
saved authentication. Claude uses safe/restricted print/JSON mode with only Read,
Edit, Write, Glob and Grep tools, no Bash, strict empty MCP configuration and no
permission bypass. Verification commands run separately under eng. Provider controls
are a boundary supplied by the installed CLI, not an OS security guarantee from eng.
Secrets are filtered from check environments, and known environment secrets and common
credential patterns are redacted in logs; this is not a general secret scanner. Check
programs can still read files allowed by the operating system. Protected-path
violations are detected after execution, not prevented for arbitrary processes. No
financial cap is promised: bound calls and time and use account limits. On Windows,
supported npm launchers resolve to Node plus `npm-cli.js`; unknown layouts are
unavailable. npm itself executes project scripts through its shell, so review the test
script and its lifecycle hooks before confirmation.

`task.usage` reflects the latest provider result, not a sum across roles. Persisted
per-invocation records are authoritative for individual calls. Usage counters retain
provider-native cache semantics; do not sum them across providers. Claude
`total_cost_usd` is stored as a client estimate, not measured account spend. Missing
usage stays unknown; Claude therefore advertises `cost_reporting: false`.

Provider and check stdout/stderr stream to redacted disk artifacts. In-memory diagnostic
excerpts remain capped at 2 MB per stream; provider summaries at 64,000 characters.
Codex JSONL records and the Claude JSON result have an 8,000,000-character parsing
limit; exceeding it fails explicitly while disk capture continues. Malformed or
incomplete output fails closed. Capture metadata records bytes, truncation, process
reason and completeness; sink failures are explicit errors. No raw temporary spool
is written. Redaction covers known environment secrets and credential patterns,
including chunk boundaries, but is not a general secret scanner. Provider fallback,
Native API adapters and provider tool/turn limits remain unsupported (use a configured
command provider for other CLIs). See [ROADMAP](ROADMAP.md),
[ARCHITECTURE](ARCHITECTURE.md), [requirements](docs/REQUIREMENTS.md) and the
[release notes and known limitations](docs/RELEASE.md).

## Development

M3 development split workflow/roles (medium reasoning), stateful engine recovery
(high), documentation/checks (low), and independent review (medium) between agents;
Codex implemented the slices and Claude Code completed review fixes and verification.
M6 adds runtime parallel scheduling (plans); it is separate from how eng itself was built.

The repository config allows 600 seconds for its full test check and 900 seconds
of active task time: the measured Windows suite took 400.49 seconds. These are
project settings; global defaults are unchanged.

Prefer installing the package into the environment used for development. If an
isolated worktree uses an external virtual environment and source imports, set
`PYTHONPATH` to that worktree's **absolute** `src` path; a relative path can resolve
against detached child working directories and import another checkout.

The full portability suite requires Node.js 24 and npm. Python-only engine use does
not require Node.js unless its configured checks or provider launcher need it.

```sh
python -m pytest
ruff check .
mypy
python -m build
```

Live provider tests are opt-in with `ENG_LIVE_CODEX=1`; they use one bounded
invocation in a disposable repository and report provider usage when available. They
may consume account quota. Offline tests do not make model calls.

The initial live check authenticated and returned measured usage, but this host's
nested Codex workspace denied file access. Verification failed and the task correctly
remained BLOCKED. Successful live Codex or Claude editing has not been confirmed on
this host. M2 portability tests use real adapter transports with deterministic CLI
emulators and real Python/Node checks; they make no model calls. See [validation
evidence](docs/VALIDATION.md) for the result and limitations.
