# Multiagentic engineering

Plan with your coding agent, split independent work, and coordinate native workers
inside your existing Claude Code, Codex, OpenCode or Pi session.

The plugin owns the workflow: **clarify → agree interfaces → plan dependencies →
run independent slices → integrate → verify**. Your host owns the model, credentials,
tools and session. Planning decisions stay with you. There is no external agent
launcher in the plugin path.

## Start in your agent

> Use multiagentic-engineering to plan this feature with me. Inspect the code first,
> identify the decisions I need to make, then propose independent slices with file
> ownership, dependencies and acceptance checks. Keep worker context small. Wait for
> me to approve the plan before implementation.

After reviewing the plan:

> Execute this plan using native agents. Keep shared files under one owner and verify
> the combined change before calling it done.

Ordinary substantial coding requests can also trigger the installed skill automatically;
selection depends on the host/model. Explicit invocation is the reliable entry point.
Small or tightly coupled work stays with one agent when parallelism adds overhead.

## Install

These are one-time package installation steps, not a runtime agent-spawning CLI.
See [host-specific setup and migration](docs/NATIVE_PLUGINS.md) for app support,
preview-branch installation and capability limits.

| Host | Package / entry point | Worker execution |
| --- | --- | --- |
| Claude Code | Marketplace plugin; `/multiagentic-engineering:multiagentic-engineering` | Native Agent tool, worker/reviewer definitions |
| Codex | Repo marketplace plugin; `$multiagentic-engineering` | Native collaboration tools when exposed |
| OpenCode | Native JavaScript plugin; `/mae` | Native Task/subagent tools |
| Pi 1.4 SDK | Pi package; `/mae` | In-process SDK child sessions via `mae_dispatch` |
| Other Agent Skills hosts | Copy/install the shared skills | Native delegation if available; otherwise sequential |

Claude Code, in its session:

```text
/plugin marketplace add Chagatai404/multiagentic-engineering
/plugin install multiagentic-engineering@multiagentic-engineering
```

Codex: add this repository as a marketplace using its plugin browser or:

```sh
codex plugin marketplace add Chagatai404/multiagentic-engineering
```

Then install `multiagentic-engineering` from that marketplace in `/plugins` or the
app's Plugins Directory. This is a repository plugin, not a published universal listing.
If your surface does not support local/repo marketplaces, use the skill-only option.

Pi:

```sh
pi install git:github.com/Chagatai404/multiagentic-engineering
```

For OpenCode, clone the repo, run `npm install --omit=dev --ignore-scripts` inside it,
and add the absolute `file:///.../adapters/opencode/index.mjs` URL to the `plugin`
array in your existing `opencode.json`. Preserve other settings. The plugin registers
its skills, `/mae`, `mae_plan` and worker/reviewer agents in memory.

## Thorough plans, bounded context

The agent writes a decision-complete `.plans/<topic>.md` and a compact JSON dispatch
plan. Unresolved decisions block dispatch. Each slice delivers a narrow verifiable
behavior across the necessary layers and specifies objective, read pointers, exclusive write ownership,
interfaces, dependencies, acceptance and checks. The validator rejects cycles,
unknown dependencies and unordered write/write or read/write overlap.

Only verified dependencies unlock a consumer. A worker report is not verification.
The coordinator integrates serially, checks real changes, and runs acceptance checks.
Plan changes invalidate saved dispatch state. Interrupted work is inspected before retry.

Default example: two workers, at most three, a 6,000-character packet, a 1,200-character
handoff and one attempt per worker. These are adjustable context/attempt limits, not
hard token or spending caps. Worker context excludes sibling transcripts and unrelated
skills. Parallelism can reduce elapsed time while increasing total tokens; no measured
savings are claimed yet.

## Skills from JMO and Matt Pocock

The shared **interview** combines [JMO](https://github.com/23jmo/jmo-skills)'s project
spec interview with [Matt Pocock](https://github.com/mattpocock/skills)'s decision-tree
questioning, terminology and design decisions. Matt's vertical slicing, behavior tests,
and spec/standards review also shape the engineering workflow. **ste** retains JMO's
clear technical writing guide. See [source selection and adaptations](docs/SKILL_SOURCES.md).
Optional UI work can use its `better-ui` and `animate` skills separately. We do not load
them into every engineering worker. Its Codex CLI handoff is excluded from this workflow.
See [third-party notices](THIRD_PARTY_NOTICES.md).

## Status and development

Native plugins are **2.0.0-beta.1**. [Validation evidence](docs/NATIVE_VALIDATION.md) covers planning, bounded dispatch,
recovery, file guards, adapter registration and packaging. Live end-to-end execution
inside the four client apps is not yet certified. An installable plugin cannot add
native spawning tools to a host surface that does not expose them.

```sh
npm ci --ignore-scripts
npm test
npm run check
npm run check:package
```

The Python `eng` 1.1 runner is retained for existing users and historical evidence.
It is not needed by any native plugin. [Migration](docs/NATIVE_PLUGINS.md#migrate-from-eng)
explains how to remove old prompt-routing hooks so they do not intercept native work.
[Legacy CLI guide](https://github.com/Chagatai404/multiagentic-engineering/blob/main/LEGACY_CLI.md) documents that optional runner.
