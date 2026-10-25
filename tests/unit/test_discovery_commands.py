import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from eng.core.models import Check
from eng.execution import commands
from eng.projects.config import initialize, load_config
from eng.verification import runner


@pytest.mark.parametrize(
    ("filename", "content", "language", "argv"),
    [
        ("pyproject.toml", "[project]\nname='demo'\n", "python", None),
        (
            "pyproject.toml",
            "[tool.pytest.ini_options]\n",
            "python",
            ["{python}", "-m", "pytest", "-q"],
        ),
        ("pyproject.toml", "[tool.pytest]\nini_options='fake'\n", "python", None),
        ("pytest.ini", "[pytest]\n", "python", ["{python}", "-m", "pytest", "-q"]),
        ("package.json", "{}", "javascript", None),
        ("package.json", '{"scripts":{"build":"node build.js"}}', "javascript", None),
        ("package.json", '{"scripts":{"test":"  "}}', "javascript", None),
        ("package.json", '{"scripts":{"test":"node test.js"}}', "javascript", ["npm", "test"]),
    ],
)
def test_conservative_discovery(
    tmp_path: Path, filename: str, content: str, language: str, argv: list[str] | None
) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / filename).write_text(content, encoding="utf-8")
    config = initialize(tmp_path)
    assert config.languages == [language]
    assert [check.argv for check in config.checks] == ([] if argv is None else [argv])
    assert all(not check.confirmed for check in config.checks)
    assert load_config(tmp_path) == config


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("pyproject.toml", "[broken"),
        ("pytest.ini", "broken"),
        ("package.json", "{"),
        ("package.json", "[]"),
        ("package.json", '{"scripts":[]}'),
        ("package.json", '{"scripts":{"test":42}}'),
    ],
)
def test_invalid_manifest_leaves_no_initialization(
    tmp_path: Path, filename: str, content: str
) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / filename).write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid"):
        initialize(tmp_path)
    assert not (tmp_path / ".engineering").exists()


def test_polyglot_discovery_has_distinct_unconfirmed_checks(tmp_path: Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"scripts":{"test":"node --test"}}', encoding="utf-8")
    config = initialize(tmp_path)
    assert config.languages == ["python", "javascript"]
    assert [check.name for check in config.checks] == ["tests", "npm-tests"]
    assert all(not check.confirmed for check in config.checks)


def test_old_absolute_python_command_preserves_literal_arguments(tmp_path: Path) -> None:
    literal = "space & $(whoami); value"
    check = Check(
        name="legacy",
        argv=[sys.executable, "-c", "import sys; print(sys.argv[1])", literal],
        confirmed=True,
    )
    result = asyncio.run(
        runner.run_checks(tmp_path, [check], tmp_path / "evidence", lambda: False, 10)
    )
    assert result[0].outcome == "PASS"
    assert result[0].command == check.argv
    assert result[0].artifact
    assert Path(result[0].artifact).read_text(encoding="utf-8").startswith(literal + "\n")


@pytest.mark.parametrize("name", ["npm", "npm.cmd", "npm.ps1"])
def test_windows_npm_resolves_literal_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    install = tmp_path / "Node installation & literal"
    entry = install / "node_modules/npm/bin/npm-cli.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("", encoding="utf-8")
    shim = install / name
    node = str(install / "node.exe")
    monkeypatch.setattr(commands.sys, "platform", "win32")
    monkeypatch.setattr(
        commands.shutil, "which", lambda name: node if name == "node" else str(shim)
    )
    argv = [name, "test", "--", "literal & $(whoami); value"]
    assert commands.resolve_command(argv) == [node, str(entry), *argv[1:]]
    assert argv[0] == name


@pytest.mark.parametrize("missing", ["npm", "node", "entry"])
def test_windows_npm_missing_layout_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    entry = tmp_path / "node_modules/npm/bin/npm-cli.js"
    entry.parent.mkdir(parents=True)
    if missing != "entry":
        entry.write_text("", encoding="utf-8")
    monkeypatch.setattr(commands.sys, "platform", "win32")
    monkeypatch.setattr(
        commands.shutil,
        "which",
        lambda name: None if name == missing else str(tmp_path / (name + ".exe")),
    )
    with pytest.raises(ValueError):
        commands.resolve_command(["npm", "test"])


def test_posix_and_python_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(commands.sys, "platform", "linux")
    assert commands.resolve_command(["npm", "test"]) == ["npm", "test"]
    assert commands.resolve_command(["{python}", "old check.py"]) == [
        sys.executable,
        "old check.py",
    ]


def test_unconfirmed_never_resolves_or_launches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("unconfirmed command reached execution boundary")

    monkeypatch.setattr(runner, "resolve_command", forbidden)
    monkeypatch.setattr(runner, "run_process", forbidden)
    result = asyncio.run(
        runner.run_checks(
            tmp_path,
            [Check(name="npm", argv=["npm", "test"])],
            tmp_path / "evidence",
            lambda: False,
            10,
        )
    )
    assert result[0].outcome == "SKIPPED"


def test_unavailable_resolution_retains_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(argv: list[str]) -> list[str]:
        raise ValueError("unsupported layout")

    monkeypatch.setattr(runner, "resolve_command", unavailable)
    check = Check(name="npm", argv=["npm", "test"], confirmed=True)
    result = asyncio.run(
        runner.run_checks(tmp_path, [check], tmp_path / "evidence", lambda: False, 10)
    )
    assert result[0].outcome == "UNAVAILABLE"
    assert result[0].command == check.argv
    assert result[0].artifact is None
