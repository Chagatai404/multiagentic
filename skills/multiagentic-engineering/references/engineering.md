# Engineering practices

Adapted from Matt Pocock's engineering skills. Use the existing repository conventions
and the user's decisions. These practices do not require an issue tracker or more agents.

## Design and slicing

Prefer a small interface that hides meaningful behavior. Specify inputs, outputs,
errors, invariants and ordering, not only type signatures. Keep changes and tests close
to that behavior. Add an abstraction when there is real variation to isolate, not to
anticipate an imagined future provider. Reuse existing interfaces and test surfaces.

A vertical slice delivers a thin behavior through the layers needed to demonstrate it.
Avoid separate “all database”, “all backend”, “all UI” tickets that are useless alone.
Begin with one thin end-to-end slice when integration is uncertain; it may establish
the contract that unlocks independent sibling features. Parallelize those siblings,
not tasks that are still negotiating the same interface. A substrate/refactor slice
is valid when its observable acceptance and downstream purpose are explicit.

For broad migrations, use expand–migrate–contract: add the compatible new interface;
migrate independent caller groups; remove the old form after all consumers are verified.
Keep each step green when possible. If only a combined integration can be verified,
say so and treat the group as one atomic slice or define explicit integration evidence;
never mark broken intermediate work verified just to unlock more workers.

## Testing within a slice

Name the observable test surface in the plan, what it catches, and what remains outside
its coverage. For changed behavior, use one focused failing behavior test, implement
the smallest working change, then repeat. Verify that failure is due to missing behavior,
not a broken fixture. Fix the behavior, not the assertion. Use expected values from
the spec or an independent worked example, not the same calculation as the implementation.

Test public behavior; mock external boundaries when needed, not private implementation
details. Prefer a real local adapter where practical. Do not bulk-write speculative tests
before learning from the first slice. Run focused tests/type checks while working and
the agreed integrated suite at the end. Reversible text/layout edits do not need
ceremonial tests. Do not claim retroactive test-first work for tests added afterward.

For bugs, reproduce the symptom, narrow the failing path, form a hypothesis, gather
discriminating evidence, fix it, and keep a regression check where useful. Bound retries
and stop when repeated failures show the plan or diagnosis needs to change.

## Review and handoff

Pin the review base and actual diff. Review two distinct questions: does each spec
acceptance item work, and does the change respect repository standards/maintainability?
Keep both conclusions visible so one cannot hide a gap in the other. One read-only
reviewer can cover both; use separate reviewers only when risk/size justifies the tokens.
Prioritize observed regressions and contract mismatches over speculative abstractions.

Handoffs point to spec, decision records, relevant glossary entries, commits/diffs and
check artifacts. Include only the changed facts needed by the next slice. Carry blockers
and failed evidence forward. Share the user's selected terminology instead of repeatedly
explaining the same domain. Record a retrospective only when it yields a concrete,
reusable improvement; do not grow instructions after every routine task.
