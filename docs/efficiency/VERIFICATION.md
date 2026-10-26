# E0/E1 verification checkpoint — 2026-10-26

The frozen E0/E1 implementation passed its complete offline gate on Windows 11
10.0.26200 / CPython 3.14.4. No paid provider, live client, push, deployment,
promotion, destructive cleanup, user-wide tool update or Research OS operation was
performed. This checkpoint stops here at the owner's request.

## Tested source identity

- Branch: `agent/codex/efficiency-e0-e1`.
- Base commit: `e7a2c5b7baa1bbeaf372fe50a27ebde02d914139`.
- Initial tracked binary working-diff SHA-256:
  `95d40e5772610de4fe99d5cc8789cadb333ae48d675471a8e6b9be0317986d4b`.
- Runtime/test/build changed-file manifest SHA-256:
  `12e81d1359d25741a67c41450652cac7b68a50579493fbb731dfdb1f42b88faf`.

The initial manifest also hashes untracked deliverables, including the raw benchmark.
Its runtime/test/build subset covers changed `src/` and `tests/` files and
`MANIFEST.in`; unchanged files are identified by the base commit. The canonical hash
is SHA-256 of the path-to-file-SHA256 dictionary encoded with
`json.dumps(mapping, sort_keys=True, separators=(',', ':'))`. Comparing every entry
after the full run found **no changed runtime, test or build files**. Documentation,
coordination and generated package metadata are excluded from that final comparison.
No milestone commit existed when this report was written; the final local commit
must be identified in the handoff rather than inferred from branch existence.

## Results and exact commands

Commands ran from the repository root. Offline subprocess tests and builds ran with
normal Windows subprocess permissions: the desktop sandbox previously blocked TEMP
writes and Proactor socket-pair setup. No product permission bypass was introduced.

| Gate | Command | Result |
|---|---|---|
| Complete offline suite | `.venv/Scripts/python.exe -m pytest -m 'not live' --basetemp .cache/efficiency-full-final --junitxml .cache/efficiency-final-evidence/pytest.xml` | **668 passed, 1 skipped, 1 deselected**, 1130.41 seconds |
| Lint | `.venv/Scripts/python.exe -m ruff check .` | Passed |
| Strict types | `.venv/Scripts/python.exe -m mypy --strict src/eng` | Passed, 52 source files |
| Wheel and source archive | `uv build --offline --out-dir .cache/efficiency-final-evidence/dist` | Passed using cached isolated build dependencies |
| Isolated environment | `uv venv --python .venv/Scripts/python.exe .cache/efficiency-final-evidence/wheel-env` | Created under repository cache |
| Offline wheel installation | `uv pip install --offline --python .cache/efficiency-final-evidence/wheel-env/Scripts/python.exe .cache/efficiency-final-evidence/dist/multiagentic_eng-1.0.0-py3-none-any.whl` | Passed; no global/user tool changes |
| Installed-wheel smoke | `.cache/efficiency-final-evidence/wheel-env/Scripts/python.exe -I .cache/efficiency-final-evidence/wheel_smoke.py` | Passed |
| Actual diff whitespace | `git diff --check` | Passed |

The skipped module is `tests/integration/test_mcp_sdk.py`: optional `mcp` is not
installed. It was not installed merely to broaden this checkpoint. The deselected
test is the opt-in paid Codex smoke; `-m 'not live'` excludes it even if its environment
opt-in were set. Existing adapter tests use offline protocol emulators.

An initial `.venv/Scripts/python.exe -m build --no-isolation --outdir
.cache/efficiency-final-evidence/dist` attempt failed because `.venv` lacks
`setuptools`. The successful `uv build --offline` used the already cached backend;
this was an environment dependency issue, not a source build failure. No downloads
or additional optional SDK installation were needed.

The wheel smoke imports `eng` from the isolated environment's `site-packages` with
Python isolation enabled. It creates a disposable Git fixture, runs a fake-provider
task to COMPLETED in one orchestration invocation, checks schema-2 CLI usage,
measured packet characters and null missing tokens/cost/account spend/subscription
allowance/human acceptance. Its plan preview resolves node overrides, defaults to
concurrency one and creates no runtime files. The source answer stays unchanged.
It verifies the bundled workflow skill in the wheel and both the skill and
`docs/efficiency/baseline-results.json` in the source archive.

Final archives are refreshed after report creation with the same offline build
command, without repeating unchanged-source tests. The final archive inventory and
hashes are retained separately to avoid a self-referential report hash.

## Evidence and independent review

Retained local evidence is under `.cache/efficiency-final-evidence/`:
`source-before.json`, `source-after.json`, `pytest.log`, `pytest.xml`, `ruff.log`,
`mypy.log`, `build.log` (initial environment failure), `build-uv.log`,
`wheel-env.log`, `wheel-install.log`, `wheel_smoke.py`, `wheel-smoke.log`,
`wheel-smoke-results.json`, final build/archive logs, and `dist/`. The temporary
repositories and isolated wheel environment are retained. Cache evidence is local;
the durable checked-in evidence is this report and the benchmark JSON.

The full gate includes legacy CLI/storage compatibility, forward migration,
per-node inheritance and saved effective allocations, role-budget recovery,
cross-process admission, committed reservation survival after process death,
unknown-usage stops, lease recovery, disjoint ownership, serialized integration,
read-only role protection, required checks/review and human approval gates.
Before this gate, a separate fresh reviewer reported no blocking findings and
independently passed 32 E1 budget/scheduler tests and 24 CLI/telemetry tests.

Inspection of the actual diff and added-line anti-pattern scan found no new
automatic push/deploy/promote behavior, shell interpolation, credential logging,
model-callable approval, invented dollars, subscription-credit inference, or
cache-counter double counting. Human CLI budget recovery remains explicit and
cannot raise a role's effective overall task allowance or waive required checks.
Missing telemetry remains unknown; finite reported plan thresholds serialize
admission because no calibrated token reservation estimate exists. In-flight usage
can still exceed thresholds.

The existing [raw baseline](baseline-results.json) contains 18 scripted rows
(six identical seeded fixtures across three arms), plus an unapproved high-risk
zero-call pause and a disjoint two-node READY/unpromoted control. It records Windows
3.14.4, base `e7a2c5b` and the E0/E1 working tree before milestone commit. It was
not rerun for this checkpoint: the full suite exercises its harness and controls.
Scripted quality outcomes and local timing support orchestration claims only;
tokens, dollars and actual-model quality remain unavailable. No paid savings claim
is established.

## Remaining work and unverified environments

Linux, actual live client hook delivery, real CI-service delivery, authenticated
provider editing, actual model quality and paid calibration were not run. The
optional MCP SDK compatibility check remains unavailable. Benchmarks are small
scripted samples, not population estimates or model-quality evidence.

E2–E5 remain future work: scoped context manifests and provenance-bound summary
caching; human-attested plan reuse; capability-validated provider/model routing;
retry/review reuse and deterministic triage improvements; implemented operating
presets and expanded dashboards. Current operator examples are not preset flags.
Any paid calibration still requires the owner's explicit separate authorization
under the [live protocol](BENCHMARKS.md). Resume from this verified E0/E1 checkpoint;
do not infer that the later slices have been implemented.
