# Native plugin validation — 2026-10-28

This is offline evidence for 2.0.0-beta.1, not live-client certification.

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

Remaining before stable release: follow the real-client smoke procedure in
[NATIVE_PLUGINS.md](NATIVE_PLUGINS.md), measure comparable single-agent/native-parallel
runs, and record actual host versions, observed usage fields and acceptance results.
