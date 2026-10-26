---
name: multiagentic-engineering
description: Run the eng engineering workflow when the user requests a coding change with multi agent, multi-agent, multiagent, or multiple agents. Tracks planner, engineer, deterministic checks and independent reviewer in isolated Git worktrees.
---

<!-- managed by multiagentic-eng -->

Use the installed `eng` CLI for coding changes that request multiple agents. Questions
about multi-agent systems remain ordinary conversation. When `ENG_ACTIVE` is set,
you are already inside the workflow: carry out your assigned role without submitting
another task.

If a prompt hook already reports a task ID, follow that task with `eng status TASK_ID`
instead of submitting the request again. Otherwise submit the user's request once
through `eng trigger`, passing the entire prompt as one argument and `--mode keywords
--project PATH`. Invoke processes with argument arrays so the prompt is never shell code.
Use the project's configured provider; choose `--provider NAME` only when requested.
If the user explicitly selects this skill for a coding request without a recognized
keyword, prepend `Use multiple agents for this request:` to the submitted description,
keeping their complete request after it. This makes explicit skill invocation route
through the same planner and reviewer workflow.

The repository must have a committed `.engineering/project.yaml`, ignored runtime
state and a clean checkout. If setup is missing, run `eng init`, inspect the proposed
checks and help the user choose a meaningful required check. Confirm only checks you
have reviewed; do not invent a passing check. Commit configuration with the user's
normal repository workflow before resubmitting. Never discard uncommitted work.

Keyword routing selects planner, engineer, required deterministic checks and reviewer,
with at least three model calls available. These roles run sequentially in an isolated
worktree. Parallel DAG plans remain a separate `eng plan` workflow requiring human
plan approval. High-risk task approval, plan approval and promotion remain human CLI
actions; never grant these approvals on the user's behalf.

Report the task ID and inspect `eng status TASK_ID` for progress, checks and workspace.
For paused or blocked tasks, explain the actual reason and required action. Completion
requires passing required checks and review. Show the resulting diff for human review;
do not push, deploy, delete workspaces or promote a plan automatically.
