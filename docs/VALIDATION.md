# Validation evidence — 2026-10-25

## Efficiency E0/E1 working slice — 2026-10-26

Implementation started after the small ADR and five unchanged-behavior baseline
regressions passed; see `docs/efficiency/ADR-001.md`. E0 regression tests were written
before implementation and first produced three expected pure failures. The sandbox's
Git-backed fixture stalled and was stopped; the same offline tests subsequently ran
with approved local subprocess access and disposable repositories.

Focused E0 command:
`python -m pytest tests/unit/test_efficiency_telemetry.py tests/unit/test_m5_accounting.py tests/integration/test_m5_resources.py tests/integration/test_adaptive_engine.py tests/contract/test_providers.py -q --basetemp .cache/pytest-e0-focused`
passed **53 tests in 203.88 seconds**. Coverage includes result-JSON persistence,
Unicode packet sizes after snapshot isolation, native missing-counter/cost handling,
role routing, budget/recovery and risk/review safeguards. `ruff check` and strict
`mypy` passed for the changed accounting/runtime/CLI sources. CLI regressions were
also written first (two expected failures), then passed **3 tests** including a
provider/store-free preview, benchmark flag routing and historical-check reporting.
These focused counts overlap other suites and must not be summed as a full result.
The final E0/CLI regression command
`python -m pytest tests/unit/test_efficiency_cli.py tests/unit/test_efficiency_telemetry.py -q --basetemp .cache/pytest-e0-final-regressions`
passed **9 tests in 1.95 seconds**, including nested-project preview resolution and
the distinction between adapter entry, unknown process timing and unknown sessions.
After independent review, explicit role recovery and caught mutation/exception
telemetry regressions passed **24 tests in 81.95 seconds** with
`python -m pytest tests/unit/test_efficiency_cli.py tests/unit/test_efficiency_telemetry.py -q --basetemp .cache/pytest-role-and-mutation-final`.
This includes repeated reviewer recovery, known/unknown role thresholds, retained
enclosing stops, invalid-input/approval persistence and adapter-entry evidence after
an exception. Ruff and strict mypy pass for the affected CLI/runtime sources.

This is intermediate focused evidence; full milestone tests/build and E1 concurrency
validation must be recorded separately before handoff. No live providers, paid model
calibration, external CI delivery, hook activation, push or promotion ran in this slice.
Actual-model identity remains unknown in built-in adapters. Fake fixtures cannot
establish real-model savings, successful live editing or escaped-defect rates in use.

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

## M5 - verified offline

Independent Windows/Python 3.14 verification collected 430 tests: 429 passed and
one opt-in paid live test was skipped, in 400.49 seconds. That run imported Engine
before the final bounded-tail change; the tail fix separately passed 33 affected regression tests in 173.53 seconds
(three new bounded-tail tests, 20 adaptive-engine tests and 10 M5 resource tests). Ruff, strict
mypy for Windows and Linux (40 source files), and `uv lock --check` (28 packages)
passed. Final wheel and source-distribution builds passed using cached setuptools 84.2.1
with `--no-isolation`; the isolated build could not resolve the package index, and
the root virtual environment lacked setuptools. Cached build tooling was supplied
without modifying that environment. All 40 Python files and LICENSE matched the
source in both distributions; README matched the source distribution and normalized
wheel metadata. Eight isolated fresh-wheel CLI smoke checks passed, importing from
site-packages. The final Python source hash was
`1c6b161a42c3ce7ada248acbd2a5f6c9a9fd3af379713cff050223462a54a40b`. Focused transport/accounting/context runs are supporting checks, not
additional full-suite tests.

The repository's own test timeout is now 600 seconds and its active task budget is
900 seconds, accommodating the measured 400.49-second suite. Global defaults are
unchanged. During validation, a relative PYTHONPATH let detached children import the
M4 checkout; an absolute M5 source path corrected the environment, and 21 hook tests
passed. This was a test import correction, not a product hook change. The main
Claude checkout was unchanged.

