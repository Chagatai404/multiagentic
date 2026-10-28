# Native plugin guide

The selected workspace is **Orca**. Start with [ORCA.md](ORCA.md), then install the
appropriate underlying agent package below. The Orca profile defines native-subagent
and Orca-supervised modes without introducing an external launcher.

## Design decisions

| Decision | Reason |
| --- | --- |
| One shared skill and plan contract | Keep behavior consistent across hosts without copying instructions |
| Human spec before worker packets | Let the user shape scope, interfaces and acceptance before parallel work |
| Native host tools, Pi SDK extension | Keep work inside the existing app/session; no external agent runner |
| Exclusive writes and dependency-aware reads | Prevent concurrent edits and readers consuming an unfinished interface |
| Two workers by default, maximum three | Bound duplicated context and integration overhead |
| Compact reference-based packets | Avoid full-history forks and repeated repository ingestion |
| Completed and verified are different states | Require real integrated evidence before downstream work |
| No default MCP or lifecycle hooks | Avoid extra startup/context cost and interception of ordinary prompts |
| Keep eng 1.x as explicit legacy | Preserve existing users' work while replacing the primary experience |

The combined interview and engineering practices come from both JMO and Matt Pocock;
see [source selection and adaptations](SKILL_SOURCES.md). Their overlap is consolidated
into one planning flow with explicit acceptance coverage and open-decision gates.

## Installation and preview branches

Install from a reviewed checkout when evaluating the PR before it is merged. Use
`feat/native-agent-workflows` as the preview branch for this change; `main` remains the
previous release until a maintainer merges it.

Claude Code: add the absolute checkout path with `/plugin marketplace add /path/to/checkout`,
then `/plugin install multiagentic-engineering@multiagentic-engineering`. The same
marketplace supports normal GitHub installation after merge. The package supplies the
skill plus `mae-worker` and `mae-reviewer`; exact names in the Agent menu may include
the plugin namespace. Follow the client's normal activation/reload instructions.

Codex: `codex plugin marketplace add Chagatai404/multiagentic-engineering --ref feat/native-agent-workflows`,
then select the plugin in `/plugins`. A local checkout can also be added by path.
The root Agent Plugins manifest and `.codex-plugin/plugin.json` compatibility manifest
point at the same skills. Repo marketplace support and native subagents vary by app,
IDE extension, managed policy and account. This package is not a universal-directory
publication. It does not turn a chat surface without subagents into one with them.

For local development installs, use a clean archive of the reviewed commit as the
marketplace source. The tested Codex 0.164 local installer copied ignored files
from the source directory, including `.venv`, `node_modules`, logs and Git metadata.
`git archive` includes only committed files and avoids carrying that development
state into plugin caches. For example, create an unused staging directory, run
`git archive --format=tar --output=/path/to/preview.tar HEAD`, extract it there, and
add that staging directory to the local marketplace. Keep the directory available
while registered; refresh from a newly reviewed commit when updating the plugin.
The Codex/Claude skill path needs no npm or Python environment in that archive.

Pi: use `pi install /absolute/path/to/reviewed/checkout` for a local preview, or install
the Git source after merge. Requires Node 22.19+ and the Pi 1.4 SDK package family
`@earendil-works/pi-coding-agent` and its host-provided `typebox`. Older
`@mariozechner/pi-coding-agent` versions are not binary-compatible with this adapter;
use the skill-only installation there. Start with `/mae <goal>`, review the saved plan,
then run `/mae-approve .plans/<name>.json` and ask the agent to execute it. Approval is
per plan digest; a materially changed plan needs review again.

OpenCode: in the reviewed checkout run `npm install --omit=dev --ignore-scripts`. Merge
this entry into the existing configuration; use an absolute file URL for your OS:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["file:///absolute/path/to/multiagentic-engineering/adapters/opencode/index.mjs"]
}
```

On Windows the URL is `file:///C:/path/to/multiagentic-engineering/adapters/opencode/index.mjs`.
URL-encode spaces in file URLs. The adapter is checked against `@opencode-ai/plugin`
1.19.5. Its config hook adds the absolute skills directory and native worker/reviewer
agents only if those names do not already exist. It does not overwrite config files.
Run `/mae <goal>` or ask for the skill; use `mae_plan` to obtain validated packets, then
the native Task/subagent interface to dispatch them. Review permissions through the
host. Later OpenCode API generations may need adapter updates.

## Skill-only hosts

Copy the full `skills/multiagentic-engineering`, `skills/interview` and `skills/ste`
directories into the host's discovered Agent Skills directory. Codex supports
`.agents/skills/`; Claude Code supports `.claude/skills/`; OpenCode supports
`.opencode/skills/`; Pi supports `.pi/skills/` at project scope. Keep each entire
folder, including references, scripts and licenses. Do not install a second copy if
the plugin already supplies it. Other hosts can load the standard SKILL.md format
where supported. No unsupported native plugin manifest is claimed for them.

Skill metadata is the small always-visible routing surface. The main instructions
load only when selected; reference files and optional JMO UI skills load only for
relevant work. With no native delegation tool, the same plan executes sequentially.
With no Node 20+ runtime, the skill can check the planning rules manually but must
say the deterministic helper was unavailable.

