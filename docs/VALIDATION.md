# Validation evidence — 2026-10-25

## M1 original evidence

Host: Windows, Python 3.14.4; installed Codex CLI 0.149.0. Dependencies were installed
into the repository's `.venv`; `uv.lock` records the resolved versions. The
restrictive desktop execution sandbox denied some Git/temporary-directory operations;
the offline suite ran in an approved local process against disposable repositories
under `.cache`.

Validation exercises real Git worktrees, a seeded failing check, file edits, process
execution, cross-process CLI inspection, durable cancellation, failure gates, unknown
outcome recovery, and process-tree cleanup after the direct child exits. Lint and
strict typing are also checked. Linux/Python 3.12 runtime execution is configured in
CI but was not executed locally; Linux static type analysis is a separate check.

Final offline result: **40 passed, 1 skipped** (the explicitly opt-in live test) in
**61.27 seconds**. Five focused checks also pass after the final recovery review. Ruff
and strict mypy pass for both Windows and Linux targets. Source and wheel builds
succeed; the wheel installs into a fresh Python 3.14.6 virtual environment and its
`eng providers` command works independently of the editable install.

The offline benchmark's first successful measured run completed in **4.776 seconds**,
including one FakeProvider invocation and a **1.219-second** passing check. Its
baseline check failed with exit code 1. Tokens and cost remain unknown for
FakeProvider. This tiny deterministic fixture is not evidence of model task success
rate or comparative agent latency.

One live Codex invocation ran with a 90-second provider timeout, a 120-second active
task budget and one permitted invocation. The CLI authenticated, completed its turn,
and reported **39,065 input tokens**, **21,760 cached input tokens** (a subset of
input), **257 output tokens** and **139 reasoning output tokens**. Cost was not
reported. The task's active time was approximately **20.92 seconds** before
finalization. These are provider-reported usage values; this project's
prompt-character cap does not limit the CLI's own system instructions, skills or other
provider-managed context.

The live agent could not edit answer.txt: its apply_patch tool returned Windows access
denied inside the nested workspace. The agent then returned a completed turn
explaining the failure. The independent check exited 1 and the engine correctly kept
the task **BLOCKED**. The opt-in success smoke test consequently failed. Do not
describe live editing as validated or bypass the provider sandbox to make this test
pass. No further model invocations were started. The live fixture and redacted
evidence remain in the ignored `.cache/pytest-live/` directory for local inspection.

The fake-provider path satisfies the M1 end-to-end acceptance. The real adapter's
invocation, event parsing and usage capture were exercised; successful live editing
still needs verification in an environment where Codex's supported workspace-write
sandbox can access its assigned workspace.

 ## M2 evidence and limits

M2 adds a Claude Code adapter checked against installed CLI 2.1.301 help, alongside
Codex 0.149.0. Version-only doctor probes do not authenticate or invoke models;
authentication remains `not_checked`. No successful live Claude edit has been
validated. The M1 Codex Windows workspace access failure above remains unresolved.

Final independent offline suite: **143 passed, 1 skipped in 71.72 seconds**. The skip
is the existing opt-in, potentially billable Codex live test. Ruff passes; strict mypy
passes for Windows and Linux targets across 26 source files. `uv lock --check` passes
with 28 resolved packages. Source and wheel builds pass; all 26 source Python files
are byte-identical to their build artifacts, and LICENSE is included. A fresh wheel
installed into the Python 3.14.6 environment at `.cache/m2-wheel-smoke`; `eng`
imported from its `Lib/site-packages`. Both `eng providers` and `eng doctor` passed,
with Claude 2.1.301 and Codex 0.149.0 version probes and authentication `not_checked`.
This smoke test made no model calls.

Final focused Claude coverage passed **72 tests in 4.36 seconds** and portability
coverage passed **37 tests in 24.79 seconds**. These overlap the full suite and must
not be added to its count. Independent anti-pattern audit and fresh code review found
no actionable findings; 14 additional pure-parser adversarial assertions passed.

Version-only doctor found Claude Code 2.1.301 and Codex 0.149.0 available, with
`authentication: not_checked`. These results verify M2 offline on this host. M2 CI
runtime execution has not been established: this branch is local and has not been
pushed.

The M2 portability matrix exercises Codex and Claude transports on disposable Python
and Node repositories. Deterministic protocol emulators drive real subprocess edits
and verification commands, including failing baselines and repaired worktrees; source
repositories remained unchanged. This validates transport and orchestration contracts,
not live model behavior. Discovery and launcher coverage checks unconfirmed-command
refusal, explicit pytest/package-script detection and supported Windows npm
resolution.

Claude usage tests preserve cache-read and cache-creation counters and label CLI
`total_cost_usd` as `client_estimate`. They do not measure account spend.
Provider-native input/cache counters must not be summed or compared as normalized
billing totals. The runtime core remains sequential; parallel development does not
validate an M6 scheduler.

## M3 - verified offline

M3 adds deterministic classification, adaptive sequential roles, standalone
planner/reviewer snapshots with mutation detection, bounded repair and per-invocation
persistence. Verification on Windows 11, Python 3.14, local only (2026-10-25):

- Full offline suite: 249 passed, 1 skipped (opt-in paid live Codex smoke test), run
  with a deliberately long pytest base directory so role snapshots exercise deep paths.
- Ruff, strict mypy for Windows and Linux targets, `uv lock --check`, source/wheel
  build, fresh-wheel install smoke and wheel-to-source byte comparison pass.
- Offline seeded-defect benchmark: failing baseline, verified repair in 4.81 seconds
  with one fake-provider call; small low-risk work keeps the single-engineer path.