Independent review prompted fixes
for overlapping known-secret redaction, preservation of numeric JSON counters, and
decimal reported-dollar threshold comparisons. A later boundary review found that
loading an entire check log before slicing its tail would scale with full artifacts.
The fix seeks and reads at most 20,000 bytes, preserves the final 5,000-character
failure excerpt, and passed three independently reviewed focused tests. No live calls or client hook installs
were used for this work.

The committed [raw Windows report](../benchmarks/results/m5-windows-offline.json)
was measured on Windows, Python 3.14, 2026-10-26, seed 20261026, with six scenarios,
three repetitions and three arms (54 observations, 18 per arm). Scripted edits are
fixtures, not models. All token and cost measurements remain null.

| Arm | Verified success | First-pass success | Calls | Repairs | Escaped defects | Median / P95 seconds |
|---|---:|---:|---:|---:|---:|---:|
| A | 9/18 | 9/18 | 18 | 0 | 9 | 0.401403 / 0.701993 |
| B | 9/18 | 9/18 | 18 | 0 | 0 | 0.618225 / 1.575039 |
| C | 18/18 | 9/18 | 39 | 9 | 0 | 4.012659 / 13.788429 |

B required intervention in 9 fixtures according to a next-action proxy; actual
human interventions were zero in every arm. Timings exclude external assessment;
B/C include their own verification checks. P95 is nearest rank on small samples,
not a population latency claim. Differences do not establish real-model quality,
spend savings or optimal invocation counts.

Context comparison produced 20 equal packets, 19 cache hits and one miss. Median
cached construction was 0.138097 seconds versus 0.071304 uncached: caching was slower
on this fixture and remains constructor opt-in, off by default. No CLI cache flag
or performance improvement is claimed. Runtime scheduling and Git/CI integration
remain M6; tool/turn telemetry remains unsupported. Historical live-editing, live
client-hook and POSIX runtime limitations above still apply.

## M5 close-out and M6 - verified offline on Linux (2026-10-26)

Host: Linux 6.18 (x86-64), Git 2.43.0, Node 22, Claude Code 2.1.310 (not authenticated;
no live call made), no Codex CLI installed. Python 3.12.3, 3.13.17 and 3.14.6.

**First POSIX run of the M5 suite.** The M5 tip (`325d9aa`) had only run on Windows
locally; its GitHub Actions run was green on ubuntu/windows x Python 3.12/3.14. Running it
on Linux produced **430 passed, 1 failed**: `test_debugger_repairs_and_keeps_all_check_logs`
indexed `rglob` results, which are in directory order (ext4 hash order here, NTFS name
order on Windows). The test now keys the two check rounds by parent directory name; no
product code was involved. M5 build, Ruff, strict mypy and the wheel smoke below pass.

**M6 offline evidence.** Final full run, after the last code change:

| Interpreter | Result |
|---|---|
| 3.12.3 | 554 passed, 3 skipped (82.77 s) |
| 3.13.17 | 554 passed, 3 skipped (81.24 s) |
| 3.14.6 | 554 passed, 3 skipped (83.84 s) |

Skips: the paid opt-in Codex live test, the Windows-only job-breakaway test, and the
official-MCP-SDK test, which needs the `mcp` package (not a dependency). That SDK test
passes (1 passed) in a scratch environment with `mcp` 2.3.0; CI runs it in its own job.
Ruff passes; strict mypy passes for `--platform linux` and `--platform win32` (51 source
files); `uv lock --check` passes (28 packages). Source and wheel build; all 52 package
files are byte-identical to `src/`, `py.typed` and `LICENSE` are in the wheel, and the sdist
carries README, LICENSE and the M6 docs. A fresh Python 3.13 environment containing only the
installed wheel ran, with no model call: `eng --version`, `eng providers` outside a
repository, `eng plan validate|create|run|promote|promote --approve` on a three-node plan
through a configured command provider (READY, three integration commits, checkout clean
and fast-forwarded), `eng mcp serve` initialize, `eng hooks git install|status` and
`eng verify-ref HEAD` (PASS).

What the 123 new tests (122 always run, plus the SDK interoperability test) exercise (all on disposable repositories, no model calls):

