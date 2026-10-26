import pytest
from pydantic import ValidationError

from eng.core.models import State
from eng.core.plan import (
    MAX_CONCURRENCY,
    NodeStatus,
    PlanSpec,
    PlanStatus,
    ancestors,
    derive_plan_status,
    node_status_for_task,
    normalize_pattern,
    outside_ownership,
    path_owned,
    patterns_may_overlap,
    ready_nodes,
    skipped_nodes,
    topological_order,
)


def node(node_id: str, owns: list[str], depends_on: list[str] | None = None) -> dict[str, object]:
    return {
        "id": node_id,
        "description": f"do {node_id}",
        "acceptance": ["done"],
        "owns": owns,
        "depends_on": depends_on or [],
    }


def plan(*nodes: dict[str, object], **extra: object) -> PlanSpec:
    return PlanSpec.model_validate({"name": "p", "nodes": list(nodes), **extra})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("src/", "src/**"),
        ("./a\\b.py", "a/b.py"),
        ("  docs/x.md ", "docs/x.md"),
    ],
)
def test_normalize_pattern(raw: str, expected: str) -> None:
    assert normalize_pattern(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "  ", "/abs", "C:/x", "../up", "a/../b", ".git/config", "a/.GIT/x", ".engineering/x"]
    + ["a//b"],
)
def test_unsafe_patterns_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_pattern(raw)


@pytest.mark.parametrize(
    ("first", "second", "overlap"),
    [
        ("src/a.py", "src/b.py", False),
        ("src/a.py", "src/a.py", True),
        ("src/**", "docs/**", False),
        ("src/**", "src/a.py", True),
        ("src/a/**", "src/b/**", False),
        ("**", "anything/at/all.txt", True),
        ("**/*.py", "docs/**", True),  # a .py file may live under docs: cannot show disjoint
        ("src/*.py", "src/*.js", True),  # two wildcards: conservative
        ("src/*.py", "src/readme.md", False),
        ("src/*.py", "src/main.py", True),
        ("SRC/A.py", "src/a.py", True),  # case-insensitive
        ("a/b", "a/b/c", False),  # a file cannot also be a directory
        ("a/**", "a", True),  # ** can match zero directories
    ],
)
def test_overlap_analysis(first: str, second: str, overlap: bool) -> None:
    assert patterns_may_overlap(first, second) is overlap
    assert patterns_may_overlap(second, first) is overlap


def test_path_ownership_matching() -> None:
    patterns = ["src/app/**", "README.md", "tests/test_*.py"]
    assert path_owned("src/app/deep/x.py", patterns)
    assert path_owned("README.md", patterns)
    assert path_owned("Tests/test_a.py", patterns)
    assert not path_owned("src/other.py", patterns)
    assert not path_owned("tests/sub/test_a.py", patterns)
    assert not path_owned("", patterns)
    assert outside_ownership(["README.md", "setup.py"], patterns) == ["setup.py"]


def test_valid_plan_orders_and_ancestors() -> None:
    spec = plan(
        node("c", ["c/**"], ["b"]),
        node("a", ["a/**"]),
        node("b", ["b/**"], ["a"]),
    )
    assert ancestors(spec)["c"] == {"a", "b"}
    assert topological_order(spec) == ["a", "b", "c"]
    assert spec.concurrency == MAX_CONCURRENCY


