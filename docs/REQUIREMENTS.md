# M0/M1 requirements and acceptance

Build a local, provider-independent single-agent vertical slice. Correctness precedes
elapsed time, tokens/cost, architecture, portability, extensibility and observability.
Optimize accepted verified work, not the cost of individual invocations.

Acceptance: installable Python 3.12+ package; useful Typer CLI; typed task/project/provider/
verification contracts; explicit state machine; transactional SQLite persistence and
migrations; real/fake provider invocation; controlled Git worktrees; bounded context;
real project checks and stored evidence; cancellation; conservative checkpoints;
unit/contract/disposable-repository end-to-end coverage. No completion from provider
confidence alone. No automatic source-branch edits or integration.

M1 uses a single workflow. All roles and future states are represented as contracts;
adaptive multi-agent behavior is not operational. Model APIs, direct tool loops, role
registration, strict dollar/turn/tool budgets, and parallel integration are future work.

Performance claims require measured evidence. Offline acceptance measures a seeded
bug, baseline failing check, fixture edit, passing check, elapsed time and process-boundary
inspection. FakeProvider reports unknown token/cost data. Live runs are opt-in and must
report failures honestly. Do not compare the offline fixture to model-based performance.
