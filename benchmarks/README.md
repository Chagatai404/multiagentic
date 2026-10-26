# Offline workflow benchmark

Run from an installed package with `eng benchmark`, or from a source checkout:

```powershell
$env:PYTHONPATH = 'src'
python benchmarks/offline.py --repetitions 3 --seed 42
```

Use a short writable `TEMP`/`TMP` directory on Windows. This creates fresh disposable
repositories, applies a Git discovery ceiling, preserves each fixture's source checkout,
and never calls a live model or installs hooks. Repetitions are bounded to 1–10;
`--scenario` may select unique names from the six categories. Order and fixture values
are seeded. Timing, random task IDs and temporary paths are intentionally not stable.

A runs a single scripted coding call; B runs that same call plus acceptance checks;
C runs the production adaptive Engine with its planning, verification, repair and review
gates. A and B use separate benchmark paths; production completion rules are unchanged.
Every arm starts from the same scenario files and uses the same external evaluator,
stored outside its editable workspace. The large refactor is a synthetic twelve-module
fixture. The failing-tests, cross-module integration and architecture scenarios receive
an intentionally incomplete first edit; C's debugger receives a prewritten final edit.
This tests orchestration, not model intelligence or real-world model quality.

The report contains raw rows and per-arm counts/rates. Verified success means external
acceptance passed. First-pass success means that happened without repair. Escaped defects
mean the workflow declared success but external acceptance failed. `human_intervention`
is zero (no human acts during fixtures); `human_intervention_required` counts rejected or
blocked outcomes as a next-action proxy, not human time. Unnecessary calls have no oracle
and remain null. Token usage, dollars and per-success resource measures remain null.

Workflow duration includes that arm's work and configured checks, and excludes the final
external assessment, whose duration is recorded separately. Median and nearest-rank P95
are descriptive measurements of these local scripted runs. Small samples do not establish
population behavior or real-model performance.

The context microbenchmark alternates cached and uncached packet construction, checks
byte-for-byte string equality every iteration, and reports raw timings and cache work.
It includes current source reads/hashes, Git metadata and redaction. A cache can be slower;
reduced decode work does not imply reduced wall time, tokens or inference cost. The cache
is an optional execution-local in-memory dependency and never persists plaintext context.