@pytest.mark.parametrize(
    ("nodes", "message"),
    [
        ([node("a", ["x"]), node("a", ["y"])], "unique"),
        ([node("a", ["x"], ["ghost"])], "unknown"),
        ([node("a", ["x"], ["a"])], "itself"),
        ([node("a", ["x"], ["b"]), node("b", ["y"], ["a"])], "cycle"),
        ([node("a", ["src/**"]), node("b", ["src/x.py"])], "overlap"),
        ([node("a", ["x"], ["b", "b"]), node("b", ["y"])], "duplicate"),
    ],
)
def test_invalid_plans(nodes: list[dict[str, object]], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        plan(*nodes)


def test_dependency_orders_overlapping_ownership() -> None:
    # Ordered nodes never run together, so sharing a file is legitimate.
    spec = plan(node("a", ["src/x.py"]), node("b", ["src/x.py"], ["a"]))
    assert [n.id for n in spec.nodes] == ["a", "b"]


def test_transitive_order_allows_overlap() -> None:
    plan(
        node("a", ["shared.py"]),
        node("b", ["b/**"], ["a"]),
        node("c", ["shared.py"], ["b"]),
    )


@pytest.mark.parametrize("value", [0, 4, -1])
def test_concurrency_is_bounded_by_three(value: int) -> None:
    with pytest.raises(ValidationError):
        plan(node("a", ["x"]), concurrency=value)


def test_node_count_and_id_limits() -> None:
    with pytest.raises(ValidationError):
        plan(node("Bad Id", ["x"]))
    many = [node(f"n{i}", [f"d{i}/**"]) for i in range(51)]
    with pytest.raises(ValidationError):
        plan(*many)


def statuses(**values: NodeStatus) -> dict[str, NodeStatus]:
    return dict(values)


def test_ready_nodes_waits_for_integrated_dependencies_and_slots() -> None:
    spec = plan(
        node("a", ["a/**"]),
        node("b", ["b/**"]),
        node("c", ["c/**"]),
        node("d", ["d/**"]),
        node("e", ["e/**"], ["a"]),
    )
    pending = {n.id: NodeStatus.PENDING for n in spec.nodes}
    assert ready_nodes(spec, pending, slots_free=3) == ["a", "b", "c"]
    assert ready_nodes(spec, pending, slots_free=10) == ["a", "b", "c"]  # never above three
    assert ready_nodes(spec, pending, slots_free=0) == []
    pending["a"] = NodeStatus.VERIFIED  # completed but not yet integrated
    assert "e" not in ready_nodes(spec, pending, slots_free=3)
    pending["a"] = NodeStatus.INTEGRATED
    assert ready_nodes(spec, pending, slots_free=3) == ["b", "c", "d"]
    assert "e" in ready_nodes(spec, {**pending, "b": NodeStatus.INTEGRATED}, slots_free=3)


def test_problem_stops_new_launches_unless_keep_going() -> None:
    spec = plan(node("a", ["a/**"]), node("b", ["b/**"]))
    state = {"a": NodeStatus.BLOCKED, "b": NodeStatus.PENDING}
    assert ready_nodes(spec, state, slots_free=3) == []
    assert ready_nodes(spec, state, slots_free=3, keep_going=True) == ["b"]


def test_skipped_nodes_follow_failed_ancestors() -> None:
    spec = plan(
        node("a", ["a/**"]),
        node("b", ["b/**"], ["a"]),
        node("c", ["c/**"], ["b"]),
        node("d", ["d/**"]),
    )
    state = {
        "a": NodeStatus.FAILED,
        "b": NodeStatus.PENDING,
        "c": NodeStatus.PENDING,
        "d": NodeStatus.PENDING,
    }
    assert skipped_nodes(spec, state) == ["b", "c"]
    state["a"] = NodeStatus.BLOCKED  # blocked can be resumed: nothing is skipped
    assert skipped_nodes(spec, state) == []


@pytest.mark.parametrize(
    ("state", "status"),
    [
        (State.COMPLETED, NodeStatus.VERIFIED),
        (State.FAILED, NodeStatus.FAILED),
        (State.CANCELLED, NodeStatus.CANCELLED),
        (State.PAUSED, NodeStatus.PAUSED),
        (State.BLOCKED, NodeStatus.BLOCKED),
        (State.IMPLEMENTING, NodeStatus.RUNNING),
        (State.CREATED, NodeStatus.RUNNING),
    ],
)
def test_task_state_maps_to_node_status(state: State, status: NodeStatus) -> None:
    assert node_status_for_task(state) == status


@pytest.mark.parametrize(
    ("values", "promoted", "expected"),
    [
        ([NodeStatus.PENDING, NodeStatus.PENDING], False, PlanStatus.CREATED),
        ([NodeStatus.INTEGRATED, NodeStatus.INTEGRATED], False, PlanStatus.READY),
        ([NodeStatus.INTEGRATED, NodeStatus.INTEGRATED], True, PlanStatus.PROMOTED),
        ([NodeStatus.RUNNING, NodeStatus.FAILED], False, PlanStatus.RUNNING),
        ([NodeStatus.VERIFIED, NodeStatus.PENDING], False, PlanStatus.RUNNING),
        ([NodeStatus.FAILED, NodeStatus.BLOCKED], False, PlanStatus.FAILED),
        ([NodeStatus.CANCELLED, NodeStatus.SKIPPED], False, PlanStatus.CANCELLED),
        ([NodeStatus.BLOCKED, NodeStatus.PAUSED], False, PlanStatus.BLOCKED),
        ([NodeStatus.PAUSED, NodeStatus.PENDING], False, PlanStatus.PAUSED),
        ([NodeStatus.INTEGRATED, NodeStatus.PENDING], False, PlanStatus.PAUSED),
    ],
)
def test_derive_plan_status(values: list[NodeStatus], promoted: bool, expected: PlanStatus) -> None:
    assert derive_plan_status(values, promoted=promoted) == expected
