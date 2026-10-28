# Orca as the primary workspace

Target: [Stably Orca](https://www.onorca.dev/docs), the agent IDE from
[stablyai/orca](https://github.com/stablyai/orca). This is the preferred workspace for
this project. Claude Code/Codex/OpenCode/Pi support remains portable underneath it.

## Recommended first setup

1. Open your project in Orca. Start Claude Code or Codex using the app's agent picker
   in one integration worktree. Use the account you want for this project.
2. Install this repository's plugin in that agent using
   [the native installation guide](NATIVE_PLUGINS.md). Orca's Skills view can also
   discover standard Agent Skills. Avoid installing duplicate plugin and skill copies.
3. Ask: “Use multiagentic-engineering in Orca. Interview me about unresolved choices,
   reuse my existing decisions, and propose independently verifiable slices. Wait
   for my approval before implementation. Use two workers unless three clearly helps.”
4. Review the spec, acceptance checks, exact ownership and dependency graph in the
   project. Keep one coordinator responsible for user decisions and integration.
5. Begin with the underlying agent's native subagents. This is the least additional
   setup. Orca can expose native child activity; a child row is not a guarantee of a
   separate worktree or terminal. Verify isolation before concurrent edits.

The package never asks you to operate an external `eng` runner. Orca itself hosts
installed coding agents; that implementation detail does not change the in-app workflow.

## When to use Orca-supervised workers

Choose Orca's orchestration when you want independently visible worktree workers or
different coding agents on different slices. Its orchestration is currently experimental;
enable it deliberately in Orca Settings and install/activate the official `orchestration`
skill. It controls Runs, tasks, worker dispatches, messages and decision gates through
the running app. The current commands and flags come from the installed runtime's
`orca skills get orchestration --full` guide.

Use the [Orca workflow profile](../skills/multiagentic-engineering/references/orca.md)
for mapping and recovery. This is an integration through documented skills and app
controls, not a fabricated Orca plugin manifest or a new standalone scheduler.

| Concern | Underlying native subagents | Orca-supervised tasks |
| --- | --- | --- |
| Coordinator | Your selected coding agent | Same selected agent, controlling one Orca Run |
| Worker lifecycle | Agent's native tools | Orca supervised dispatches |
| Isolation | Confirm actual native behavior | Prefer distinct child worktrees from integration revision |
| Skills | Selected agent's plugin/skills | Ensure every chosen agent and execution host can load its packet/skills |
| Scheduling | Shared MAE plan and native tools | Same plan, mapped to Orca task/dispatch IDs |
| Verification | Coordinator inspects and tests | Same; Orca completed is not MAE verified |
| Recursion | Workers do not delegate | Workers do not spawn native subagents or another Orca Run |

Use only one scheduling mode for the same work. The concurrency limit applies across
all its workers, including mixed providers. One coordinator plus two workers is the
initial layout; allow a third worker only for a genuinely independent slice. Keep
backend/API/UI layers together when they implement one behavior; establish shared
contracts first, then parallelize independent features.

## Context and worktrees

Keep `.plans/` authoritative in the coordinator's integration worktree. Commit or
otherwise make the approved spec and packet artifacts reachable before creating remote
or child workers. Each worker must start with the integrated dependencies and a compact
packet: objective, acceptance, owned/read paths, interfaces and relevant handoffs.
Do not send a full interview transcript or sibling histories to every agent.

For Orca-supervised work record the Run ID, plan-to-task mapping, dispatch attempt,
worktree path, base revision, result commit and verified integration commit. Check
that completion belongs to the active attempt. Merge serially and run combined checks;
only verified results unlock the next wave. Preserve partial edits after cancellation.
Do not reset runtime-global orchestration state to fix one plan.

On Windows, choose whether the agent runs on the host or in WSL; install its plugin
in that actual environment and active account home. SSH workers similarly require
their own reachable tools and skills. Orca's Codex account/server isolation can affect
visibility and continuation from other IDEs; do not promise cross-app resume based on
the fact that both sessions are called Codex. Consult the current Orca Codex guide.

## Orca acceptance plan

Before claiming live support for your setup:

1. Confirm all three bundled skills are discoverable in the selected agent/account.
2. Co-plan a disposable feature. Verify that unresolved choices block dispatch.
3. Run two independent slices, with the chosen scheduler as sole lifecycle owner.
4. Confirm worktree bases, owned files and dependencies match the approved plan.
5. Simulate a failed check and a cancellation. Verify no consumer starts early and
   recovery inspects the existing attempt rather than duplicating it.
6. Integrate and run acceptance checks. Record actual client/runtime versions, worker
   counts, elapsed time and available usage. Compare equivalent single-agent work
   before claiming a token or speed improvement.

Current evidence: profile and packet integration are implemented; no Orca app/runtime
is available in this build environment, so live Orca execution remains unverified.

## Official references checked 2026-10-28

- [Orca model](https://www.onorca.dev/docs)
- [Skills registry](https://www.onorca.dev/docs/cli/skills)
- [Orchestration](https://www.onorca.dev/docs/cli/orchestration)
- [Codex in Orca](https://www.onorca.dev/docs/agents/codex)
- [Claude Code in Orca](https://www.onorca.dev/docs/agents/claude-code)
