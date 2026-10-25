import subprocess
from pathlib import Path

import pytest
import yaml

from eng.core.models import Check, ProjectConfig


def commit(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Eng Test",
            "-c",
            "user.email=eng@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture(autouse=True)
def git_ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Temporary directories may live inside this checkout (TEMP=.cache); repository
    # discovery must never climb out of a test's sandbox into the real repository.
    # Git does not protect a ceiling directory itself, only its subdirectories, so the
    # ceiling is the parent: commands run directly in tmp_path are covered too.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    (root / ".gitignore").write_text(
        ".engineering/state/\n.engineering/worktrees/\n"
        ".engineering/artifacts/\n.engineering/locks/\n",
        encoding="utf-8",
    )
    (root / "answer.txt").write_text("41", encoding="utf-8")
    (root / "check.py").write_text(
        "from pathlib import Path\nassert Path('answer.txt').read_text() == '42'\n",
        encoding="utf-8",
    )
    directory = root / ".engineering"
    directory.mkdir()
    config = ProjectConfig(
        name="fixture",
        checks=[
            Check(
                name="answer",
                argv=["{python}", "check.py"],
                confirmed=True,
            )
        ],
    )
    (directory / "project.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8"
    )
    commit(root)
    return root
