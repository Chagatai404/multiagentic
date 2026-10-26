import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from eng.integrations.clients import hook_command
from eng.integrations.install import InstallScope, hook_status, install_hook, uninstall_hook

CLAUDE_FILE = Path(".claude") / "settings.local.json"
CODEX_FILE = Path(".codex") / "hooks.json"


def _read(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _existing_settings() -> dict[str, Any]:
    return {
        "model": "sonnet",
        "permissions": {"allow": ["Bash(git status)"]},
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "lint"}]}],
            "UserPromptSubmit": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": "other-tool", "timeout": 5},
                    ],
                }
            ],
        },
    }


def test_install_into_empty_project_creates_claude_settings(tmp_path: Path) -> None:
    result = install_hook("claude-code", tmp_path, mode="manual", provider="claude")
    path = tmp_path / CLAUDE_FILE
    assert result == {
        "client": "claude-code",
        "path": str(path),
        "installed": True,
        "changed": True,
        "backup": None,
        "mode": "manual",
    }
    hook = _read(path)["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    assert hook == {
        "type": "command",
        "command": sys.executable,
        "args": [
            "-m",
            "eng.integrations.hook",
            "claude-code",
            "--mode",
            "manual",
            "--provider",
            "claude",
            "--project",
            str(tmp_path.resolve()),
        ],
        "timeout": 20,
    }


def test_install_codex_writes_both_command_forms_and_trust_note(tmp_path: Path) -> None:
    result = install_hook("codex", tmp_path, mode="adaptive", provider="codex")
    assert "/hooks" in result["note"]
    hook = _read(tmp_path / CODEX_FILE)["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    argv = hook_command("codex", mode="adaptive", provider="codex", project=tmp_path)
    assert hook["commandWindows"] == subprocess.list2cmdline(argv)
    assert "eng.integrations.hook" in hook["command"]
    assert hook["timeout"] == 20
    assert hook["statusMessage"] == "eng: routing prompt"
    assert "dangerously" not in (tmp_path / CODEX_FILE).read_text(encoding="utf-8")


def test_install_preserves_unrelated_keys_and_hooks(tmp_path: Path) -> None:
    path = tmp_path / CLAUDE_FILE
    path.parent.mkdir(parents=True)
    original = json.dumps(_existing_settings(), indent=2)
    path.write_text(original, encoding="utf-8")

    result = install_hook("claude-code", tmp_path, mode="manual", provider="claude")
    data = _read(path)

    assert result["changed"] is True
    assert data["model"] == "sonnet"
    assert data["permissions"] == {"allow": ["Bash(git status)"]}
    assert data["hooks"]["PreToolUse"] == _existing_settings()["hooks"]["PreToolUse"]
    groups = data["hooks"]["UserPromptSubmit"]
    assert groups[0] == _existing_settings()["hooks"]["UserPromptSubmit"][0]
    assert len(groups) == 2
    assert groups[1]["hooks"][0]["command"] == sys.executable
    assert result["backup"] == str(path.with_name(path.name + ".eng-backup"))
    assert path.with_name(path.name + ".eng-backup").read_text(encoding="utf-8") == original


def test_second_install_is_idempotent(tmp_path: Path) -> None:
    install_hook("claude-code", tmp_path, mode="manual", provider="claude")
    path = tmp_path / CLAUDE_FILE
    before = path.read_bytes()
    result = install_hook("claude-code", tmp_path, mode="manual", provider="claude")
    assert result["changed"] is False
    assert result["backup"] is None
    assert path.read_bytes() == before


def test_mode_change_replaces_only_eng_entry_and_backup_is_kept_once(tmp_path: Path) -> None:
    path = tmp_path / CLAUDE_FILE
    path.parent.mkdir(parents=True)
    original = json.dumps(_existing_settings(), indent=2)
    path.write_text(original, encoding="utf-8")
    backup = path.with_name(path.name + ".eng-backup")

    install_hook("claude-code", tmp_path, mode="manual", provider="claude")
    result = install_hook("claude-code", tmp_path, mode="full", provider="claude")
    assert result["changed"] is True
    assert result["backup"] is None
    assert backup.read_text(encoding="utf-8") == original

    data = _read(path)
    groups = data["hooks"]["UserPromptSubmit"]
    eng_hooks = [
        hook
        for group in groups
        for hook in group["hooks"]
        if "eng.integrations.hook" in " ".join(hook.get("args", []))
    ]
    assert len(eng_hooks) == 1
    assert "full" in eng_hooks[0]["args"]
    assert groups[0] == _existing_settings()["hooks"]["UserPromptSubmit"][0]
    assert hook_status("claude-code", tmp_path)["mode"] == "full"


def test_uninstall_removes_only_eng_entries(tmp_path: Path) -> None:
    path = tmp_path / CLAUDE_FILE
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_existing_settings(), indent=2), encoding="utf-8")

    install_hook("claude-code", tmp_path, mode="manual", provider="claude")
    result = uninstall_hook("claude-code", tmp_path)

    assert result["changed"] is True
    assert result["installed"] is False
    assert _read(path) == _existing_settings()
    assert hook_status("claude-code", tmp_path)["installed"] is False


