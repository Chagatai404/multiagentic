# Third-party notices

The `interview` skill is adapted from Johnathan Mo's jmo-skills interview. `ste` is
an unchanged snapshot from the same repository. Both are MIT licensed; full upstream
copyright and permission notices are included in each skill's LICENSE.

Source: https://github.com/23jmo/jmo-skills
Pinned revision: 6082bf2c472857d6cfda48995ab985b69345aac6

Changes to interview: host-neutral questioning, bounded clarification, canonical spec,
reuse of user decisions, and handoff to native parallel planning.

Optional UI skills (`better-ui`, `animate`) remain in their upstream package and are
not bundled. Install only when needed. The `codex` subprocess handoff and `agentation`
(with its separate PolyForm Shield license) are not included. No third-party service
or MCP credentials are bundled.

## Matt Pocock's Skills For Real Engineers

Source: https://github.com/mattpocock/skills
Pinned revision: 59db609eb1e18aaf59b63284d0e52255aff0c63c
License: MIT, copyright (c) 2026 Matt Pocock. The complete notice is retained in
`skills/interview/LICENSE` and `skills/multiagentic-engineering/LICENSE`.

Adapted practices: dependency-ordered grilling, domain terminology and consequential
decisions, spec synthesis, vertical slicing, ready-task graphs, compact context pointers,
small interfaces, behavioral tests, spec/standards review and reference-based handoffs.
Exact inspected source skill paths and integration choices are in
[SKILL_SOURCES.md](docs/SKILL_SOURCES.md). These are concise adaptations, not an unchanged
copy or an installation of the whole upstream workflow.
