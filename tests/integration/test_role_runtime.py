import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

from eng.agents import execute_role, parse_handoff, workspace_digest
from eng.core.models import ProjectConfig, ProviderRequest, ProviderResult, Role, Task, TaskSpec
from eng.execution.workspace import git
from eng.providers.fake import FakeProvider


def task_request(repo: Path, role: Role) -> tuple[Task, ProviderRequest]:
    task = Task(
        project=repo,
        workspace=repo,
        config=ProjectConfig(),
        spec=TaskSpec(description="Fix fixture", acceptance=["pass"]),
    )
    return task, ProviderRequest(
        task_id=task.id,
        execution_id="run",
        role=role,
        workspace=repo,
        prompt=f"Inspect {repo}",
        timeout_seconds=60,
    )


class InspectProvider(FakeProvider):
    def __init__(self, primary: Path, mutation: str = "") -> None:
        super().__init__()
        self.primary = primary
        self.mutation = mutation
        self.snapshot: Path | None = None

    async def execute(
        self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
    ) -> ProviderResult:
        self.snapshot = request.workspace
        assert request.workspace != self.primary
        assert (request.workspace / ".git").is_dir()
        assert git(request.workspace, "rev-parse", "--git-common-dir") == ".git"
        assert not (request.workspace / ".engineering").exists()
        assert (request.workspace / "untracked.txt").read_text() == "preserved"
        assert str(self.primary) not in request.prompt
        if self.mutation == "snapshot":
            (request.workspace / "answer.txt").write_text("bad")
        elif self.mutation == "primary":
            (self.primary / "answer.txt").write_text("bad")
        elif self.mutation == "protected":
            (self.primary / ".engineering" / "project.yaml").write_text("bad")
        return ProviderResult(status="success", summary="inspected")


@pytest.mark.parametrize("mutation", ["", "snapshot", "primary", "protected"])
def test_read_only_role_standalone_snapshot(repo: Path, tmp_path: Path, mutation: str) -> None:
    (repo / "untracked.txt").write_text("preserved")
    task, request = task_request(repo, Role.REVIEWER)
    provider = InspectProvider(repo, mutation)
    before = workspace_digest(repo)
    result = asyncio.run(
        execute_role(provider, request, task, tmp_path / "artifacts", lambda: False)
    )
    assert result.status == ("error" if mutation else "success")
    if mutation:
        assert result.error_kind == "role_mutation"
    else:
        assert workspace_digest(repo) == before
    assert provider.snapshot is not None and provider.snapshot.exists()
    assert not (provider.snapshot / "artifacts").exists()


def test_snapshot_beyond_windows_max_path(tmp_path: Path) -> None:
    # Directories stay below MAX_PATH (Git must chdir there); its object files exceed it.
    padding = 225 - len(str(tmp_path / "x" / "r-snapshot-00000000"))
    if padding < 1:
        pytest.skip("Temporary directory is already too deep for this layout")
    deep = tmp_path / ("d" * padding)
    repo = deep / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "--quiet")
    (repo / "untracked.txt").write_text("preserved")
    artifact_dir = deep / "invocation"
    snapshot_objects = artifact_dir.parent / "r-snapshot-00000000" / ".git" / "objects"
    assert len(str(snapshot_objects / "00" / ("0" * 38))) > 260
    task, request = task_request(repo, Role.REVIEWER)
    provider = InspectProvider(repo)
    result = asyncio.run(execute_role(provider, request, task, artifact_dir, lambda: False))
    assert result.status == "success", result.summary
    assert provider.snapshot is not None and provider.snapshot.parent == artifact_dir.parent


