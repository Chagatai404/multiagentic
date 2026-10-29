---
name: interview
description: Co-plan an engineering project with the user and write a decision-complete implementation spec. Use when requirements, interfaces, acceptance, UX or tradeoffs need clarification before work can be split.
---

# Interview and specify

Combine JMO's project interview/spec handoff with Matt Pocock's dependency-ordered
grilling and domain modeling. Reuse the user's plan and settled decisions.

1. Inspect relevant code, tests, glossary and architectural decisions. Look up facts
   yourself; ask the user for choices. Delegate exploration only when it saves time
   and the host supports it. An unfinished lookup remains an open prerequisite.
2. Keep a small decision table in the spec: question, prerequisites, chosen answer,
   rationale/evidence, status. Separate confirmed facts, proposals and accepted
   assumptions. Identify behavior, constraints, interfaces, failure cases and test
   surfaces that need a choice. Challenge contradictions between the code and intent.
3. Ask a small round of independent, ready questions (normally 1–3). Give options,
   tradeoffs and a recommended answer. A dependent question belongs to the next round.
   Make a specific recommendation so an unambiguous yes can accept it; never interpret
   silence or an ambiguous yes to several questions as approval of all choices.
4. After each reply, update the decision table and recompute what can be asked next.
   Stress-test decisions with concrete failure/edge scenarios. Clarify overloaded
   terms using the existing glossary. Capture a small definition only when needed;
   propose an architectural decision record only for a consequential, nonobvious tradeoff.
5. Finish when each material decision is resolved or explicitly deferred by the user
   with scope/impact recorded, and no investigation still blocks the chosen design.
   Include relevant deferred limitations in acceptance/non-goals. During collaborative
   planning, summarize the agreement and obtain confirmation before implementation.

Save `.plans/<topic>-spec.md` in the current project: user problem, goals/non-goals,
behavior and acceptance IDs, decisions, interfaces (including errors/invariants),
test surfaces, risks, unresolved decisions and rollback. Synthesize what is already
known; do not run another interview just to write the spec. Keep detailed file ownership
in the dispatch plan, where it can be rechecked against the current checkout.

Hand this spec to multiagentic-engineering for independent slices. Keep one planning
conversation, not one interview per worker. Load `ste` only when explanations need it.
