import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from eng.cli import app, provider_for
from eng.core.models import Task, TaskSpec
from eng.providers.fake import FakeProvider
from eng.storage.store import Store

runner = CliRunner()


def test_provider_for_and_discovery() -> None:
    assert provider_for("claude").name == "claude"
    assert provider_for("codex").name == "codex"
    fake = provider_for("fake", ["answer.txt=42"])
    assert isinstance(fake, FakeProvider)
    assert fake.changes == {"answer.txt": "42"}
    for name in ("codex", "claude"):
        with pytest.raises(ValueError, match="only available"):
            provider_for(name, ["answer.txt=42"])
    with pytest.raises(ValueError, match="relative/path"):
        provider_for("fake", ["bad"])
    result = runner.invoke(app, ["providers"])
    assert result.exit_code == 0
    assert set(json.loads(result.output)) == {"claude", "codex", "fake"}
    help_result = runner.invoke(app, ["run", "--help"])
    assert all(name in help_result.output for name in ("claude", "codex", "fake"))


@pytest.mark.parametrize("override,expected", [(None, "claude"), ("codex", "codex")])
def test_cli_provider_selection(
    repo: Path, monkeypatch: pytest.MonkeyPatch, override: str | None, expected: str
) -> None:
    config_path = repo / ".engineering" / "project.yaml"
    config_path.write_text(
        config_path.read_text().replace("provider: codex", "provider: claude"),
        encoding="utf-8",
    )
    selected = []

    async def execute(self: object, task_id: str) -> Task:
        selected.append(self.provider.name)  # type: ignore[attr-defined]
        return self.store.load(task_id)  # type: ignore[attr-defined,no-any-return]

    monkeypatch.setattr("eng.cli.Engine.execute", execute)
    args = ["run", "fix", "--accept", "works", "-p", str(repo)]
    if override:
        args.extend(["--provider", override])
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert selected == [expected]
    assert json.loads(result.output)["spec"]["provider"] == expected


def test_resume_uses_saved_provider(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eng.projects.config import load_config

    store = Store(repo)
    task = Task(
        project=repo,
        spec=TaskSpec(description="fix", acceptance=["works"], provider="claude"),
        config=load_config(repo),
    )
    store.create(task)
    store.close()
    selected = []

    async def execute(self: object, task_id: str, *, resume: bool, verify_only: bool) -> Task:
        selected.append(self.provider.name)  # type: ignore[attr-defined]
        assert resume and not verify_only
        return self.store.load(task_id)  # type: ignore[attr-defined,no-any-return]

    monkeypatch.setattr("eng.cli.Engine.execute", execute)
    result = runner.invoke(app, ["resume", task.id, "-p", str(repo)])
    assert result.exit_code == 1, result.output
    assert selected == ["claude"]


def test_doctor_cli_reports_each_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from eng.execution.process import ProcessResult

    async def probe(argv: list[str], cwd: Path, seconds: float) -> ProcessResult:
        assert argv[-1] == "--version"
        return ProcessResult(0, "version", "", 0)

    monkeypatch.setattr("eng.providers.registry.codex_command", lambda: ["codex"])
    monkeypatch.setattr("eng.providers.registry.claude_command", lambda: ["claude"])
    monkeypatch.setattr("eng.providers.registry.run_process", probe)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    for name in ("claude", "codex"):
        assert output[name]["available"]
        assert output[name]["authentication"] == "not_checked"
    assert output["fake"]["kind"] == "deterministic_fixture"
