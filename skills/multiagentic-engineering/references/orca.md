# Orca workspace profile

This profile targets Stably's Orca agent IDE (`stablyai/orca`, onorca.dev). Orca owns
the app workspace and agent sessions; install this package in the underlying agent.
There is no separate Orca JavaScript plugin API assumed by this package.

## Choose one scheduler before execution

Default to one Claude Code or Codex coordinator in an Orca worktree, using that agent's
native subagents. Use its host adapter. Orca can display child-agent activity, but
native subagents need not have separate panes or isolated worktrees. Verify actual
isolation; retain exclusive path ownership in a shared checkout. Do not assume sessions
inside Orca are visible to a separate Codex desktop/IDE session.

For independently visible workers or mixed coding agents, choose Orca-supervised Runs
instead. Orca's orchestration is experimental and must already be enabled/trusted by
the user. Load its official `orchestration` skill and the installed runtime's full guide
before changing state. Use the documented app control bridge; never implement another
process launcher or use `eng` to create workers. The bridge controls the running app;
Orca owns the lifecycle of its installed coding agents.

In either mode, the coordinator schedules and integrates. Worker packets disable all
further delegation, including `mae_dispatch` inside a Pi worker. Use the plan's worker
concurrency (normally 2, at most 3) across the entire run, not separately per provider.
Use one attempt per task by default. Do not race multiple agents on the same work just
because the IDE supports it; independent feature slices are the default.

## Map a plan to Orca-supervised work

1. Inspect runtime connectivity/capabilities and load version-matched guidance. The
   documented discovery calls are `orca status --json` and
   `orca skills get orchestration --full`; resolve the session's actual executable
   using the official Orca skill (including `ORCA_CLI_COMMAND`/platform variants).
   Do not invent mutation flags from memory or use retired `orchestration run` commands.
2. Keep the user-approved spec and JSON plan canonical in the coordinator's integration
   worktree. Run the shared plan validator. Open decisions block worker dispatch;
   represent them as Orca decision gates when appropriate, without resolving user
   choices on the user's behalf. A Run is a namespace, not an automatic scheduler.
3. Create one Run for the plan and map each plan task ID to an Orca task. Launch only
   the validated ready wave. Store returned Run/task/dispatch identifiers, worktree
   path, source revision and later worker/integration commits in the coordinator's
   task evidence. Never infer IDs or reuse completion from a prior dispatch attempt.
4. Prefer distinct Orca child worktrees for writers. Verify each starts from the current
   integration revision containing all verified dependencies. Make committed spec and
   task packet artifacts reachable on that host before dispatch. Project-local skill
   installs must be present in each worktree; global installs belong to the actual
   execution host/account (Windows, WSL and SSH homes are different).
5. Pass one compact packet and relevant reference paths. Workers read local repo
   instructions, implement their slice, and follow Orca's injected completion/heartbeat
   contract. Ask the coordinator about scope changes; do not launch another scheduler.
6. Consume every message in a delivery before acknowledging it. A successful Orca
   worker outcome maps to MAE `completed`, not `verified`. Inspect the correct worker
   diff/commit, integrate serially, run the planned checks, then record verified
   evidence and compute the next ready wave. Never dispatch merely because an Orca
   task is labeled ready if the MAE dependency evidence is still unverified.
7. On interruption, inspect the recorded dispatch and partial edits before retry.
   Stop only the workers this coordinator owns. Follow runtime release/retention
   receipts; preserve worktree changes and evidence. Never reset global orchestration
   state, delete worktrees or close unrelated terminals as routine cleanup.

Keep MAE state coordinator-owned; worktree copies must not start competing schedulers.
After plan changes, reconcile both the digest-bound state and Orca task/dispatch mapping.
If orchestration is unavailable, retain the underlying agent-native mode or execute
sequentially. Report the actual selected mode and limits before starting.

## Verification boundary

This profile is documentation/skill integration with Orca's native control plane.
The initial profile was authored without a live runtime. A later Windows follow-up
exercised a small Codex shared-checkout flow; see `docs/NATIVE_VALIDATION.md` in the
repository. Verify installed skill discovery, child visibility, worktree ancestry,
failure/cancellation recovery and integrated checks in a disposable feature before
relying on a particular desktop/WSL/SSH configuration.
Usage is only the data each agent/Orca actually reports; no cross-provider token or
billing equivalence is assumed.

Official sources: [skills](https://www.onorca.dev/docs/cli/skills),
[orchestration](https://www.onorca.dev/docs/cli/orchestration),
[Codex](https://www.onorca.dev/docs/agents/codex),
[Claude Code](https://www.onorca.dev/docs/agents/claude-code).