## Planning and token policy

The user and coordinator agree one spec. A task must be independently implementable
from its packet. Interface discovery belongs before consumers; shared files and
lockfiles have one owner. No task should merely say “do the backend” without behavior,
owned paths and verification. See the bundled example and planning reference.

Measure packet characters and number of workers deterministically. Actual model input,
output, cache usage and monetary cost stay unknown unless reported by the host. SDK
statistics retain Pi's native meaning and are not a cross-provider billing measure.
Use one worker for short/coupled tasks. Parallelize only when saved elapsed time is
worth duplicated context; prefer a stronger planning pass over repeated worker replans.
A thorough plan aims to remove ambiguity, not maximize document length.

## Verification, state and recovery

The JSON helper validates structure, graph, ownership and state; it never runs checks
or attests user approval. `.plans/<name>.state.json` is a local coordinator record.
All hosts use only verified dependencies. Running/blocked work stops further waves.
Completed workers need actual diff inspection and required checks before `verified`.
State edits are a protocol action by the coordinator; they are not proof that a test ran.

Pi adds a project-wide dispatch lock and durable running state. A process crash leaves
an unknown outcome and may leave the lock. Inspect workers, files and evidence before
manually removing `.plans/.mae-dispatch.lock`. If a retry is appropriate, preserve
attempts/evidence and change that task to `pending`; dispatch requires attempts below
the plan ceiling. If the ceiling or task scope changes, revise/review the plan and
explicitly reconcile state with the new digest. Never discard old evidence silently.

Pi workers have read/search and ownership-checked edit/write tools. Parent handles
shell checks, deletion/renames and integration. They do not inherit arbitrary parent
extensions, custom provider registrations or ephemeral API keys. Credentials come from
Pi's normal stored auth. Custom-provider failures are surfaced, not silently replaced
with another model. SDK sessions are in-memory: after a crash, inspect files and the
saved dispatch state; no child transcript resume is promised. Other hosts retain
whatever native child-session persistence they expose.

File guards and local approval records are not OS sandboxes or tamper-proof security
boundaries. Claude/Codex/OpenCode ownership is enforced by the coordinator protocol,
not by Pi's tool wrappers. All hosts retain their own permissions. No plugin enables
permission bypass, push, deployment or destructive cleanup automatically.

## Migrate from eng

Old prompt hooks can intercept a request before the native skill sees it. Remove only
the old managed integration using the existing installation, for the scopes you used:

```sh
eng uninstall --scope user
eng uninstall --scope project -p /path/to/project
```

Check `eng uninstall --help` on your installed version. It removes managed prompt hooks
and the old managed skill; it does not delete worktrees or historical task evidence.
If you installed separate Git verification hooks, decide separately whether to retain
those; they are unrelated to native skill discovery. Finish or cancel active legacy
work before moving the same task to a native plan. Preserve `.engineering/` records.
Install the native plugin after removal. Do not run both workflows for the same task.

The old `eng install`, `eng trigger`, MCP submit and provider adapters remain explicitly
legacy. Native plugins neither invoke them nor inherit their CLI-only approval gates.
Python package version remains 1.1.0; native manifests use 2.0.0-beta.1. Existing release
automation still concerns the Python package; this branch does not publish a release.

## Evidence and outstanding smoke checks

Automated offline checks cover DAG/ownership/read hazards, packet limits, state digests,
readiness, authorization, concurrency, cancellation, timeout, retained failures, locks,
symlink writes, OpenCode registration, Pi SDK type/registration compatibility and package
contents. A fresh-context planning exercise checks co-planning and shared-file handling.
The legacy Python regression suite remains part of CI.

Before declaring a stable release, run this in each real client surface:

1. Install from a reviewed checkout; verify discovery of the three skills.
2. Co-plan a disposable feature and inspect the DAG and decisions before approving.
3. Execute two disjoint edits; confirm native child visibility and no agent CLI subprocess.
4. Check a shared-file conflict is rejected and a failed check blocks a dependent slice.
5. Cancel during work, inspect retained edits, and resume without duplicate execution.
6. Verify integrated output and record versions, timing, actual usage coverage and limits.

No live model calls, host end-to-end certifications or token savings are implied by
the offline tests. Host CLI validators may be unavailable in a build environment.

## Official references checked 2026-10-28

- [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Claude plugin manifest](https://code.claude.com/docs/en/plugins-reference)
- [Claude subagents](https://code.claude.com/docs/en/sub-agents)
- [OpenCode plugins](https://docs.opencode.ai/docs/plugins/)
- [OpenCode agents](https://docs.opencode.ai/docs/agents/)
- [OpenCode skills](https://docs.opencode.ai/docs/skills/)
- [Pi SDK](https://github.com/earendil-works/pi/blob/2eb6a8d15ff038d0ac9565f760720e5bec9b4a3e/packages/coding-agent/docs/sdk.md)
- [Pi packages](https://github.com/earendil-works/pi/blob/2eb6a8d15ff038d0ac9565f760720e5bec9b4a3e/packages/coding-agent/docs/packages.md)