def test_worktree_snapshots_use_shallow_project_root(repo: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "worktree"
    workspace.mkdir()
    git(workspace, "init", "--quiet")
    (workspace / "untracked.txt").write_text("preserved")
    task, request = task_request(workspace, Role.REVIEWER)
    task = task.model_copy(update={"project": repo})
    deep = tmp_path / "artifacts" / ("t" * 32) / ("e" * 32) / "roles" / "r1"
    provider = InspectProvider(workspace)
    result = asyncio.run(execute_role(provider, request, task, deep, lambda: False))
    assert result.status == "success", result.summary
    assert provider.snapshot is not None
    assert provider.snapshot.parent == repo.resolve() / ".engineering" / "artifacts" / "snapshots"


@pytest.mark.parametrize("mutation", ["", "snapshot"])
def test_provider_exception_keeps_mutation_evidence(
    repo: Path, tmp_path: Path, mutation: str
) -> None:
    class Raising(InspectProvider):
        async def execute(
            self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
        ) -> ProviderResult:
            await super().execute(request, artifact_dir, cancelled)
            raise RuntimeError("provider crashed")

    (repo / "untracked.txt").write_text("preserved")
    task, request = task_request(repo, Role.REVIEWER)
    run = execute_role(Raising(repo, mutation), request, task, tmp_path / "a", lambda: False)
    if mutation:
        result = asyncio.run(run)
        assert (result.status, result.error_kind) == ("error", "role_mutation")
    else:
        with pytest.raises(RuntimeError, match="provider crashed"):
            asyncio.run(run)


def test_git_timeout_is_a_git_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from eng.execution import workspace

    def slow(*_: object, **__: object) -> None:
        raise subprocess.TimeoutExpired("git", 30)

    monkeypatch.setattr(workspace.subprocess, "run", slow)
    with pytest.raises(ValueError, match="timed out"):
        git(tmp_path, "status")


def test_snapshot_setup_failure_is_not_reported_as_mutation(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eng.agents import runtime

    def broken(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(runtime, "_prepare_snapshot", broken)
    task, request = task_request(repo, Role.PLANNER)
    result = asyncio.run(
        execute_role(FakeProvider(), request, task, tmp_path / "artifacts", lambda: False)
    )
    assert (result.status, result.error_kind) == ("error", "role_setup")


@pytest.mark.parametrize("role", [Role.PLANNER, Role.REVIEWER])
def test_fake_read_only_roles_do_not_edit(repo: Path, tmp_path: Path, role: Role) -> None:
    task, request = task_request(repo, role)
    result = asyncio.run(
        execute_role(
            FakeProvider({"answer.txt": "42"}), request, task, tmp_path / "artifacts", lambda: False
        )
    )
    assert result.status == "success"
    assert (repo / "answer.txt").read_text() == "41"
    assert parse_handoff(role, result.summary, "invocation").role == role


@pytest.mark.parametrize("role", [Role.ENGINEER, Role.DEBUGGER])
def test_editing_role_uses_actual_workspace(repo: Path, tmp_path: Path, role: Role) -> None:
    task, request = task_request(repo, role)
    result = asyncio.run(
        execute_role(
            FakeProvider({"answer.txt": "42"}), request, task, tmp_path / "artifacts", lambda: False
        )
    )
    assert result.status == "success"
    assert (repo / "answer.txt").read_text() == "42"


def test_verifier_never_calls_provider(repo: Path, tmp_path: Path) -> None:
    task, request = task_request(repo, Role.VERIFIER)
    with pytest.raises(ValueError, match="never a provider"):
        asyncio.run(
            execute_role(
                FakeProvider({"answer.txt": "42"}),
                request,
                task,
                tmp_path / "artifacts",
                lambda: False,
            )
        )
    assert (repo / "answer.txt").read_text() == "41"


def test_digest_detects_untracked_content_and_rejects_symlink(repo: Path) -> None:
    before = workspace_digest(repo)
    (repo / "new.txt").write_text("untracked")
    assert workspace_digest(repo) != before
    try:
        (repo / "linked.txt").symlink_to(repo / "answer.txt")
    except OSError:
        pytest.skip("Host does not permit symlinks")
    with pytest.raises(ValueError, match="Symlink"):
        workspace_digest(repo)


@pytest.mark.parametrize("elapsed", [3.0, 11.0])
def test_snapshot_setup_consumes_provider_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    elapsed: float,
) -> None:
    from types import SimpleNamespace

    from eng.agents import runtime

    task, request = task_request(tmp_path, Role.PLANNER)
    request = request.model_copy(update={"timeout_seconds": 10.0})
    ticks = iter([100.0, 100.0 + elapsed])
    monkeypatch.setattr(runtime, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(
        runtime,
        "_prepare_snapshot",
        lambda *_: (
            tmp_path,
            tmp_path / "snapshot",
            "before",
            "snapshot-before",
        ),
    )
    monkeypatch.setattr(runtime, "_mutation", lambda *_: None)

    class Capture(FakeProvider):
        called = False

        async def execute(
            self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
        ) -> ProviderResult:
            self.called = True
            assert request.timeout_seconds == 7.0
            return ProviderResult(status="success")

    provider = Capture()
    result = asyncio.run(
        execute_role(provider, request, task, tmp_path / "artifacts", lambda: False)
    )
    assert result.status == ("timeout" if elapsed > 10 else "success")
    assert provider.called == (elapsed < 10)