def test_uninstall_on_fresh_install_drops_emptied_keys(tmp_path: Path) -> None:
    install_hook("codex", tmp_path, mode="manual", provider="codex")
    result = uninstall_hook("codex", tmp_path)
    assert result["changed"] is True
    assert _read(tmp_path / CODEX_FILE) == {}


def test_uninstall_without_settings_file_creates_nothing(tmp_path: Path) -> None:
    result = uninstall_hook("claude-code", tmp_path)
    assert result["changed"] is False
    assert not (tmp_path / CLAUDE_FILE).exists()


def test_status_reports_installed_mode_and_codex_note(tmp_path: Path) -> None:
    assert hook_status("codex", tmp_path)["installed"] is False
    install_hook("codex", tmp_path, mode="adaptive", provider="codex")
    status = hook_status("codex", tmp_path)
    assert status["installed"] is True
    assert status["entries"] == 1
    assert status["mode"] == "adaptive"
    assert "/hooks" in status["note"]


@pytest.mark.parametrize(
    "content",
    [
        '{"hooks": {',
        "[1, 2]",
        '{"hooks": []}',
        '{"hooks": {"UserPromptSubmit": {}}}',
    ],
)
def test_malformed_settings_raise_and_stay_byte_identical(tmp_path: Path, content: str) -> None:
    path = tmp_path / CLAUDE_FILE
    path.parent.mkdir(parents=True)
    path.write_bytes(content.encode("utf-8"))

    with pytest.raises(ValueError):
        install_hook("claude-code", tmp_path, mode="manual", provider="claude")
    with pytest.raises(ValueError):
        uninstall_hook("claude-code", tmp_path)
    with pytest.raises(ValueError):
        hook_status("claude-code", tmp_path)

    assert path.read_bytes() == content.encode("utf-8")
    assert not path.with_name(path.name + ".eng-backup").exists()


def test_unknown_client_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        install_hook("cli", tmp_path, mode="manual", provider="claude")
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("client", "variable", "filename"),
    [("claude-code", "CLAUDE_CONFIG_DIR", "settings.json"), ("codex", "CODEX_HOME", "hooks.json")],
)
def test_user_hook_is_unbound_preserves_settings_and_is_reversible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: str, variable: str, filename: str
) -> None:
    directory = tmp_path / "client config with spaces"
    directory.mkdir()
    monkeypatch.setenv(variable, str(directory))
    path = directory / filename
    original = json.dumps(_existing_settings())
    path.write_text(original, encoding="utf-8")
    result = install_hook(client, mode="keywords", provider="fake", scope=InstallScope.USER)
    assert result["path"] == str(path)
    assert _read(path)["permissions"] == _existing_settings()["permissions"]
    entry = _read(path)["hooks"]["UserPromptSubmit"][-1]["hooks"][0]
    assert "--project" not in json.dumps(entry)
    assert "keywords" in json.dumps(entry)
    assert not install_hook(client, mode="keywords", provider="fake", scope=InstallScope.USER)[
        "changed"
    ]
    assert hook_status(client, scope=InstallScope.USER)["installed"]
    assert uninstall_hook(client, scope=InstallScope.USER)["changed"]
    assert _read(path) == _existing_settings()
    assert path.with_name(path.name + ".eng-backup").read_text(encoding="utf-8") == original


@pytest.mark.parametrize("client", ["claude-code", "codex"])
def test_user_and_project_hooks_are_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: str
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "user-claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "user-codex"))
    project = tmp_path / "project"
    install_hook(client, mode="keywords", provider="fake", scope=InstallScope.USER)
    install_hook(client, project, mode="manual", provider="fake")
    uninstall_hook(client, project)
    assert hook_status(client, scope=InstallScope.USER)["installed"]
    assert not hook_status(client, project)["installed"]


def test_default_user_paths_respect_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert hook_status("claude-code", scope=InstallScope.USER)["path"] == str(
        tmp_path / ".claude" / "settings.json"
    )
    assert hook_status("codex", scope=InstallScope.USER)["path"] == str(
        tmp_path / ".codex" / "hooks.json"
    )


@pytest.mark.parametrize(
    ("client", "event", "filename"),
    [("gemini", "BeforeAgent", "settings.json"), ("cursor", "beforeSubmitPrompt", "hooks.json")],
)
def test_additional_client_hook_layout_and_preservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: str, event: str, filename: str
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / f".{client}" / filename
    path.parent.mkdir()
    other = {"command": "other-tool", "type": "command"}
    groups = [other] if client == "cursor" else [{"hooks": [other]}]
    original = {"version": 1, "hooks": {event: groups}, "unrelated": {"keep": True}}
    path.write_text(json.dumps(original), encoding="utf-8")
    install_hook(client, mode="keywords", provider=None, scope=InstallScope.USER)
    data = _read(path)
    assert data["unrelated"] == original["unrelated"]
    assert data["hooks"][event][0] == groups[0]
    entry = data["hooks"][event][-1]
    if client == "gemini":
        entry = entry["hooks"][0]
        assert entry["timeout"] == 20000
    assert "--provider" not in entry["command"]  # use project's configured provider
    assert hook_status(client, scope=InstallScope.USER)["mode"] == "keywords"
    assert not install_hook(client, mode="keywords", provider=None, scope=InstallScope.USER)[
        "changed"
    ]
    uninstall_hook(client, scope=InstallScope.USER)
    assert _read(path) == original
