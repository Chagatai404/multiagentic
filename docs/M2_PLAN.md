# M2 parallel implementation plan

## Primary goal

Run the same verified engineering workflow with either Codex or Claude Code, and
initialize and verify both Python and JavaScript projects without changing the engine.
All failures, missing capabilities and unavailable measurements must remain visible.

## Phase 0 — Documentation discovery (complete)

**How this serves the primary goal:** establish real provider and command contracts
before independent agents implement against them.

Three discovery agents inspected the repository and installed CLIs independently.
Baseline: d98360c on agent/codex/m2-portability; existing M1 PR remains separate.
No other overlapping working tree or configured project coordination was found.

Resource policy: compact fresh-context handoffs. Use low reasoning for registry/CLI
wiring, routine verification, documentation and commit administration; medium for
provider parsing, portability and independent review. Escalate only a specific problem
that warrants it. Do not run every agent at high reasoning.

Allowed APIs and source patterns:

- Frozen engine interface: Provider.execute(ProviderRequest, artifact_dir, cancelled)
  from src/eng/providers/base.py. Preserve saved-provider recovery in core/engine.py.
- Claude Code 2.1.301 installed help plus official [headless usage](https://code.claude.com/docs/en/headless),
  [CLI reference](https://code.claude.com/docs/en/cli-reference),
  [permissions](https://code.claude.com/docs/en/permissions),
  [environment variables](https://code.claude.com/docs/en/env-vars), and
  [SDK result parser](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/_internal/message_parser.py).
  Use safe-mode, restricted file tools, print/json, acceptEdits, permission-prompts
  none, strict empty MCP config, no shell tool and no permission bypass. Resolve the
  observed native npm entry or an explicitly supported legacy JS entry without a shell.
- Registry patterns: cli.provider_for, project config precedence, saved TaskSpec.provider,
  and existing typed Capabilities. Constructor factories must have no execution effects.
- Project patterns: projects/config.py, Check.confirmed, runner.py and disposable Git
  fixture construction in tests/conftest.py. Infer pytest from explicit pytest config;
  infer npm test only from a nonempty scripts.test. All discovered checks are unconfirmed.
- npm invocation follows installed npm 11.12.1 launcher and official
  [npm test](https://docs.npmjs.com/cli/v11/commands/npm-test/) and
  [scripts](https://docs.npmjs.com/misc/scripts/) documentation. npm itself executes
  reviewed project scripts in a shell; eng passes an argv array and does not interpolate.

## Phase 1 — Three concurrent implementation slices

**How this serves the primary goal:** independent file ownership lets provider support,
selection, and project portability progress concurrently without conflicting edits.

### Slice A: Claude adapter and credential isolation

Owner: claude_slice. Files: providers/claude.py, dedicated test_claude.py, narrow
execution/process.py environment extension, and optional Usage fields in core/models.py.
Expose ClaudeProvider and claude_command() -> list[str]. Preserve the Provider protocol.
Use bool | Literal['codex','claude'] for the process provider selector: False is a check,
True preserves Codex compatibility, named providers receive only their verified auth keys.

Parse single-object CLI results, including failures in stdout on nonzero exit. Normalize
permission denials, errors, malformed fields, cancellation and timeout conservatively.
Retain unknown counters as null. Claude total_cost_usd is a client estimate: introduce
optional cost_source metadata and cache_creation_input_tokens if needed to preserve its
meaning without breaking saved JSON. Do not conflate estimated cost with measured spend.

Verification: parser/error matrices, native/legacy resolution, isolated environments,
exact safe argv, cancellation/timeout evidence, redaction that preserves JSON and usage.
No model calls. Sources and copied patterns are those established in Phase 0.

### Slice B: provider registry and CLI integration

Owner: registry_slice. Files: providers/registry.py, cli.py, dedicated registry and CLI tests.
Implement immutable ProviderRegistration(name, factory, command), ProviderRegistry
register/names/create/capabilities/doctor, and build_registry(fake_changes=None).
Register fake, Codex and Claude; preserve cli.provider_for compatibility and fake-edit
validation. Explicit CLI selection overrides project defaults; resume uses its saved
provider. Doctor probes installed versions with bounded subprocesses, reporting
authentication='not_checked'; it must never claim model access from a version probe.

Verification: registry invariants, unknown/mismatched registration, all adapter names,
capability output, probe errors/timeouts, CLI precedence and saved-provider continuity.
No silent fallback/replay and no expensive availability probes while listing capabilities.

### Slice C: project discovery and two-language portability

Owner: portability_slice. Files: projects/config.py, execution/commands.py,
verification/runner.py, dedicated discovery/launcher tests, integration/test_portability.py,
and CI Node declaration. Preserve the confirmation gate and configured command snapshot.
Resolve only supported Windows npm shim layouts to Node plus npm-cli.js; unsupported
layouts become UNAVAILABLE with no shell fallback. Use {python} for portable discovery.

Verification: Codex and Claude adapters each run against Python and Node disposable
repositories through explicit deterministic protocol emulators, real subprocess edits,
real checks and retained evidence. Prove failing baselines, passing repaired worktrees,
unchanged source repositories and unconfirmed-check refusal. Emulators validate transport
contracts; they are not evidence of live model behavior. No external project mutations.

## Phase 2 — Integrate, independently review and verify

**How this serves the primary goal:** prove the combined slices preserve M1 recovery,
completion and permission guarantees across subsystem boundaries.

Wait for all owners and inspect their actual diffs. Fresh agents independently run the
verification checklist, inspect anti-patterns, and review code quality. Correct confirmed
defects in the owning slice. Run focused tests, full offline suite, Ruff, strict mypy for
Windows/Linux, package build and a fresh wheel smoke test. Inspect real installed CLI
versions without model calls. Keep the existing live Codex access-denial limitation.
Do not describe any live adapter edit or authentication as validated unless exercised.

Anti-pattern guards: no shell=True, permission bypass, Codex flags in the engine,
invented npm checks, credential sharing, usage fabrication, implicit replay/fallback,
provider probes in factories, or unconfirmed execution. Keep pure core contracts pure.

Update README, ARCHITECTURE, CHANGELOG, ROADMAP and validation notes with evidence.
Only a verification-approved agent may commit. Preserve the base history and report
branch/commit. Repository instructions prohibit automatic pushes; leave the reviewed
commit local unless existing human authorization explicitly covers publication.

## Not in M2

Adaptive roles/debug retries, automatic hooks, parallel scheduling inside eng, automatic
integration, API/local providers, and fine-grained tool/financial budgets remain M3–M6.
Development uses parallel agents now; that does not make eng's own M6 scheduler operational.
