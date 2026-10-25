# Evaluation plan

Run `python benchmarks/offline.py` for a reproducible seeded defect and verified
FakeProvider repair. This is a deterministic correctness baseline, not an agent
intelligence or performance comparison. It uses a temporary repository and never
touches external project repositories.

M5 adds repeated A/B/C runs: single coding agent, coding agent plus deterministic
checks, and adaptive orchestration. Hold repository start state and acceptance fixed.
Include bugs, medium features, refactors, failing tests, cross-module changes, and
architecture violations. Measure verified success rate, tokens/cost per success,
median/P95 duration, first-pass success, retries, unnecessary invocations, human
intervention and escaped defects. Separate measured tokens from estimated prices,
unknown data and subjective grading; report sample sizes and variability.
