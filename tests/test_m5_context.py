import os
from pathlib import Path

import pytest

from eng.context.cache import ContextCache
from eng.context.packet import build_packet
from eng.core.models import ProjectConfig, RepairAttempt, Role, RoleHandoff, Task, TaskSpec
from eng.execution.workspace import git


def _task(repo: Path) -> Task:
    return Task(
        project=repo,
        workspace=repo,
        config=ProjectConfig(instructions=[]),
        spec=TaskSpec(
            description="Fix fixture", acceptance=["Correct result"], context_paths=["answer.txt"]
        ),
    )


def test_current_bytes_same_size_and_mtime(repo: Path) -> None:
    task = _task(repo)
    cache = ContextCache()
    original = build_packet(task, cache=cache)
    assert original == build_packet(task)
    assert original == build_packet(task, cache=cache)
    assert cache.snapshot()["hits"] == 1
    path = repo / "answer.txt"
    timestamp = path.stat()
    path.write_text("99", encoding="utf-8")
    os.utime(path, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
    updated = build_packet(task, cache=cache)
    assert updated == build_packet(task)
    assert "99" in updated and updated != original
    assert cache.snapshot()["misses"] == 2


def test_membership_policy_deletion_and_move_revalidated(repo: Path) -> None:
    task = _task(repo)
    cache = ContextCache()
    assert "\n41" in build_packet(task, cache=cache)
    task.config.protected_paths.append("answer.txt")
    assert "\n41" not in build_packet(task, cache=cache)
    assert cache.snapshot()["entries"] == 0
    task.config.protected_paths.remove("answer.txt")
    git(repo, "rm", "--cached", "answer.txt")
    assert "\n41" not in build_packet(task, cache=cache)
    git(repo, "add", "answer.txt")
    (repo / "answer.txt").rename(repo / "moved.txt")
    assert "\n41" not in build_packet(task, cache=cache)
    task.spec.context_paths = ["moved.txt"]
    assert "\n41" not in build_packet(task, cache=cache)
    git(repo, "add", "moved.txt")
    assert "\n41" in build_packet(task, cache=cache)
    (repo / "moved.txt").unlink()
    assert "\n41" not in build_packet(task, cache=cache)


def test_workspace_head_and_limit_scopes(repo: Path, tmp_path: Path) -> None:
    task = _task(repo)
    cache = ContextCache()
    build_packet(task, cache=cache)
    git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=t@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "new head",
    )
    build_packet(task, cache=cache)
    assert cache.snapshot()["misses"] == 2
    task.spec.budgets.context_chars += 1
    build_packet(task, cache=cache)
    assert cache.snapshot()["misses"] == 3
    other = tmp_path / "other"
    git(repo, "worktree", "add", "--detach", str(other))
    task.workspace = other
    assert build_packet(task, cache=cache) == build_packet(task)
    assert cache.snapshot()["misses"] == 4


def test_symlink_rechecked_after_cache_population(repo: Path) -> None:
    task = _task(repo)
    cache = ContextCache()
    build_packet(task, cache=cache)
    (repo / "answer.txt").unlink()
    try:
        (repo / "answer.txt").symlink_to(repo / "check.py")
    except OSError:
        pytest.skip("OS does not grant symlink creation")
    with pytest.raises(ValueError, match="Symlink"):
        build_packet(task, cache=cache)


def test_cache_is_bounded_and_clearable(tmp_path: Path) -> None:
    cache = ContextCache(max_bytes=5, max_entries=1)
    path = tmp_path / "data"
    for value in ("aaaa", "bbbb", "ccc"):
        path.write_text(value, encoding="utf-8")
        assert cache.read(path, 10, scope=(value,)) == value
        assert cache.snapshot()["retained_bytes"] <= 5
        assert cache.snapshot()["entries"] <= 1
    path.write_text("too much data", encoding="utf-8")
    cache.read(path, 20, scope=())
    cache.clear()
    assert cache.snapshot()["entries"] == 0
    with pytest.raises(ValueError):
        ContextCache(max_bytes=0)


def test_reviewer_excludes_both_implementation_narratives_and_nested_repair(repo: Path) -> None:
    task = _task(repo)
    engineer = RoleHandoff(role=Role.ENGINEER, summary="ENGINEER_PRIVATE_PROSE", invocation_id="e")
    debugger = RoleHandoff(role=Role.DEBUGGER, summary="DEBUGGER_PRIVATE_PROSE", invocation_id="d")
    task.handoffs = [engineer, debugger]
    task.repairs = [RepairAttempt(number=1, failure_signature="failure", handoff=debugger)]
    packet = build_packet(task, Role.REVIEWER, cache=ContextCache())
    assert "ENGINEER_PRIVATE_PROSE" not in packet
    assert "DEBUGGER_PRIVATE_PROSE" not in packet
    assert "failure_signature" in packet
    assert "DEBUGGER_PRIVATE_PROSE" in build_packet(task, Role.DEBUGGER)


def test_nul_git_filename_whitespace_preserved(repo: Path) -> None:
    name = " leading space.txt"
    (repo / name).write_text("WHITESPACE_REFERENCE", encoding="utf-8")
    git(repo, "add", "--", name)
    assert name in git(repo, "ls-files", "-z").split("\0")
    task = _task(repo)
    task.spec.context_paths = [name]
    assert "WHITESPACE_REFERENCE" in build_packet(task, cache=ContextCache())
    (repo / name).write_text("changed", encoding="utf-8")
    assert name in git(repo, "diff", "--name-only", "-z").split("\0")


def test_dynamic_objective_and_evidence_are_never_cached(repo: Path) -> None:
    task = _task(repo)
    cache = ContextCache()
    original = build_packet(task, evidence="failure-one", cache=cache)
    task.spec.description = "New fixture"
    updated = build_packet(task, evidence="failure-two", cache=cache)
    assert updated == build_packet(task, evidence="failure-two")
    assert "failure-one" not in updated and "failure-two" in updated
    assert updated != original
    with pytest.raises(ValueError, match="bounded"):
        cache.read(repo / "answer.txt", -1, scope=())
