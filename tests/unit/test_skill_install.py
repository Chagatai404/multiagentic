import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from eng.cli import app
from eng.integrations.install import InstallScope
from eng.integrations.skills import SKILL_NAME, skill_paths, update_skills


@pytest.fixture
def user_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_install_from_outside_repository_is_idempotent_and_uninstalls(user_home: Path) -> None:
    runner = CliRunner()
    extra = user_home / "future-agent" / "skills"
    args = ["install", "--skill-dir", str(extra)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["scope"] == "user" and len(data["hooks"]) == 4
    assert all(hook["mode"] == "keywords" for hook in data["hooks"])
    assert len(data["skills"]) == 4
    for skill in data["skills"]:
        assert Path(skill["path"]).is_file()
    again = runner.invoke(app, args)
    assert again.exit_code == 0, again.output
    assert all(not item["changed"] for item in json.loads(again.output)["hooks"])
    assert all(not item["changed"] for item in json.loads(again.output)["skills"])
    status = runner.invoke(app, ["hooks", "status", "codex", "--scope", "user"])
    assert status.exit_code == 0 and json.loads(status.output)["installed"]
    removed = runner.invoke(app, ["uninstall", "--skill-dir", str(extra)])
    assert removed.exit_code == 0, removed.output
    assert all(not Path(skill["path"]).exists() for skill in data["skills"])


def test_project_install_does_not_write_user_settings(repo: Path, user_home: Path) -> None:
    result = CliRunner().invoke(app, ["install", "--scope", "project", "-p", str(repo)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert all(Path(hook["path"]).is_relative_to(repo) for hook in data["hooks"])
    assert all(Path(skill["path"]).is_relative_to(repo) for skill in data["skills"])
    assert not (user_home / ".codex").exists()
    assert not (user_home / ".claude").exists()


def test_refuses_to_replace_unowned_skill_or_remove_extra_files(user_home: Path) -> None:
    paths = skill_paths(InstallScope.USER, None, [])
    other = paths[0]
    other.parent.mkdir(parents=True)
    other.write_text("My own workflow", encoding="utf-8")
    for remove in (False, True):
        with pytest.raises(ValueError, match="unowned skill"):
            update_skills(InstallScope.USER, None, extra_dirs=[], remove=remove)
        assert other.read_text(encoding="utf-8") == "My own workflow"
        assert not paths[1].exists()
    other.unlink()
    update_skills(InstallScope.USER, None, extra_dirs=[])
    resource = other.parent / "personal-notes.txt"
    resource.write_text("keep me", encoding="utf-8")
    update_skills(InstallScope.USER, None, extra_dirs=[], remove=True)
    assert resource.read_text(encoding="utf-8") == "keep me"
    assert other.parent.name == SKILL_NAME


def test_invalid_client_is_rejected_before_writes(user_home: Path) -> None:
    result = CliRunner().invoke(app, ["install", "--client", "future-unknown-client"])
    assert result.exit_code == 2
    assert not (user_home / ".agents").exists()


def test_invalid_settings_do_not_partially_install(user_home: Path) -> None:
    path = user_home / ".cursor" / "hooks.json"
    path.parent.mkdir()
    path.write_text('{"hooks": []}', encoding="utf-8")
    result = CliRunner().invoke(app, ["install"])
    assert result.exit_code == 2
    assert not (user_home / ".agents").exists()
    assert not (user_home / ".claude").exists()
    assert not (user_home / ".codex").exists()
