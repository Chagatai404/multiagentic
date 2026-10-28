> Legacy `eng` prompt-routing setup. For native in-session plugins use
> [NATIVE_PLUGINS.md](NATIVE_PLUGINS.md). Do not install these routing hooks for the
> native workflow; remove existing ones during migration.

# Client installation and prompt routing

The [README quickstart](../LEGACY_CLI.md#quickstart-install-once-for-your-user) covers
package installation and project checks. The installer defaults to the current OS user:

```sh
eng install
eng hooks status claude-code --scope user
eng hooks status codex --scope user
eng hooks status gemini --scope user
eng hooks status cursor --scope user
```

No repository is needed to install user-wide. The installer writes native hooks for all
supported clients, even if a client is installed later. It also copies the portable
`multiagentic-engineering` skill into `~/.agents/skills/`, `~/.claude/skills/` and
`~/.copilot/skills/`. These are local files; remote hosts and other accounts need their
own setup. `CLAUDE_CONFIG_DIR` and `CODEX_HOME` redirect their respective client settings.

Restart clients after installation. In Codex, open `/hooks` and review/trust the eng
entry; changed hook definitions need review again. No trust or permission bypass is
installed. In Copilot, `/skills reload` refreshes skills and `/multiagentic-engineering`
selects the workflow explicitly. Otherwise skill selection follows the client's normal
model-driven discovery. Gemini, Cursor and other skills-compatible clients can discover
the shared `~/.agents/skills/` copy. Unknown clients receive no fabricated native hook.

## Project-wide installation

```sh
eng install --scope project -p /absolute/path/to/repo
```

This installs hooks and skills under that repository, bound to its root. Skills go in
`.agents/skills/`, `.claude/skills/` and `.github/skills/`. Generated files are excluded
through `.git/info/exclude`, keeping the checkout clean. Installation neither initializes
a project nor confirms checks. Each repository still needs `eng init`, meaningful
confirmed required checks and committed configuration.

Existing per-client commands retain project scope and manual routing by default:

```sh
eng hooks install claude-code -p . --mode keywords
eng hooks install codex -p . --mode keywords
eng hooks install gemini -p . --mode keywords
eng hooks install cursor -p . --mode keywords
eng hooks uninstall codex -p .
```

Use `--scope user` with those commands to target the user's settings. Top-level `eng
install` defaults to `--scope user --mode keywords`, and accepts `--client NAME` to
install one native hook. It always installs the portable skills as well.

Settings are updated atomically with one `.eng-backup` copy of existing settings. Other
hooks and configuration keys are retained. A skill with the same directory name but
without eng's ownership marker is never overwritten or removed. Additional files in a
managed skill directory are retained during uninstall.

## Routing modes

| Mode | Routes |
|---|---|
| `manual` | Only an `eng:` prefix |
| `keywords` | `eng:` or multi agent / multi-agent / multiagent / multiple agents |
| `adaptive` | Keywords plus high-confidence imperative change requests |
| `full` | Adaptive routing with a review floor |

Keyword matching is case-insensitive, bounded to words, includes plural forms and works
anywhere in a coding request. Questions, slash commands and ambiguous non-keyword prompts
pass through. An explicit `eng:` request takes precedence, including for questions.

Keyword routing requests complex classification, which runs planner, engineer, checks
and independent reviewer, with at least three model calls available. Normal task and
provider timeouts and high-risk approval requirements still apply. Repairs may need
additional budget. The roles are sequential; parallel plans require an explicit DAG and
human plan approval. No approval or promotion is performed by the hook or skill.

Claude Code hooks select the Claude provider, and Codex hooks select Codex. Gemini and
Cursor hooks and the portable skill use `provider` in `.engineering/project.yaml`,
defaulting to Codex. To override a native hook's provider:

```sh
eng hooks install gemini --scope user --mode keywords --provider claude
```

Client integration is separate from model-provider support. Gemini, Cursor and Copilot
are not built-in engine model providers; a compatible command provider is another option.

## Hook protocols and safety

| Client | User settings | Event | Block response after runner starts |
|---|---|---|---|
| Claude Code | `~/.claude/settings.json` | `UserPromptSubmit` | `decision: block` |
| Codex | `~/.codex/hooks.json` | `UserPromptSubmit` | `decision: block` |
| Gemini CLI | `~/.gemini/settings.json` | `BeforeAgent` | `decision: deny` |
| Cursor | `~/.cursor/hooks.json` | `beforeSubmitPrompt` | `continue: false` |

Claude uses exec-form `command`/`args`. Codex uses `command` and `commandWindows`.
Gemini uses grouped hooks and a millisecond timeout; Cursor uses a flat event array and a
seconds timeout. Gemini/Cursor command strings are generated for the installing OS;
rerun installation on another OS rather than copying settings across platforms.

Cursor's `conversation_id`/`generation_id` become session/turn identities. Routing
requires exactly one `workspace_roots` entry; multiple-root workspaces pass through to
avoid choosing the wrong repository. Other clients use `cwd` and available session/turn
IDs. Without a turn ID, identical prompt content deduplicates for 120 seconds.

Hook input is JSON on stdin; output is one JSON object or silence. Every execution failure
exits zero and lets the original prompt through. A successfully started task blocks the
original prompt, with a task ID and status command. `ENG_ACTIVE` prevents recursion.
Unconfigured repositories silently bypass user-wide hooks. Configured repositories still
require ignored runtime state and a clean checkout. Existing trigger claims deduplicate
repeated delivery; failed or interrupted claims never trap the prompt.

The user-wide hook discovers the repository from each prompt's client context rather than
pinning the repository where installation ran. Project hooks pin their installed root.

Official protocol references:

- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Codex hooks and trust](https://learn.chatgpt.com/docs/hooks)
- [Gemini CLI hook reference](https://geminicli.com/docs/hooks/reference/)
- [Cursor hooks](https://cursor.com/docs/hooks)
- [Copilot CLI skills](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills)

## Future clients and direct CLI use

Shared-skills clients can discover the skill after they are installed. For a different
skills root, install a copy explicitly:

```sh
eng install --skill-dir /path/to/new-client/skills
eng uninstall --skill-dir /path/to/new-client/skills
```

The option is repeatable. It adds the skill, not a native hook. A client without skills
can submit a request through `eng trigger`, preserving the entire prompt as one argv
argument and keeping shell interpolation out of user input:

```sh
eng trigger "Fix the parser with multiple agents" --mode keywords -p .
eng run "Fix addition" --accept "Addition returns the sum" --provider claude
```

Use `eng status TASK_ID` and `eng usage TASK_ID` to inspect work. The optional read-only
MCP server provides the same task state to a client:

```sh
claude mcp add eng -- eng mcp serve -p /absolute/path/to/repo
codex mcp add eng -- eng mcp serve -p /absolute/path/to/repo
```

The server exposes no approval or promotion tools. `--allow-submit` is a separate opt-in
for task submission and may result in billable model calls.

## Troubleshooting and removal

| Symptom | Check |
|---|---|
| Client answers a keyword prompt | Check `eng hooks status CLIENT --scope user`, restart the client and confirm project setup. |
| Codex skips eng | Open `/hooks` and trust its current definition. |
| Ordinary prompts are unexpectedly routed | Reinstall with `eng install --mode keywords`; inspect project hooks for adaptive/full mode too. |
| Hook fails after a tool environment moves | Rerun `eng install` using the persistent replacement environment. |
| Task pauses or blocks | Inspect `eng status TASK_ID`; extend budget or resolve the reported check/environment issue. |
| Copilot does not select the skill | Reload skills and explicitly use `/multiagentic-engineering`. |

```sh
eng uninstall
eng uninstall --scope project -p /absolute/path/to/repo
```

User and project installations are independent; removing one does not remove the other.
Repeat `--skill-dir` for additional copies. Uninstall removes only eng entries and managed
skill files. It retains backups, unrelated hooks, project state and worktrees.

Validation uses emulated client payloads and real subprocesses with offline providers.
It does not establish live hook delivery or successful paid provider editing in a client.
