# E3–E5 verification checkpoint — 2026-10-26

Scope: [ADR-003](ADR-003.md) routing, [ADR-004](ADR-004.md) repair economies and
[ADR-005](ADR-005.md) presets. Offline only. No paid provider, live client,
deployment, promotion or destructive cleanup. Branch `claude/efficiency-e3-5`, on top
of the E2 checkpoint (`ab49793`); E3 `c5cf222`, E4 `bcba72a`, E5 in the commit that
adds this report. Each slice passed the full offline suite before its commit.

Environment: Linux 6.18 container, CPython 3.13.17, Git 2.43.0, `uv` managed venv.

| Gate | Command | Result |
|---|---|---|
| Complete offline suite (final) | `uv run pytest -m 'not live' -q -p no:cacheprovider -rs --basetemp <scratch>/pt` | **713 passed, 2 skipped, 1 deselected**, 125.96 s |
| After E3 / after E4 | same | 700 / 706 passed, same skips |
| Lint | `uv run ruff check .` | Passed |
| Strict types | `uv run mypy --strict src/eng` | Passed, 55 source files |
| Wheel and sdist | `uv build --out-dir <scratch>/dist` | Passed; sdist contains ADR-003..005, ROUTING.md, `core/routing.py`, `core/presets.py` |
| Installed-wheel smoke | isolated venv, `python -I`: balanced preset on a complex task → 5 calls with headroom on; a model route resolves; `eng run --help` lists `--preset` | Passed |
| Diff whitespace | `git diff --check` | Passed |

Skips: optional `mcp` SDK not installed; Windows-only job breakaway. Deselected: the
opt-in paid Codex smoke. The three files flagged by `ruff format --check` on the base
commit remain unformatted (pre-existing drift; their E3 capability edits are small).

## What the new tests establish

- **E3** (`tests/unit/test_routing.py`, `tests/integration/test_routing_engine.py`):
  first-match rules, role constraints, rule validation and unique labels; engineer and
  reviewer receive different routed models after changed-path risk escalation;
  explicit task models win; providers without model selection skip routes with an
  event; `eng run` routes the provider only without `--provider`; plan nodes freeze
  routed providers, explicit node providers win, and preview agrees.
- **E4** (`tests/integration/test_repair_economy.py`): unchanged check repairs pause
  without re-running checks and complete after a human fix and resume; unchanged
  review repairs skip the repeat review; headroom blocks a repair whose required
  review cannot run, keeps review repairs durable and respects role allocations;
  defaults reproduce the previous loop. Enabling both settings by default changed ten
  existing fixture flows, which is why they are opt-in.
- **E5** (`tests/unit/test_presets.py`, `tests/integration/test_presets_cli.py`): calls
  derived from required roles and repairs; thresholds and role sublimits untouched;
  precedence beneath explicit options and plan/node settings; preview, frozen node
  workflow and launch-time task config agree.

## Not established

Any real cost, token or quality effect of routes, repair economies or presets; live
provider editing; live client hooks; real CI delivery; Windows runtime for E2–E5. No
separate independent reviewer pass was run. Expanded dashboards were not implemented.
