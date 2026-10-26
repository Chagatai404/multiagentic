# Efficiency benchmark evidence and calibration

The offline harness measures deterministic orchestration using scripted FakeProvider
edits. It does not measure model intelligence, real model quality, paid savings or
ChatGPT subscription credits. Existing M5 results remain under `benchmarks/results/`.
The E0/E1 raw report is `baseline-results.json` alongside this document.

## Reproduction

Run from this checkout with the development environment installed. Use a short writable
temporary directory on Windows; keep `PYTHONPATH` absolute because child working
directories differ. This command creates disposable repositories, never invokes a live
provider, never promotes a branch, and does not alter the source checkout:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$env:TEMP = (Join-Path (Get-Location) '.cache')
$env:TMP = $env:TEMP
.venv/Scripts/python.exe -c "import json; from pathlib import Path; from eng.benchmark import run_benchmark; report=run_benchmark(seed=42,repetitions=1,include_efficiency_cases=True); Path('docs/efficiency/baseline-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')"
```

The saved evidence also includes a `provenance` envelope identifying base commit
`e7a2c5b`, E0/E1 working-tree state, runtime and the exact methodology. Reproduction
on another revision must identify that revision instead; timings need not match.

Seed-42, one-repetition fixture results (six rows per arm):

| Arm | Verified | First pass | Calls | Repairs | Escaped defects |
| --- | ---: | ---: | ---: | ---: | ---: |
| A single scripted call | 3/6 | 3/6 | 6 | 0 | 3 |
| B call plus checks | 3/6 | 3/6 | 6 | 0 | 0 |
| C production adaptive Engine | 6/6 | 3/6 | 13 | 3 | 0 |

The approval control pauses with zero calls. The disjoint control integrates both
nodes, passes final assessment with two calls, and leaves the main checkout unchanged.
All token and cost values are null. These counts demonstrate fixture behavior only.

For repeated measurements, set `repetitions=3` (bounded to 1–10). Seed 42 controls
fixture values and shuffled A/B/C order. Timing, task identifiers and temporary paths
are intentionally variable. The additional controls run separately after the shuffled
arms, and are not included in comparative arm summaries.

## Cases and outcomes

| Case | Fixture and evidence |
| --- | --- |
| `small_bug` | One arithmetic fix; external evaluator fails on the initial tree. |
| `medium_feature` | Numeric clamp integration boundary checks; medium complexity. |
| `large_refactor` | Twelve-module interface change; production planner and reviewer remain due. |
| `failing_tests` | First edit fails required acceptance; scripted debugger can repair. |
| `cross_module_integration` | Initial edit leaves a consumer incomplete; checks catch the mismatch. |
| `architecture_violation` | Numerically correct first edit violates an AST dependency check. |
| `high_risk_approval` | Production Engine blocks an unapproved security task before any provider call. |
| `disjoint_cross_module_plan` | Two independent nodes own separate directory trees, execute through PlanRunner with explicit concurrency two, and pass serialized integration checks. Main checkout stays unchanged and promotion is never invoked. |

A is a single scripted coding call; B adds deterministic acceptance to that same call;
C uses the production Engine including its classification, required checks, review and
repair policy. A/B are benchmark comparators, not production completion alternatives.
Every arm uses identical scenario contents and an evaluator outside the editable
worktree. Source checkout and evaluator immutability are checked after each row.
The plan control's per-node check accepts either missing sibling work or correct
existing files; a separate final assessment requires both integrated outputs.

`verified_success` means external fixture acceptance passed, not human acceptance.
`declared_success` means that arm declared success. `escaped_defects` counts declared
success with failed external acceptance. `repairs` counts fixture repair attempts;
`first_pass_success` requires acceptance without repair. `human_intervention_required`
is a next-action proxy and actual human interventions are zero. The high-risk control
records a correct gate stop separately, rather than treating it as a failed optimizer.
Disjoint control configured concurrency is not a measured speedup or proof of overlap.

Raw wall timings are measured locally. Workflow time excludes the final external
assessment; B/C include their own checks. Median and nearest-rank P95 are descriptive
only; small samples do not support population claims. The context microbenchmark
alternates cached/uncached construction and checks equal packets; a slower cache is
a valid result. Cache remains off by default.

Fake invocation counts are measured orchestrator calls. Tokens, cache billing, dollars,
actual provider model, internal provider turns and unnecessary invocations have no
fixture measurement and remain null/unavailable. Zero paid invocations in this harness
does not imply zero production cost. Schema 1 and the existing six default scenarios
remain compatible; `include_efficiency_cases=True` produces schema 2 with additional
`control_cases`. No pricing rule is implicit in either schema.
Rows include the actual initial complexity/risk classification. The E0 fixture text
adds an explicit integration cue to `medium_feature` so it exercises medium complexity;
the old M5 description actually classified as small. This does not add or remove any
required safeguard, and its expected A/B/C call counts stay the same.

## Owner-opt-in live calibration protocol (not executed)

1. Obtain explicit owner confirmation naming one provider, selected model (or provider
   default), fixture revision, account and the exact initial limits: **one small low-risk
   task, one CLI invocation, 60-second provider timeout, 90-second active wall budget,
   context packet limit 8,000 characters, no repairs**. A money ceiling must be enforced
   by provider/account tooling if available; eng cannot promise an in-flight dollar cap.
   Approval of this document or ordinary offline testing does not authorize calibration.
2. Copy the seeded small fixture into a fresh disposable repository. Use the existing
   required external check, isolate the worktree, and keep the same objective, source
   bytes, acceptance and engine configuration between comparison runs. Record source
   commit, Python/OS, engine revision, installed adapter CLI versions and redacted
   configuration. Run no hooks, recursive orchestration or automatic promotion.
3. Run only the explicitly approved initial provider task. Persist redacted bounded
   invocation/evaluator evidence, selected provider/model and separately any verifiable
   actual model, packet characters/UTF-8 bytes, orchestration calls, native usage and
   missing coverage, check durations, active wall time, final state, repair count and
   external acceptance. A reported completed turn is not a verified edit. Retain unknown
   usage, cost and model fields as null. Stop on timeout or unknown outcome; inspect and
   use the existing verify-only acknowledgement rather than replaying the invocation.
4. Report that single run and obtain fresh explicit authorization before another paid
   call. Only then run the other provider against the same fixture and budget. A full
   complex-workflow comparison needs separately approved planner/engineer/reviewer
   allowances; never squeeze it into a one-call budget by dropping required roles.
5. Store live results separately with `fixture_kind: live_provider_measurement` and
   provenance for each native counter. Compare verified outcomes and escaped defects
   alongside usage. Keep reported costs, client estimates, explicit versioned pricing
   estimates and independently measured account spend separate. Never sum cached token
   subsets into total input, infer subscription credits, or call pricing estimates
   measured spend. Without repeated comparable successful edits, make no savings claim.

The historical Codex smoke in `docs/VALIDATION.md` reported 39,065 input tokens for one
invocation, then failed its edit/check because of a Windows access error. That is usage
evidence, not live-edit success or evidence that an 8,000-character packet bounds total
provider context. No new live Codex or Claude validation is established by this slice.
