# Host adapters

Read only the applicable row and section. Installation does not guarantee that a
particular IDE/app/account exposes delegation. Report absent tools and use sequential
execution; never emulate native tools with a coding CLI subprocess.

| Host | Entry | Delegation |
| --- | --- | --- |
| Orca (preferred workspace) | Install this plugin in the selected Claude/Codex agent, or install its skills | Choose underlying native subagents or Orca-supervised tasks; [Orca profile](orca.md) |
| Claude Code | Installed plugin skill; `/multiagentic-engineering:multiagentic-engineering` | Native Agent tool and bundled mae-worker/mae-reviewer definitions |
| Codex / compatible ChatGPT surfaces | Installed plugin or `$multiagentic-engineering` | Session's native spawn/wait/message tools, when available |
| OpenCode | Loaded skill or `/mae` | Native Task/subagent tool with mae-worker; `mae_plan` prepares packets |
| Pi | `/skill:multiagentic-engineering` or `/mae` | Bundled `mae_dispatch` uses in-process SDK sessions |
| Other Agent Skills hosts | Explicit or automatic skill selection | Discover capabilities; sequential fallback |

## Claude Code

Use the native Agent tool with the worker/reviewer available under this plugin's
namespace. Send only a packet; do not preload all skills. Respect inherited permissions.
Use native worktree isolation if available and useful; otherwise disjoint shared writes.
Read-only reviewer reports findings to the coordinator. It must not apply fixes.

## Codex

Use the session's actual collaboration API, not a hardcoded tool signature. Prefer
fresh child context (`fork_context: false` or equivalent when offered). Pass repository
and packet paths plus task-local instructions. Reuse/close native child sessions as
the host supports. The portable skill works without installing custom agent TOMLs.
Do not modify global configuration or increase account/model permissions.

## OpenCode

The plugin adds `mae_plan` and worker/reviewer definitions through native configuration.
Use the current host's native Task/subagent tool. Tool naming differs between versions;
use the advertised interface. Worker/reviewer prompts prohibit recursive delegation.
Parent owns integration/check execution. Honor OpenCode's permission prompts. The
plugin does not use a detached server, spawn a CLI, or patch user config on disk.

## Pi

The extension provides `/mae`, `/mae-approve`, `mae_plan` and `mae_dispatch`. Ask the
user to run `/mae-approve .plans/<slug>.json` after reviewing a plan when dispatch is
needed. That command binds their authorization to the plan digest. The model cannot
invoke it through a registered tool. Direct file editing is not a security boundary;
never synthesize authorization yourself. Editing the plan invalidates authorization.

Call `mae_dispatch` for the next ready wave. Workers use the parent's model and fresh
SDK sessions, no extension/tool recursion, and narrow file tools; they cannot run shell
checks. Parent verifies edits and runs checks. Default Pi stored credentials must
support the selected model; custom parent-only auth/providers may need setup.
Review-only workers have no write tools. Cancellation/timeout preserves partial work
as blocked. The coordinator updates verified state after checks. Do not auto-retry a
blocked/interrupted task. This integration targets Pi's documented 1.4 SDK; older
`@mariozechner` builds can use the skill-only fallback until upgraded.
