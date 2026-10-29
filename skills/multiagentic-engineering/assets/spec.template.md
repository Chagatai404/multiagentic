# <Feature>: agreed engineering spec

## Problem and scope

User problem, desired behavior, non-goals, constraints. Link existing evidence once.

## Decisions

| ID | Decision | Depends on | Choice / rationale / evidence | Status |
| --- | --- | --- | --- | --- |
| D1 | <material choice> | <none or IDs> | <answer or pending research> | open / resolved / user-deferred |

Use existing glossary terms. Define only necessary new terms. Capture accepted
assumptions and consequences of deferral; no silent default for an unresolved choice.

## Interfaces

Modules and caller-visible inputs/outputs, invariants, errors, ordering, compatibility.
Record consequential tradeoffs; put exact current file ownership in the dispatch JSON.

## Acceptance and verification

| ID | Observable behavior / edge case | Slice | Check and test surface | Coverage limit |
| --- | --- | --- | --- | --- |
| AC1 | <user-visible result> | <task ID> | <existing test command or manual procedure> | <what it cannot prove> |

## Delivery graph

Thin end-to-end slice if needed, independent sibling slices, genuine dependencies,
shared-file owner, integration order, worker/context/attempt budget. Explain why the
chosen concurrency pays for its additional context.

## Risks and recovery

Open decisions/research that block implementation, rollback, interrupted-work handling,
deferred limitations and actual user authorization. Record agreement without inventing it.
