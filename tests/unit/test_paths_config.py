from pathlib import Path

import pytest

from eng.context.packet import build_packet
from eng.core.models import Task, TaskSpec
from eng.execution.workspace import protected_changes, safe_path, task_lock
from eng.projects.config import initialize, load_config


@pytest.mark.parametrize("path", ["../outside", ".git/config"])
def test_paths_do_not_escape(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError):
        safe_path(tmp_path, path)


def test_mandatory_protections_cannot_be_disabled() -> None:
    paths = [".engineering/project.yaml", "nested/.env", "keys/private.pem", "src/code.py"]
    assert protected_changes(paths, []) == paths[:3]


def test_config_precedence_and_unique_checks(repo: Path, tmp_path: Path) -> None:
    user = tmp_path / "user.yaml"
    user.write_text("name: user\nbudgets:\n  context_chars: 999\n", encoding="utf-8")
    config = load_config(repo, user)
    assert config.name == "fixture"
    assert config.budgets.context_chars == 16000  # explicit project defaults win
    assert config.checks[0].confirmed


def test_init_does_not_overwrite(repo: Path) -> None:
    before = (repo / ".engineering/project.yaml").read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        initialize(repo)
    assert (repo / ".engineering/project.yaml").read_bytes() == before


def test_context_respects_size_and_excludes_secret_files(repo: Path) -> None:
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(description="fix", acceptance=["works"], context_paths=["check.py", ".env"]),
    )
    task.workspace = repo
    task.spec.budgets.context_chars = 700
    packet = build_packet(task)
    assert len(packet) <= 700
    assert "Reference file: check.py" in packet
    assert "Reference file: .env" not in packet


def test_os_lock_refuses_second_owner_and_releases(repo: Path) -> None:
    with task_lock(repo, "example"):
        with pytest.raises(ValueError, match="already running"):
            with task_lock(repo, "example"):
                pytest.fail("Lock admitted a second owner")
    with task_lock(repo, "example"):
        pass


def test_lock_identifier_cannot_escape_runtime_directory(repo: Path) -> None:
    with pytest.raises(ValueError, match="identifier"):
        with task_lock(repo, "../../outside"):
            pytest.fail("Unsafe task identifier was accepted")