- Independent read-only review (recovery, verify-only, approval, review digest binding,
  durable retries, completion gate, budgets) found no safeguard bypass. Verified
  findings were fixed with regression tests: Windows Git `Filename too long` in deep
  role snapshots (now `core.longpaths` plus a shallow `.engineering/artifacts/snapshots`
  root), snapshot setup errors mislabelled as mutation (now `role_setup`), mutation
  evidence dropped when a read-only provider raised, Git timeouts escaping as
  non-Git errors, and a review rejection at budget exhaustion spending the explicit
  extension on a fresh review instead of the pending repair.
- A boundary audit found no shell interpolation, no provider flags in core/agents,
  bounded context packets and no M4/M6 or live-editing claims.

The branch is not pushed; M3 CI execution is not established.

Known limitations recorded rather than fixed:

- Deep Windows paths: the shallow snapshot root is the mitigation. `core.longpaths`
  alone did not prevent Git object-write failures near 280 characters, and Git cannot
  enter directories beyond MAX_PATH. Snapshot copies use Python file APIs that pass
  260 characters here only because `LongPathsEnabled=1` (Windows defaults it off).
  Deep project roots or deeply nested trees can still fail, closed, as `role_setup`.
- Budget exhaustion is deliberately split: failed checks stay BLOCKED (M1 behavior;
  resume re-runs checks without a model call), review rejections PAUSE with a durable
  pending repair.
- A planner required only after implementation-time escalation is followed by a
  second engineer call; whether that call is always useful is unassessed.
- Workspace digests exclude gitignored files, so review binding does not cover
  ignored inputs that checks may read.
- A digest failure after a role's checkpoint advances is reported FAILED, while the
  durable record may still show `provider_started`.
- Snapshots share one root and are named by role and a random suffix, not task id. Each planner/reviewer call copies tracked and
nonignored content and runs `git add --all`; that time and disk cost is unmeasured
(M5). `eng plan` and `eng debug` remain deferred; `run`/`resume` expose the workflow.

CLI help is checked without model calls for classification overrides, high-risk
approval, repair limits, initial model-call budgets and resume extensions. No paid
model invocation is needed for offline M3 validation. M1/M2 evidence above remains
historical evidence, including the unresolved live Codex Windows access failure.
Successful live Codex/Claude editing remains unvalidated; adapter transports were not
changed to bypass this limitation.

`task.usage` represents the latest provider result. Persisted invocation records
preserve individual role usage; they are authoritative, not an invented task total.
CLI cost values remain client estimates rather than measured account spend, and
missing usage stays unknown. Parallel development does not validate parallel runtime
scheduling; scheduling/integration remain M6 work.

## M4 - verified offline

Client hook contracts were checked against the official Claude Code and Codex hook
documentation (2026-10-26) for installed claude 2.1.301 and codex 0.149.0. Verification
on Windows 11, Python 3.14, local only:

- Full offline suite: 341 passed, 1 skipped (opt-in paid live Codex smoke test), with a
  long pytest base directory. Ruff, strict mypy for Windows and Linux, `uv lock
  --check`, build, wheel-to-source comparison and fresh-wheel smoke pass; the installed
  wheel's hook module fails open (exit 0, systemMessage) on malformed input.
- End-to-end tests run the hook as a real subprocess with emulated Claude Code and
  Codex stdin, including the exact argv an installer writes. They cover routing with a
  detached runner that executes the fake-provider task after the hook exits,
  redelivery idempotency, question/slash/manual/ambiguous bypass with no state written,
  ENG_ACTIVE reentrancy, never exiting 2 on malformed input, unknown provider, non-
  repository, dirty-checkout, unignored-state and other-project cases, and that
  installation keeps `git status` clean.
- The runner test proves the hook returns while its child keeps running and that
  child output appends to the log; on this host `CREATE_BREAKAWAY_FROM_JOB` succeeded.
- An independent read-only review found no exit-2 path. Verified findings were fixed:
  import/interrupt failures not failing open, validation messages echoing prompt text,
  a crash window that could block redeliveries without a runner, bookkeeping errors
  after spawn letting a prompt through while a runner worked, no binding between hook
  and installed project, installer files dirtying the checkout, uninitialized state
  dirtying it, heuristic prompts warning in every dirty tree, and settings file mode
  loss on POSIX.

Development incidents, both caused by pytest temporary directories living under this
checkout's `.cache` (TEMP=.cache) and Git discovery climbing out of them:

- A "non-repository" e2e directory resolved to this checkout and routed one task here
  with the default claude provider. The engine refused it (dirty repository; FAILED,
  0 provider calls, no worktree); its records remain in the ignored `.engineering/state`.
- Installer unit tests appended eight lines to this checkout's `.git/info/exclude`;
  they were removed and the file restored byte-for-byte to its original content.

Fix: the autouse fixture sets `GIT_CEILING_DIRECTORIES` to each test's temporary
directory parent (Git does not protect the ceiling directory itself), and e2e hook
runs default to the fake provider. Re-running the installer and e2e tests left the
exclude file hash, task list and `.claude`/`.codex` paths of this checkout unchanged.

Not validated: hook firing inside live Claude Code or Codex sessions; whether those
clients pass ENG_ACTIVE to hooks spawned inside eng-launched providers; Windows job
breakaway inside the clients' hook processes (if refused, the runner may end with the
hook); Codex `commandWindows` quoting when the interpreter path contains spaces; POSIX
detachment (CI only). Routed task descriptions are stored in task payloads like any
`eng run` description; trigger digests are unsalted. A turn-keyed claim interrupted
before its runner started is never retried automatically; the prompt passes through.