- Pure plan logic: pattern normalization, 13 overlap cases (symmetric), ownership
  matching, cycle/duplicate/unknown/self dependency rejection, concurrency bounds,
  readiness, skipping and plan-status derivation.
- Concurrency: a four-node plan observed overlapping (peak 2-3, never above three); a
  13-node plan that saturates at exactly three and produces one integration commit per
  node; two coordinators sharing one project-wide cap; `concurrency: 1` serializes;
  slot locks cap at three. The plan test file passed five consecutive runs unchanged.
- Safety: ownership violation FAILS the node and SKIPS dependents with nothing integrated;
  both sides of a rename are visible; an integrated tree that fails verification is rolled
  back and the node BLOCKED (each node passes alone, only the combination fails); a merge
  conflict BLOCKS without moving the head; a coordinator crash, an unrecorded integration
  commit and a tampered plan branch are reconciled or refused; promotion refuses a dirty
  checkout, a diverged branch, a detached HEAD and a moved plan branch, never runs without
  `--approve`, never twice, and no remote is ever configured.
- Approvals/budgets: a high-risk node pauses until `plan approve` or run-level approval;
  plan-wide limits with unknown coverage stop launches until `--clear-limits`; `create`
  refuses projects with no confirmed required check, an unknown provider, or a dirty
  checkout, leaving no branch or worktree behind.
- Triggers: PASS/FAIL/INCOMPLETE semantics; real `git commit` runs the installed hook and a
  detached verification records a result without delaying the commit; a blocking
  `pre-push` blocks a failing push and allows a passing one, and fails open when checks
  are unconfirmed; foreign hooks are never overwritten or removed; the hook is inert under
  `ENG_ACTIVE` and fails open outside a repository; CI success/cancel bypass, failure routes
  one deduplicated task per run attempt, the summary is redacted and quoted as untrusted.
- Providers/MCP: command provider stdin/exit/timeout/cancel/model-flag/environment
  scrubbing and credential redaction; MCP initialize/version negotiation, batches,
  notifications, parse/invalid-request errors, argument validation, redaction, the absence
  of any approval-class tool, idempotent `eng_submit`, and a real stdio subprocess.

**Bug found by load testing and fixed (coordinator starvation).** A full run on two
interpreters under a concurrent workload had one intermittent failure that the quiet runs
did not. Reproduced by running the plan tests beside six CPU-bound processes (4 cores):
about one run in four failed `test_two_plans_share_the_project_wide_slot_cap`, with a plan
left `CREATED`. Cause: a coordinator that could not take a project slot (another plan held
all three) and had nothing of its own running treated "nothing launched" as "nothing left to
do" and exited with ready work. Fix: a starved coordinator now waits and retries, emitting
`waiting_for_slot` once, until it can launch or is cancelled. A deterministic regression test
holds all three slots, shows the coordinator stays alive, releases them, and expects READY;
with the fix disabled the test fails, with it enabled it passes. Afterwards six consecutive
loaded runs of 63 trigger/plan/MCP/provider tests passed. Lesson recorded: a clean run on a
quiet machine does not prove a concurrency feature; always stress it.

**Bug found by the e2e tests and fixed.** Git exports `GIT_DIR`/`GIT_INDEX_FILE` to hooks;
the detached verifier inherited them and `git worktree add` failed ("Not a directory"),
recorded as INCOMPLETE. The hook entry point now scrubs repository-local `GIT_*` variables.
**Hardening found in review.** `changed_paths` used rename detection, which would hide the
deleted side of a rename from protected-path/ownership checks; it now uses `--no-renames`.
Plan limits had no explicit override; `--clear-limits` was added.

