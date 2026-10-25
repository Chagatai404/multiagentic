# M4 parallel implementation plan - automatic trigger integration

## Goal

Supported client hooks (Claude Code and Codex `UserPromptSubmit`) and a generic
`eng trigger` command submit normalized TriggerEnvelopes. Explicit or high-confidence
engineering requests start exactly one orchestrated task; everything else passes through
untouched. Deduplication, reentrancy protection and a safe read-only bypass are tested
with emulated client input. No live client hook firing is claimed.

## Verified client facts (official docs, 2026-10-26; installed claude 2.1.301, codex 0.149.0)

- Both clients send JSON on stdin with `session_id`, `cwd`, `hook_event_name`, `prompt`;
  Claude Code adds `prompt_id` and `transcript_path`, Codex adds `turn_id` and `model`.
- Exit 0 with no output passes through. `{"decision":"block","reason":...}` on stdout or
  exit 2 blocks the prompt (reason shown to the user). `systemMessage` warns the user.
- Claude Code: `.claude/settings.local.json` -> `hooks.UserPromptSubmit[].hooks[]` with
  `type: command`, `command`, optional `args` (exec form, no shell) and `timeout`
  (default 30 s). Also fires for background-subagent reports and inter-session messages.
- Codex: `.codex/hooks.json` -> same nesting; `command` is one string, `commandWindows`
  overrides it on Windows, `timeout` seconds. Non-managed hooks run only after the user
  trusts them with `/hooks`; project `.codex/` layers must be trusted. eng never uses
  `--dangerously-bypass-hook-trust`.

## Safety rules for every slice

- Exit code 2 blocks the user's prompt: the hook entry point never exits 2, never uses
  Typer/`fail()`, tolerates unknown arguments, and fails open (exit 0 + systemMessage).
- Never install hooks into this checkout or a home directory; tests use `tmp_path` only.
- Store prompt digests and redacted envelopes, never raw secrets.
- Detached runner holds none of the hook's pipes. No pushes, no paid model calls.
- Defaults: installed mode is `manual` (only `eng:` routes) unless `--mode adaptive|full`.

## Contracts (frozen; `src/eng/core/triggers.py`)

TriggerOrigin, TriggerMode, TriggerAction, TriggerEnvelope, TriggerDecision,
TriggerRecord, CONTENT_DEDUP_SECONDS.

## Slice A - routing and trigger storage (medium)

Owns `src/eng/core/triggers.py` (add functions only, keep models), `src/eng/storage/store.py`
(migration 3 + trigger methods), `tests/unit/test_triggers.py`,
`tests/unit/test_trigger_storage.py`.

- `prompt_digest(prompt: str) -> str` - sha256 of stripped, whitespace-collapsed,
  casefolded text.
- `idempotency_key(envelope) -> tuple[str, bool]` - `(key, content_keyed)`; key from
  origin + session + turn_id when turn_id present, else origin + session + digest.
- `route_trigger(envelope, mode, *, reentrant: bool) -> TriggerDecision` - order:
  reentrant -> REENTRANT; `eng:` prefix (case-insensitive, leading whitespace) -> ROUTE
  with stripped description (blank -> BYPASS); slash command -> BYPASS; MANUAL -> BYPASS;
  M3 `classify_task` QUESTION -> BYPASS; ADAPTIVE/FULL high-confidence imperative change
  (leading optional "please", verb such as fix/implement/add/create/refactor/update/
  rename/remove/write tests, at least 3 words, no trailing question mark) -> ROUTE;
  otherwise BYPASS "ambiguous". `full_verification = mode == FULL` on ROUTE.
- Store migration 3: `triggers(key PRIMARY KEY, origin, session_id, prompt_digest,
  content_keyed, task_id, status, message, created_at, updated_at, payload)`.
- `Store.claim_trigger(record, payload: dict, *, now: str) -> TriggerRecord | None` - in
  one `BEGIN IMMEDIATE`: insert; if the key exists return the existing record (duplicate),
  except a content-keyed row older than CONTENT_DEDUP_SECONDS is replaced (returns None).
  `payload` is stored through `redact_data`.
- `Store.update_trigger(key, *, status, task_id=None, message="", now)`;
  `Store.trigger(key) -> TriggerRecord | None`; `Store.triggers(limit=50)`.

## Slice B - client adapters and installers (medium)

Owns `src/eng/integrations/__init__.py`, `clients.py`, `install.py`,
`tests/unit/test_clients.py`, `tests/unit/test_install.py`.

- `parse_hook_input(origin, raw: str, *, received_at: str) -> TriggerEnvelope` - strict
  JSON object, `prompt` string required, map `prompt_id`/`turn_id` to `turn_id`; raise
  ValueError otherwise. Unknown keys ignored.
- `render_decision(origin, decision, *, project: Path) -> tuple[int, str]` - ROUTE and
  DUPLICATE (task_id set) -> `(0, json block with reason naming the task and
  "eng status <id> -p <project>")`; BYPASS/REENTRANT -> `(0, "")`.
- `render_error(origin, message) -> tuple[int, str]` - `(0, json systemMessage)`.
- `hook_command(client, *, mode, provider) -> list[str]` - argv
  `[sys.executable, "-m", "eng.integrations.hook", client, "--mode", mode,
  "--provider", provider]`.
- `install_hook(client, project_root, *, mode, provider) -> dict`,
  `uninstall_hook(client, project_root) -> dict`, `hook_status(client, project_root) -> dict`.
  Claude: `.claude/settings.local.json`, entry `{"type":"command","command":argv[0],
  "args":argv[1:],"timeout":20}`. Codex: `.codex/hooks.json`, entry `{"type":"command",
  "command": shlex.join(argv), "commandWindows": subprocess.list2cmdline(argv),
  "timeout":20, "statusMessage":"eng: routing prompt"}`. Identify eng entries by the
  `eng.integrations.hook` marker; preserve all other keys and hooks; idempotent; atomic
  write (temp + os.replace); `<file>.eng-backup` before the first modification of an
  existing file; malformed existing JSON -> ValueError, file untouched.

## Slice C - detached runner (medium-high)

Owns `src/eng/integrations/runner.py`, `tests/unit/test_runner.py`.

- `spawn_detached(argv: list[str], *, cwd: Path, log_path: Path,
  env: dict[str, str] | None = None) -> int` - stdin DEVNULL, stdout+stderr appended to
  log_path, close_fds; Windows `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, attempting
  `CREATE_BREAKAWAY_FROM_JOB` first and retrying without it if refused; POSIX
  `start_new_session=True`. Returns the pid; raises OSError on failure.
- Tests: the parent returns promptly while the child keeps running; a parent that reads
  the parent's own captured pipes to EOF is not blocked by the child; the child writes to
  the log; env is passed exactly.

## Slice D - hook entry point, CLI and end-to-end (lead)

Owns `src/eng/integrations/hook.py`, `src/eng/cli.py`, `tests/integration/test_triggers_e2e.py`
and docs. Order per prompt: route -> claim trigger -> create CREATED task -> spawn
`eng start TASK` -> mark started -> emit block. Spawn failure marks the trigger failed
and fails open. `eng start TASK_ID` executes a CREATED task; `eng trigger` reads an
envelope JSON; `eng hooks install|uninstall|status CLIENT`.

## Deferred

Git hooks and CI triggers (M6), live hook firing inside real clients, MCP.
