# Native plugin validation — 2026-10-28

The first section records offline build evidence for 2.0.0-beta.1. The Windows
follow-up below records separate, limited live-client evidence.

| Check | Result |
| --- | --- |
| `npm test` | 21 passed: DAG/read-write ownership, readiness, open decisions, state digests, packet bounds, authorization, dispatch, cancellation, timeout, locks, symlinks, native adapter registration and real Pi file tools |
| `npm run check` | Pass against Pi SDK 1.4.0 and OpenCode plugin 1.19.5; OpenCode's config fields checked against its SDK v2 type because its hook still exports a v1 Config type |
| `npm run check:package` | Pass: manifest identity, marketplace paths, skills/licenses/links, no agent subprocess dependency, npm archive contents |
| `uv run pytest -q` | 713 passed, 3 skipped |
| `uv run ruff check .` | Pass |
| `uv run mypy` | Pass, 57 Python source files |
| `uv run python -m build` | Python sdist and wheel built; legacy readme retained |
| Fresh-context planning exercises | Shared-type/profile case and CSV invoice-import case; both retained user decisions, blocked on material unknowns, and avoided premature execution |

Python skips: optional MCP SDK not installed; paid live Codex smoke test not enabled;
Windows-only process-job test on Linux. Windows CI is configured but was not run locally.
Claude/Codex/Pi/OpenCode interactive client executables were not installed on this host;
the Pi SDK and OpenCode plugin libraries were available for compatibility tests. No
live model requests were made by these offline tests. Do not equate SDK registration
or mocked workers with successful end-to-end client execution.

Measured static context: 734 characters across the three skill metadata blocks; the
example's first two worker packets are 1,553 and 1,521 characters. These are character
counts, not tokenizer counts, billable usage or a demonstrated reduction versus a baseline.

The combined interview exercise preserved CSV-only/5 MB/no-queue decisions, asked the
unresolved atomicity question first, made the shared contract a prerequisite, proposed
an initial end-to-end behavior, and treated three workers as a ceiling. The profile
exercise assigned the shared type a single owner and deferred implementation until
access behavior and user approval were resolved.

Orca: a dedicated workspace profile maps the same approved plans to underlying
native subagents or Orca-supervised Runs, with one scheduler and verified dependency
gates. Orca itself is not installed here; no live runtime exercise is claimed. A fresh-context
Orca scenario preserved the two-worker ceiling, blocked a dependent task until merge
and checks, prohibited nested Pi dispatch, and identified WSL installation/ancestry
checks without inventing runtime capabilities.

Remaining before stable release: follow the real-client smoke procedure in
[NATIVE_PLUGINS.md](NATIVE_PLUGINS.md), measure comparable single-agent/native-parallel
runs, and record actual host versions, observed usage fields and acceptance results.

## Windows local handoff follow-up

The bundle checksums and complete Git history were verified before importing
`feat/native-agent-workflows` into a separate checkout. The existing checkout,
branches, worktrees and remote were preserved. The imported checkout targets
`Chagatai404/multiagentic-engineering`; PR [#3](https://github.com/Chagatai404/multiagentic-engineering/pull/3)
contains the implementation and local follow-up.

Windows setup used Orca 1.4.243, Codex CLI 0.164.0, Claude Code 2.1.312,
Node 24.15.0 and CPython 3.14.6. The native plugin was installed through the
documented local marketplaces for Codex and Claude. Orca registered the imported
project and launched the existing authenticated Windows Codex account without a
model override. WSL had only the Docker Desktop distribution; OpenCode and Pi
executables were absent, so those live clients remain untested.

`eng uninstall --scope user` removed identified managed legacy prompt hooks and
managed skill files, preserving unrelated settings and existing/new `.eng-backup`
files. Worktrees and legacy execution records were retained. Host hook messages
(`plugin contents changed; hook approval required`) were observed in the Orca
session; no hook trust or approval policy was bypassed.

Windows native CI initially demonstrated a canonical-path bug: an 8.3 project
root such as `RUNNER~1` was compared with an expanded `realpath` target, causing
valid Pi edits to fail ownership checks. A directory-alias test reproduced the
failure locally before the fix. The Pi adapter now computes ownership relative
to the canonical root; the regression also checks that sibling writes stay
forbidden. The existing path test now expects the documented canonical result.
All 22 native tests, TypeScript and package validation pass locally and in the
corrected Linux/Windows native CI jobs. Ruff and strict mypy (57 sources) pass;
the Python sdist and wheel build successfully.

The first live Orca/Codex exercise found all three installed skills and used real
native delegation and interruption. An unresolved choice yielded no ready packets;
an intentional assertion failed, and blocked/interrupted producers did not unlock
their consumer. Two producers were interrupted without delivering their modules,
and an edit approval remained pending during the bounded attempt. No successful
combined assertion or preservation of a nonempty partial edit was demonstrated.
The attempt's report and blocked state were retained locally, with no automatic
replay. This is partial runtime evidence, not live workflow certification or a
token/speed benchmark.

The user explicitly authorized one fresh attempt in a separate initialized Git
fixture. Two native Codex workers changed only their assigned existing modules,
`gamma.mjs` and `delta.mjs`, from base
`d9431d1fca9347dc697c3f98027952bfcc931f69`. The coordinator inspected the actual
diff, ran both module assertions, marked the producers verified, and only then
ran the combined `gamma|delta` assertion. All three commands exited 0. The setup
owner independently inspected both edits and reran those assertions successfully.
The first attempt's blocked state was retained rather than overwritten. This
establishes the small Windows Orca/Codex shared-checkout flow; separate worker
worktrees, WSL/SSH and mixed-agent Orca-supervised dispatch remain untested.

At runtime commit `6792d3d`, all eight jobs in GitHub Actions run
[40759370423](https://github.com/Chagatai404/multiagentic-engineering/actions/runs/40759370423)
passed. Python 3.12/3.14 passed on Linux and Windows; the captured Windows 3.14
summary was 714 passed/2 skipped and Linux 3.12 was 713 passed/3 skipped. The
separate optional MCP compatibility job passed. Local Windows pytest used a
fresh project-cache base directory because its default user temp folder was
inaccessible; its full result is recorded separately from CI.

A fresh independent read-only code review of `6792d3d` found no actionable defects
in planning/state gates, ownership wrappers, cancellation, SDK registration or
packaging. It retained successful live editing/integration and inherited host
permissions as validation gaps.

The locked dependency audit reported six affected package entries (five high,
one moderate), including transitive `toml`, `zod` and `undici` advisories. The host
SDKs pin affected versions; npm's suggested forced remediation downgrades the
host packages outside the validated API generation. No forced downgrade or
unvalidated dependency override was applied. These audit findings remain open;
passing functional checks do not resolve them.
