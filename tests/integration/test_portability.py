"""Offline protocol emulators exercise real adapters; these are not live model tests."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from eng.core.engine import Engine
from eng.core.models import State, Task, TaskSpec
from eng.execution.commands import resolve_command
from eng.execution.workspace import git
from eng.projects.config import initialize
from eng.providers.claude import ClaudeProvider
from eng.providers.codex import CodexProvider
from eng.storage.store import Store
from eng.verification.runner import run_checks


def commit_fixture(root: Path) -> None:
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Eng Test",
        "-c",
        "user.email=eng@example.invalid",
        "commit",
        "-m",
        "disposable fixture",
    )


@pytest.mark.parametrize("provider_name", ["codex", "claude"])
@pytest.mark.parametrize("language", ["python", "javascript"])
def test_real_adapters_two_languages_with_offline_emulators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider_name: str, language: str
) -> None:
    root = tmp_path / (language + " project & literal")
    root.mkdir()
    git(root, "init", "-b", "main")
    if language == "python":
        (root / "src/number_package").mkdir(parents=True)
        (root / "tests/unit").mkdir(parents=True)
        (root / "src/number_package/__init__.py").write_text("", encoding="utf-8")
        target = "src/number_package/answer.py"
        before, after = "VALUE = 41\n", "VALUE = 42\n"
        (root / "pytest.ini").write_text("[pytest]\npythonpath = src\n", encoding="utf-8")
        (root / "tests/unit/test_answer.py").write_text(
            "from number_package.answer import VALUE\ndef test_answer():\n    assert VALUE == 42\n",
            encoding="utf-8",
        )
    else:
        (root / "lib").mkdir()
        (root / "test").mkdir()
        target = "lib/answer.cjs"
        before, after = "module.exports = 41;\n", "module.exports = 42;\n"
        (root / "package.json").write_text(
            json.dumps(
                {
                    "name": "portability-fixture",
                    "private": True,
                    "scripts": {"test": "node --test test/answer.cjs"},
                }
            ),
            encoding="utf-8",
        )
        (root / "test/answer.cjs").write_text(
            "const assert = require('node:assert/strict');\n"
            "const test = require('node:test');\n"
            "test('answer', () => assert.equal(require('../lib/answer.cjs'), 42));\n",
            encoding="utf-8",
        )
        try:
            resolve_command(["npm", "test"])
        except ValueError as error:
            pytest.fail(f"Node/npm required for portability matrix: {error}")
    (root / target).write_text(before, encoding="utf-8")
    (root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    config = initialize(root)
    assert config.languages == [language]
    assert len(config.checks) == 1 and not config.checks[0].confirmed
    skipped = asyncio.run(
        run_checks(root, config.checks, tmp_path / "unconfirmed", lambda: False, 30)
    )
    assert skipped[0].outcome == "SKIPPED"
    config.checks[0].confirmed = True  # explicit review step, retained in task snapshot
    baseline = asyncio.run(
        run_checks(root, config.checks, tmp_path / "baseline", lambda: False, 30)
    )
    assert baseline[0].outcome == "FAIL", baseline[0].model_dump()
    assert baseline[0].artifact and Path(baseline[0].artifact).is_file()
    commit_fixture(root)
    head = git(root, "rev-parse", "HEAD")

    emulator = tmp_path / (provider_name + " protocol emulator.py")
    argv_record = tmp_path / "provider argv.json"
    # Only the executable locator is replaced. The actual adapter builds argv, launches
    # the child, supplies stdin and parses its protocol; the child edits the real worktree.
    emulator.write_text(
        "import json, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        f"pathlib.Path({str(argv_record)!r}).write_text(json.dumps(args), encoding='utf-8')\n"
        "prompt = sys.stdin.read()\nassert 'Repair answer' in prompt\n"
        f"pathlib.Path({target!r}).write_text({after!r}, encoding='utf-8')\n"
        + (
            "assert args[:2] == ['exec', '--json']\n"
            "assert args[-1] == '-'\n"
            "assert pathlib.Path(args[args.index('--cd') + 1]) == pathlib.Path.cwd()\n"
            "print(json.dumps({'type':'thread.started','thread_id':'offline-session'}))\n"
            "print(json.dumps({'type':'item.completed','item':"
            "{'type':'agent_message','text':'Offline repair'}}))\n"
            "print(json.dumps({'type':'turn.completed'}))\n"
            if provider_name == "codex"
            else "assert args[:3] == ['--safe-mode', '--restricted', '--print']\n"
            "print(json.dumps({'type':'result','subtype':'success','is_error':False,"
            "'result':'Offline repair','permission_denials':[]}))\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        f"eng.providers.{provider_name}.{provider_name}_command",
        lambda: [sys.executable, str(emulator)],
    )
    provider = CodexProvider() if provider_name == "codex" else ClaudeProvider()
    store = Store(root)
    try:
        task = Task(
            project=root,
            config=config,
            spec=TaskSpec(
                description="Repair answer",
                acceptance=["answer is 42"],
                provider=provider_name,
            ),
        )
        store.create(task)
        result = asyncio.run(Engine(store, provider).execute(task.id))
        assert result.state == State.COMPLETED, result.message
        assert result.provider_calls == 1
        assert result.workspace is not None and result.workspace != root
        assert (result.workspace / target).read_text(encoding="utf-8") == after
        assert (root / target).read_text(encoding="utf-8") == before
        assert git(root, "rev-parse", "HEAD") == head
        assert git(root, "status", "--porcelain") == ""
        assert result.verification[0].outcome == "PASS"
        assert result.verification[0].command == config.checks[0].argv
        assert result.verification[0].artifact
        assert Path(result.verification[0].artifact).is_file()
        assert result.usage.input_tokens is None  # emulator does not invent usage
        evidence = root / ".engineering/artifacts" / task.id / str(result.execution_id)
        assert (evidence / "changes.diff").is_file()
        assert (evidence / "events.jsonl").is_file()
        assert (
            evidence / ("provider.jsonl" if provider_name == "codex" else "provider.json")
        ).is_file()
        arguments = json.loads(argv_record.read_text(encoding="utf-8"))
        if provider_name == "codex":
            assert arguments == [
                "exec",
                "--json",
                "--ephemeral",
                "--ignore-user-config",
                "--color",
                "never",
                "--sandbox",
                "workspace-write",
                "-c",
                'approval_policy="never"',
                "-c",
                "sandbox_workspace_write.network_access=false",
                "--cd",
                str(result.workspace),
                "-",
            ]
        else:
            assert arguments == [
                "--safe-mode",
                "--restricted",
                "--print",
                "--output-format",
                "json",
                "--no-session-persistence",
                "--permission-mode",
                "acceptEdits",
                "--permission-prompts",
                "none",
                "--strict-mcp-config",
                "--mcp-config",
                '{"mcpServers":{}}',
                "--setting-sources",
                "",
                "--tools",
                "Read,Edit,Write,Glob,Grep",
                "--disable-slash-commands",
                "--no-chrome",
            ]
    finally:
        store.close()
