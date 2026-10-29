# Agent instructions

Repository and tests are implementation truth. Read ARCHITECTURE.md before changing
subsystem boundaries. Before substantial work inspect status, branch, worktrees and
recent commits. Check configured shared coordination state. Do not edit another
agent's active files or work concurrently with Claude in the same directory; use an
isolated agent/codex/<task> branch/worktree if another agent is active. Git records
completed work; branch existence alone does not mean integration.

Keep models/policy pure. Inject providers/storage at the engine boundary. Invoke
processes with argv arrays, never shell interpolation. No provider-specific flags in
the engine. Verify installed help and official docs before altering adapter flags.
Keep missing usage unknown. No automatic push, deployment, destructive cleanup, or
permission bypass. Worktrees are not security sandboxes. Do not log credentials.

Run focused pytest coverage, ruff and mypy for affected changes; inspect actual diffs.
Run full tests and a package build before a milestone handoff. Live model tests are
opt-in, time/call bounded and potentially billable. Report skipped/unavailable checks.
Plans (`eng plan`), Git/CI triggers, command providers and the MCP server are operational
as of M6, verified offline only; do not claim live provider editing, live client hooks,
real CI delivery or Windows M6 runtime behaviour are validated unless you have run them.
Plan approvals and promotion are human CLI actions: never add a model-callable way to
grant them (the MCP server deliberately has none) and never make eng push or delete
workspaces. Concurrency is capped at three (`core/plan.MAX_CONCURRENCY`).

Permanent Obsidian vault: C:/Users/ASUS/Obsidian/Knowledge. Use the Obsidian skill
for relevant durable knowledge; consult only the corresponding project note when
useful, never the entire vault. No secrets or session logs in Obsidian. Graphify maps
code relationships, not vault knowledge. Claude-mem is Claude Code's session memory.
See the user's personal instructions for Research OS tasks; this package's engineering
state is separate from Research OS and human knowledge records.

## Native plugin development (2.0 beta)

The primary product is now the native plugin; the CLI requirements above apply to
legacy `src/eng` behavior. Keep native adapters free of coding-CLI subprocesses and
`eng` runtime dependencies. Native plans live in `.plans/`; user decisions and native
host permissions apply. Max native concurrency is three. Shared ownership includes
read/write dependencies; one coordinator owns state and integration.

Run `npm test`, `npm run check`, and `npm run check:package` for plugin changes.
Keep skills canonical under `skills/`, preserve upstream licensing, and distinguish
protocol guidance from runtime enforcement. Do not claim live host execution from
mock transports, SDK registration, manifests, or offline tests. Publishing a review
branch/PR when requested is separate from any plugin's runtime permissions.
