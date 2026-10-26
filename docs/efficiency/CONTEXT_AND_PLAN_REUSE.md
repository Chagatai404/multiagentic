# Context and plan reuse: current boundary

E0/E1 measure packets and control configured budgets. E2 dependency-scoped manifests,
durable summary indexes, compact typed dependency handoffs and approved-plan reuse
attestations are deferred. A human-approved plan does not currently satisfy a node's
required planner call. Independent review, digest matching and deterministic checks
remain mandatory.

Current packets include bounded objectives/acceptance, selective configured reference
paths, role handoffs, failure excerpts and relevant diffs. Read-only planner/reviewer
roles execute in independent snapshots and detect mutations. E0 measures the final
adapter request's character and UTF-8 byte counts after path rewriting; these numbers
do not cover the provider's hidden/system/tool context.

The existing in-memory content-hash cache remains opt-in through the engine API and
off by default. It hashes current bounded bytes and keys reuse by workspace, revision,
policy, path and read limit. It stores decoded static references only, not objectives,
full histories, secrets or hidden state. Prior Windows fixture measurements found it
slower. No new durable plaintext context cache or CLI cache switch is introduced.

Future durable reuse must record source hash/revision, policy fingerprint, ownership
and provenance; invalidate edits, renames, branch and policy changes; and keep a
deterministic uncached path. Future planning attestations require human action and
must bind scope, acceptance, revision and interface contracts. They cannot waive
independent review, changed-scope reasoning, required verification or risk escalation.
These are design requirements for E2, not implemented capabilities.
