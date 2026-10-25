# Validation evidence — 2026-10-25

Host: Windows, Python 3.14.4; installed Codex CLI 0.149.0. Dependencies were installed
into the repository's `.venv`; `uv.lock` records the resolved versions. The restrictive
desktop execution sandbox denied some Git/temporary-directory operations; the offline
suite ran in an approved local process against disposable repositories under `.cache`.

Validation exercises real Git worktrees, a seeded failing check, file edits, process
execution, cross-process CLI inspection, durable cancellation, failure gates, unknown
outcome recovery, and process-tree cleanup after the direct child exits. Lint and strict
typing are also checked. Linux/Python 3.12 runtime execution is configured in CI but
was not executed locally; Linux static type analysis is a separate check.

Final offline result: **40 passed, 1 skipped** (the explicitly opt-in live test) in
**61.27 seconds**. Five focused checks also pass after the final recovery review.
Ruff and strict mypy pass for both Windows and Linux targets.
Source and wheel builds succeed; the wheel installs into a fresh Python 3.14.6 virtual
environment and its `eng providers` command works independently of the editable install.

The offline benchmark's first successful measured run completed in **4.776 seconds**,
including one FakeProvider invocation and a **1.219-second** passing check. Its baseline
check failed with exit code 1. Tokens and cost remain unknown for FakeProvider. This
tiny deterministic fixture is not evidence of model task success rate or comparative
agent latency.

One live Codex invocation ran with a 90-second provider timeout, a 120-second active
task budget and one permitted invocation. The CLI authenticated, completed its turn,
and reported **39,065 input tokens**, **21,760 cached input tokens** (a subset of input),
**257 output tokens** and **139 reasoning output tokens**. Cost was not reported.
The task's active time was approximately **20.92 seconds** before finalization. These
are provider-reported usage values; this project's prompt-character cap does not limit
the CLI's own system instructions, skills or other provider-managed context.

The live agent could not edit answer.txt: its apply_patch tool returned Windows
access denied inside the nested workspace. The agent then returned a completed turn
explaining the failure. The independent check exited 1 and the engine correctly kept
the task **BLOCKED**. The opt-in success smoke test consequently failed. Do not describe
live editing as validated or bypass the provider sandbox to make this test pass.
No further model invocations were started. The live fixture and redacted evidence
remain in the ignored `.cache/pytest-live/` directory for local inspection.

The fake-provider path satisfies the M1 end-to-end acceptance. The real adapter's
invocation, event parsing and usage capture were exercised; successful live editing
still needs verification in an environment where Codex's supported workspace-write
sandbox can access its assigned workspace.