**GitHub Actions evidence (ubuntu-latest and windows-latest, Python 3.12 and 3.14, plus the
MCP-SDK and installed-wheel jobs).** Run 9 on `c4cd75d` passed all six jobs (the Windows
jobs execute the full suite, including threaded plans, slot locks, real Git hooks through
Git for Windows `sh`, blocking pre-push and the MCP subprocess; Windows 3.14 collected 556
items, 554 passed, and Git there was 2.56). The two earlier runs on this branch each
failed one Windows test and both failures were in the new tests, not in product code:
(1) run 7: the unusual-filename test wrote non-ASCII text as UTF-8 but the fixture's check
script read it with the platform default encoding (cp1252) - fixed in the fixture; (2) run
8: the saturation test counted overlap inside the provider call only, which depends on
machine speed (2 instead of 3 on a slow runner) although the cap held - tests now derive
in-flight nodes from recorded `node_started`/`node_finished` events (also across two plans
sharing the cap). Writing that measure exposed a real but harmless ordering gap: the slot
was released before the finish event was logged, so the audit trail could briefly overstate
concurrency; the finish is now recorded before the slot is released. Windows suite time is
about 5-6 minutes versus 80 seconds on Linux.

**Adapter drift check.** Every flag `ClaudeProvider` passes (`--safe-mode --restricted
--print --output-format --no-session-persistence --permission-mode --permission-prompts
--strict-mcp-config --mcp-config --setting-sources --tools --disable-slash-commands
--no-chrome --model`) is present in `claude --help` of 2.1.310 (baseline 2.1.301). Codex
could not be re-checked (not installed here); its baseline remains 0.149.0.

**Not established.** Successful live model editing with Codex or Claude (no authenticated
provider was available or used); firing inside live Claude Code/Codex hooks; real CI-service
delivery (`ci-trigger` is driven with emulated events and GitHub-style variables); any real
third-party command provider; Windows runtime behaviour beyond what the CI suite covers
(it passes the full offline suite, but only with emulated providers); load beyond three
concurrent nodes by design; and scheduling performance (no benchmark of M6
was made, so no speed or cost claim is made).


## User-wide installation and keyword routing (2026-10-26)

Windows / Python 3.14, on `agent/codex/user-wide-install`, based on `8c33d3c`:

- Full offline suite: **598 passed, 2 skipped** in 890.23 seconds. Skips: optional
  MCP SDK compatibility test (`mcp` not installed), and the opt-in paid Codex smoke test.
- Focused client suite before the final installer preflight change: 95 unit tests and
  26 hook integration tests passed. The full suite above includes that final change.
- Ruff and strict mypy passed (52 source files); bundled skill validation passed.
- Wheel and source distribution built successfully. Both contain the bundled workflow
  skill and neither contains the local build cache.
- The built wheel was installed into a persistent user-wide uv tool environment.
  `eng install` installed all four native hooks and shared/Claude/Copilot skills.
  A second installation reported `changed: false` for every hook and skill.
- An installed-wheel CLI keyword request in a disposable repository completed with
  planner, engineer, passing required checks and independent reviewer: exactly three
  deterministic fake-provider invocations.
- The actual generated user hook commands for Claude Code, Codex, Gemini and Cursor
  were executed with emulated client payloads and an explicit fake-provider override.
  All returned their client-specific blocking response, and all four resulting tasks
  completed with three fake invocations and passing required checks.
- Unit coverage includes user/project scope separation, default and overridden client
  homes, preserving unrelated configuration, backups, idempotent install/remove, skill
  ownership/collision handling, custom skill directories, malformed-settings preflight,
  bounded keywords, question/slash-command bypass and recursion prevention. Integration
  coverage includes keyword routing/deduplication for all four clients and unbound
  routing across two independently configured repositories.

The full suite and detached-process tests ran with normal Windows subprocess permissions.
Inside the desktop sandbox, default TEMP writes were denied and a detached-hook test
stalled; rerunning outside that sandbox passed. No product-code workaround or permission
bypass was added for that environment restriction.

**Not established:** actual hook delivery inside any live client, successful live model
editing, model authentication or real CI-service delivery. Installing settings is separate
from client hook activation; Codex still requires the user to review/trust `/hooks`.
Copilot and unknown skills-compatible clients use model-selected skill discovery, without
an assertion of deterministic prompt interception. Gemini/Cursor hook integration does
not add those products as engine model-provider adapters. Parallel DAG plans and human
approval/promotion boundaries remain unchanged.

E0/E1 efficiency milestone evidence, exact commands and remaining limitations are in
[efficiency verification](efficiency/VERIFICATION.md).
