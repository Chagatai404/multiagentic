# multiagentic

A provider-independent engineering orchestrator. Version 0.1 implements M0 and M1:
one coding provider, isolated Git worktrees, deterministic verification, durable SQLite
state, cancellation, and conservative recovery.

Requires Python 3.12+, Git, and a trusted local repository with an initial commit.
Codex CLI is optional for the offline demo. The tested CLI baseline is Codex 0.149.0.

```sh
python -m venv .venv
# Activate the environment using your platform's usual command.
python -m pip install -e '.[dev]'
eng --help
eng doctor
eng providers
```

On Windows, use `.venv\Scripts\python.exe` and `.venv\Scripts\eng.exe` directly
if you prefer not to activate the environment. If the venv has no pip, use `uv pip install`.
With uv installed, `uv sync --extra dev --locked` uses the committed dependency lock.

## Use in a project

```sh
eng init --project /path/to/repository
```

Review `.engineering/project.yaml`. Detection proposes commands with `confirmed: false`.
Use argument arrays, never shell command strings. `{python}` resolves to the interpreter
running eng, which is useful when a worktree shares an external virtual environment.

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
eng run 'Fix the addition function' --accept 'Addition returns the sum' --provider codex
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
Mandatory protected paths remain enforced across all levels.

The command prints task JSON, including its ID, workspace, checks, usage, and state.
Exit codes: 0 completed/successful inspection; 1 task incomplete; 2 invalid input/setup.
COMPLETED means all configured required checks passed. It does not prove every natural
language acceptance criterion or replace human acceptance of the change.

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

## State, evidence, and recovery

SQLite is authoritative under `.engineering/state/eng.sqlite3`. Versioned migrations
store tasks, executions, transitions, checkpoints, invocations (including reported
usage), verification records, and artifact references. Logs and redacted diff evidence
live under `.engineering/artifacts/TASK_ID/EXECUTION_ID/`. Workspaces remain under
`.engineering/worktrees/TASK_ID/`. Inspect new files in the preserved workspace; the
diff artifact contains tracked changes only. Nothing is automatically committed,
merged, pushed, deployed, or removed.

Resume never replays an invocation whose outcome is unknown. Inspect the saved
workspace, then use `--verify-only` to acknowledge the outcome and continue with checks.
Verification uses the saved configuration, so an agent cannot replace the configured
checks by editing project.yaml. BLOCKED checks can be rerun after manual repairs.
Terminal tasks require a new task. Cancellation is durable across CLI processes; an
active runner polls it and kills the subprocess tree. Ctrl+C pauses the run.

The wall-clock budget counts active execution time across continuations, not time
spent waiting for a person. Interrupted executions with no final timing record have
unknown time; they require outcome inspection and are not presented as exact timing.

## Safety and scope

Git worktrees isolate changes; they are **not security sandboxes**. Use only trusted
repositories and approved check commands, or provide an external OS/container sandbox.
Codex is launched in workspace-write mode with tool network access disabled and
approval requests denied. The provider still needs its normal service connection and
saved authentication. Provider controls are a boundary supplied by the installed CLI,
not an OS security guarantee from eng. Secrets are filtered from check environments,
and known environment secrets and common credential patterns are redacted in logs;
this is not a general secret scanner. Check programs can still read files allowed by
the operating system. Protected-path violations are detected after execution, not
prevented for arbitrary processes. No financial cap is promised for Codex: this CLI
does not expose a hard dollar limit; bound calls and time and use account limits.

Each captured stdout/stderr stream is capped at 2 MB in M1; pipes continue draining.
Malformed or incomplete provider output fails closed. Native streaming, full log
spooling, fine-grained tool/turn/cost caps, automatic debug/review, provider fallback,
Claude/Gemini/API adapters, adaptive hooks, parallel agents, integration, and benchmark
comparisons are deferred. See [ROADMAP](ROADMAP.md), [ARCHITECTURE](ARCHITECTURE.md),
and [requirements](docs/REQUIREMENTS.md).

## Development

```sh
python -m pytest
ruff check .
mypy
python -m build
```

Live provider tests are opt-in with `ENG_LIVE_CODEX=1`; they use one bounded invocation
in a disposable repository and report provider usage when available. They may consume
account quota. Offline tests do not make model calls.

The initial live check authenticated and returned measured usage, but this host's
nested Codex workspace denied file access. Verification failed and the task correctly
remained BLOCKED. Live editing has therefore not been confirmed on this host. See
[validation evidence](docs/VALIDATION.md) for the result and limitations.
