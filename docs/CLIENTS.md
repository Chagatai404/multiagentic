# Using eng from Claude Code and Codex

This guide covers installing `eng` and using it from Claude Code and Codex. The
[README](../README.md) has the short version; the design is in
[ARCHITECTURE](../ARCHITECTURE.md).

> **Status.** The hook, MCP and CLI flows are tested with emulated client input and real
> subprocesses. Firing inside a live Claude Code or Codex session, and live model editing,
> have not been validated on this project. Try a scratch repository first. See
> [release known limitations](RELEASE.md#known-limitations-read-before-relying-on-it).

## Requirements

- Python 3.12 or newer, and Git 2.40 or newer if you will use plans.
- A Git repository with at least one commit, and a clean checkout whenever eng routes a
  prompt.
- The client you use installed and logged in: `claude` (baseline Claude Code 2.1.301)
  and/or `codex` (baseline Codex CLI 0.149.0).
- Node.js and npm only if your configured checks need them.

## 1. Install eng

eng is not on a package index yet. Install the `v1.0.0` release from the repository:

```bash
python -m pip install "git+https://github.com/Chagatai404/multiagentic@v1.0.0"
eng --version
eng doctor
```

`eng doctor` reports executable versions only. It does not check authentication or model
access; confirm those in the client itself.

To use the latest `main`, replace `@v1.0.0` with `@main`.

The hooks run the Python interpreter that installed eng (`python -m
eng.integrations.hook`). Keep that environment in place. If you move or recreate it,
reinstall the hooks.

## 2. Prepare each project (once per repository)

```bash
cd your-repo
eng init -p .
```

Open `.engineering/project.yaml` and confirm a check that proves your code works:

```yaml
checks:
  - name: tests
    argv: ['{python}', '-m', 'pytest', '-q']
    timeout_seconds: 60
    required: true
    confirmed: true
```

Discovered commands start as `confirmed: false`. Without a confirmed required check,
nothing can complete. Commit the configuration:

```bash
git add .engineering
git commit -m "Add eng configuration"
```

`.engineering/state/` must stay git-ignored; `eng init` writes that rule.

## 3. Install the prompt hook for your client

Routing is opt-in and project-local. Install only for the client you use.

### Claude Code

```bash
eng hooks install claude-code -p .
```

This writes `.claude/settings.local.json`. Other hooks in that file are kept. Restart
Claude Code if it was already open.

### Codex

```bash
eng hooks install codex -p .
```

This writes `.codex/hooks.json`. Start Codex in the project, open `/hooks`, and **trust
the eng entry**. Codex ignores untrusted hooks. Restart Codex if it was already open.

### Options and check

```bash
eng hooks status claude-code -p .     # or: codex
```

`eng hooks install` also accepts:

- `--mode manual|adaptive|full` (default `manual`): see [Routing modes](#routing-modes).
- `--provider NAME`: run routed work with a provider other than the client's own, for
  example a `command_providers` entry in `project.yaml`.

The installer keeps your checkout clean by adding its own files to `.git/info/exclude`.

## 4. Use it from the client

Start a prompt with `eng:`:

```text
eng: fix add() so add(2, 3) returns 5
```

The client does not answer the prompt. It shows a short message such as
`eng started task 13683b32... for this request`. The agent then works in a separate Git
worktree in the background. Your checkout is not touched.

Follow the task from the client or a terminal:

```bash
eng status                 # all tasks
eng status TASK_ID         # state, checks, events, worktree path
eng usage TASK_ID          # reported token and cost coverage
```

When the task reaches `COMPLETED`, every required check has passed. Review the diff in
`.engineering/worktrees/TASK_ID` and apply it yourself. eng never merges or pushes.

If the task ends `PAUSED` or `BLOCKED`, `eng status TASK_ID` says why. It is usually the
model-call budget, an approval, or a failing check:

```bash
eng resume TASK_ID --extend-model-calls 2
eng resume TASK_ID --approve-high-risk     # high-risk work only
```

### Routing modes

| Mode | Routes |
|---|---|
| `manual` (default) | Only prompts that start with `eng:` |
| `adaptive` | Also clearly imperative change requests, such as "Fix the failing parser test" |
| `full` | Adaptive routing, plus an independent review of routed work |

Questions, slash commands and ambiguous prose always pass through to the client.

### Budget

Routed tasks use `budgets.model_calls` from `project.yaml`, which defaults to **1**. Medium,
high-risk or complex requests need a planner or reviewer call. Raise the budget if they
pause:

```yaml
budgets: {model_calls: 3, wall_seconds: 900}
```

### What the hook does when something is wrong

If routing cannot run (dirty checkout, unknown provider, state directory not ignored), the
hook lets the prompt through with a warning. It never traps your prompt. It also never
routes from inside an eng-launched agent.

## 5. Give the client read-only access to eng state (optional)

The MCP server exposes eng state to the agent without giving it any way to approve or
change work:

```bash
claude mcp add eng -- eng mcp serve -p /absolute/path/to/your-repo    # Claude Code
codex mcp add eng -- eng mcp serve -p /absolute/path/to/your-repo     # Codex
```

Read-only tools: `eng_tasks`, `eng_task_status`, `eng_usage`, `eng_plans`,
`eng_plan_status`, `eng_triggers`, `eng_refs`. The server has no tool to approve, resume,
cancel, integrate or promote. Approvals stay human CLI actions.

`--allow-submit` adds `eng_submit`, which starts one task and may be billable. Enable it
only when you intend that.

To remove the server:

```bash
claude mcp remove eng
codex mcp remove eng
```

## 6. Use eng without a client hook

These run the same workflow from a shell, with no hook installed:

```bash
eng run 'Fix the addition function' --accept 'Addition returns the sum' --provider claude
eng run 'Fix the addition function' --accept 'Addition returns the sum' --provider codex
eng trigger "eng: fix add()" -p .        # same normalized trigger the hook sends
eng triggers -p .                         # trigger records (digests, never raw prompts)
```

`--accept` is the acceptance statement the task is judged against. Pass `--model` to
override the provider default, and `--model-calls` to set the budget for that task.

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| Prompt answered by the client, not eng | `eng hooks status claude-code -p .` (or `codex`). Confirm the checkout is clean and `.engineering/state/` is ignored. |
| Codex ignores the eng hook | Open `/hooks` in Codex and trust the eng entry. |
| Hook fails after moving the repo or venv | Reinstall: `eng hooks uninstall ...` then `eng hooks install ...`. |
| Task stays `PAUSED` | `eng status TASK_ID` for the reason. Usually `eng resume TASK_ID --extend-model-calls N`. |
| Task is `BLOCKED` | A required check failed, errored or was unavailable. Fix the check or environment, then `eng verify TASK_ID`. |

## 8. Uninstall

```bash
eng hooks uninstall claude-code -p .     # or: codex
claude mcp remove eng                    # or: codex mcp remove eng
```

Uninstall removes only eng's own hook entries. Other hooks in those files are preserved.
Worktrees and `eng/plan/*` branches are not removed automatically. Delete them yourself
when you are done with them.

## Related

- [README](../README.md): install, quickstart, plans, safety.
- [ARCHITECTURE](../ARCHITECTURE.md): subsystem boundaries.
- [Release notes and known limitations](RELEASE.md).
