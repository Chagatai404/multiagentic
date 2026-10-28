# Skill selection and adaptations

The native workflow combines both requested skill repositories. We keep one interview
and one engineering coordinator, so source overlap does not create repeated questions
or two competing task systems. Source revisions and licenses are pinned in `UPSTREAM.json`.

## Sources

- [23jmo/jmo-skills at 6082bf2](https://github.com/23jmo/jmo-skills/tree/6082bf2c472857d6cfda48995ab985b69345aac6)
- [mattpocock/skills at 59db609](https://github.com/mattpocock/skills/tree/59db609eb1e18aaf59b63284d0e52255aff0c63c)

| Source skill | Useful practice | Where it lands |
| --- | --- | --- |
| JMO `skills/interview` | In-depth implementation/UX/tradeoff interview; project-local spec | Shared `interview` skill and `.plans/` spec |
| JMO `skills/ste` | Precise technical communication | Unchanged `ste`, loaded only when needed |
| Matt `skills/productivity/grilling` | Decisions form a dependency tree; ask only ready questions; research facts yourself | Interview decision table and bounded question rounds |
| Matt `skills/engineering/grill-with-docs`, `domain-modeling` | Clarify shared terminology; record consequential decisions | Interview glossary/decision guidance |
| Matt `skills/engineering/to-spec` | Synthesize settled conversation; define observable test surfaces | Spec template and acceptance-to-check mapping |
| Matt `skills/engineering/to-tickets` | Small verifiable vertical slices; explicit blockers; expand–contract migrations | Planning rules and end-to-end feature example |
| Matt `skills/engineering/implement-spec` | Work the ready task graph; communicate with context pointers | Native waves and compact dependency handoffs |
| Matt `skills/engineering/codebase-design` | Small interfaces hiding meaningful behavior; real variation before abstraction | On-demand engineering reference |
| Matt `skills/engineering/tdd`, `implement` | Behavior tests through public interfaces; short feedback cycles | Worker test policy and focused/integrated checks |
| Matt `skills/engineering/code-review` | Spec coverage and standards are separate review questions | Two-part final review; extra reviewers only when justified |
| Matt `skills/productivity/writing-for-agents`, `handoff` | Conditional context pointers; clear completion criteria; reference existing artifacts | Lazy references, compact packets, explicit states and handoffs |

## The resulting workflow

1. Inspect facts and reuse the user's existing plan.
2. Interview in dependency order. Record decisions and terminology as they settle.
3. Synthesize one spec with acceptance IDs and intended test surfaces. Keep unresolved
   decisions explicit; the deterministic dispatcher refuses plans that retain them.
4. Propose small end-to-end behaviors, dependencies, exact ownership and budgets.
   Establish a shared contract first when it is not already stable. Let the user
   correct scope, granularity and dependencies before co-planned implementation.
5. Dispatch the ready independent slices through native tools. Workers read narrow
   pointers and relevant dependency results, not a full conversation or skill catalog.
6. Test changed behavior incrementally. Integrate serially and verify actual outcomes.
7. Review spec coverage and code standards separately. Preserve evidence and blockers;
   retry only after a concrete diagnosis, within the plan's attempt ceiling.

## Deliberate adaptations

- Use small rounds of ready questions to control cognitive load. Keep dependent
  questions for later. A silent/ambiguous answer never resolves a decision.
- The user's already-settled choices remain settled; specification is synthesis,
  not an automatic second interview. Explicit deferrals record limits instead of
  disappearing into assumptions.
- A vertical slice is preferred, not an excuse for shared writes. Introduce a contract
  task or serialize work when independence cannot be demonstrated.
- File ownership belongs in the current dispatch plan even when a long-lived product
  spec avoids volatile paths. Recheck it against the inspected revision.
- Keep tracker publication optional and separately authorized. Do not create issues,
  apply labels, close tickets, reset worktrees or delete branches as a side effect of
  loading these adapted skills.
- Use the host's native agents and existing permissions. Do not import JMO's Codex CLI
  handoff or an external agent launcher. Do not require another plugin's setup wizard.
- Retain bounded concurrency and proportionate review. Maximum throughput is not the
  same as minimum tokens. No mandatory planner, researcher, merger and dual-reviewer
  swarm for every task.
- Agree verification in the plan and use meaningful behavior tests. Do not require a
  new user approval for every existing test or add tests to trivial text edits.

JMO's `better-ui` and `animate` remain optional for relevant UI work. Its `agentation`
license/runtime and third-party MCP connections are not pulled into the core package.
Matt's whole tracker, productivity and architecture-survey catalog is not auto-loaded.
