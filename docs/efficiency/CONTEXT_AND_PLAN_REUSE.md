# Context and plan reuse (E2)

Decision record: [ADR-002](ADR-002.md). Independent review, digest matching,
deterministic checks, task approval and ownership remain mandatory in every mode.

## Packets

Packets include bounded objectives/acceptance, selective configured reference paths,
role handoffs, failure excerpts and relevant diffs. Read-only planner/reviewer roles
execute in independent snapshots and detect mutations. E0 measures the final adapter
request's character and UTF-8 byte counts after path rewriting; these numbers do not
cover the provider's hidden/system/tool context. E2 adds two optional sections, both
absent on the uncached path: the node's interface contracts and, with
`context_reuse`, compact handoffs from its direct dependencies (≤1500 characters each).

## Dependency handoffs and the summary index

Every integrated plan node records a digest-bound `DependencyHandoff` on the plan
record (`eng plan status PLAN_ID` shows it). With `context_reuse: true`, a dependent
node's launch validates each direct dependency's handoff (digest, verification-policy
fingerprint, integrated commit in the launch revision), marks files changed again
since integration as stale, omits anything that fails, and writes a `context_manifest`
plan event describing what was reused. Handoffs name changed files; roles read current
content from their worktree. No file content, secrets or full histories are stored.

## Attested planning

A complex node normally spends one planner call. A human can attest that a node's own
spec is its plan:

```sh
eng plan create plan.yaml -p .
eng plan attest PLAN_ID api cli -p .     # or --all for every unlaunched, non-high-risk node
eng plan attest PLAN_ID cli --revoke -p .
eng plan run PLAN_ID -p .
```

The attestation binds node scope, verification policy and the integration revision.
It is invalidated (event `attestation_invalidated`, model planner runs) when the
scope or policy changes, the revision is no longer an ancestor, or any path the node
owns changed since attestation, including by a dependency. The engine also rejects it
(event `attestation_rejected`) when the task does not match or classifies high risk.
Only the initial planner step is replaced; changed-scope planning, review and checks
still run. `eng plan preview` reads a plan file before any attestation exists, so it
still counts the planner call.

## Cache

The existing in-memory content-hash cache remains opt-in through the engine API and
off by default. It hashes current bounded bytes and keys reuse by workspace, revision,
policy, path and read limit. Prior Windows fixture measurements found it slower. E2
adds no durable plaintext content cache and no CLI cache switch.

## Not established

Offline fixtures show fewer planner invocations and delivered handoffs. They do not
show real token, cost or quality effects; those need the owner-authorized live
protocol in [BENCHMARKS.md](BENCHMARKS.md).
