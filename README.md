# multiagentic

A provider-independent engineering orchestrator with Codex, Claude Code and
deterministic fake adapters, isolated Git worktrees, deterministic verification,
durable SQLite state, cancellation, bounded adaptive planning/review/repair, and
conservative recovery. The runtime workflow remains sequential.

Requires Python 3.12+, Git, and a trusted local repository with an initial commit.
Provider CLIs are optional for the offline demo. Adapter command baselines are Codex
0.149.0 and Claude Code 2.1.301. JavaScript checks require Node.js and npm.

```sh
python -m venv .venv
# Activate the environment using your platform's usual command.
python -m pip install -e '.[dev]'
eng --help
eng doctor
eng providers
```

On Windows, use `.venv\Scripts\python.exe` and `.venv\Scripts\eng.exe` directly if you
prefer not to activate the environment. If the venv has no pip, use `uv pip install`.
With uv installed, `uv sync --extra dev --locked` uses the committed dependency lock.

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

## Prompt hooks (opt-in)

Claude Code and Codex can route engineering prompts to eng through their
`UserPromptSubmit` hooks. Installation is explicit and project-local:

```powershell
eng hooks install claude-code -p .            # writes .claude/settings.local.json
eng hooks install codex -p . --mode adaptive  # writes .codex/hooks.json; trust it via /hooks
eng hooks status claude-code -p .
eng hooks uninstall claude-code -p .
```

- `manual` (default): only prompts starting with `eng:` route, for example
  `eng: fix the failing parser test`.
- `adaptive`: also routes clearly imperative change requests ("Fix the failing
  parser test"). Questions, slash commands and ambiguous prose always pass through.
- `full`: adaptive routing plus independent review of routed work.

A routed prompt is blocked in the client, with a message naming the task, so only
eng performs the work. The task runs in a detached `eng start TASK_ID` process; use
`eng status TASK_ID` to follow it. Redelivered prompts reuse the existing task.
Hooks fired inside eng's own provider processes never route. Routing requires a
clean checkout, and any hook failure lets the prompt through with a warning.
`eng trigger "eng: ..." -p .` submits the same normalized trigger from a shell, and
`eng triggers` lists records (prompt digests, never raw prompts). Routed tasks use the
project's `budgets.model_calls` (default 1): a complex request that needs a planner, or
any review, pauses after that call. Raise the budget in `.engineering/project.yaml` or
continue with `eng resume TASK_ID --extend-model-calls N`. Hook behavior is
tested with emulated client input; firing inside live Claude Code or Codex sessions
has not been validated.

## State, evidence, and recovery

SQLite is authoritative under `.engineering/state/eng.sqlite3`. Versioned migrations
store tasks, executions, transitions, checkpoints, invocations (including reported
usage), verification records, and artifact references. Invocation schema v2 stores
each invocation identity, execution, role, status and result, preserving older rows.
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

Each captured stdout/stderr stream is capped at 2 MB; pipes continue draining.
Malformed or incomplete provider output fails closed. Native streaming, full log
spooling, fine-grained tool/turn/cost caps, provider fallback, Gemini/API adapters,
adaptive hooks, parallel scheduling, integration, and benchmark comparisons are
deferred. See [ROADMAP](ROADMAP.md), [ARCHITECTURE](ARCHITECTURE.md), and
[requirements](docs/REQUIREMENTS.md).

## Development

M3 development split workflow/roles (medium reasoning), stateful engine recovery
(high), documentation/checks (low), and independent review (medium) between agents;
Codex implemented the slices and Claude Code completed review fixes and verification.
This development process does not implement parallel runtime scheduling.

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
