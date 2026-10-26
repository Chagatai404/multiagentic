"""Reproducible offline workflow fixtures, not measurements of model intelligence."""

import asyncio
import math
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eng.context.cache import ContextCache
from eng.context.packet import build_packet
from eng.core.engine import Engine
from eng.core.models import (
    Budgets,
    Check,
    ProjectConfig,
    ProviderRequest,
    ProviderResult,
    Role,
    State,
    Task,
    TaskSpec,
)
from eng.execution.workspace import git, prepare, safe_path
from eng.providers.fake import FakeProvider
from eng.storage.store import Store

SCENARIOS = (
    "small_bug",
    "medium_feature",
    "large_refactor",
    "failing_tests",
    "cross_module_integration",
    "architecture_violation",
)
ARMS = ("A_single_coding", "B_coding_checks", "C_adaptive")


@dataclass(frozen=True)
class Fixture:
    description: str
    initial: dict[str, str]
    first: dict[str, str]
    repaired: dict[str, str]
    evaluator: str


def _fixture(scenario: str, seed: int) -> Fixture:
    value = random.Random(seed).randrange(7, 100)
    initial = {"calc.py": "def answer():\n    return 0\n"}
    final = {"calc.py": f"def answer():\n    return {value}\n"}
    evaluator = f"from calc import answer\nassert answer() == {value}\n"
    descriptions = {
        "small_bug": "Fix the small arithmetic bug",
        "medium_feature": "Implement bounded numeric feature",
        "large_refactor": "Refactor architecture across twelve modules",
        "failing_tests": "Repair the failing numeric tests",
        "cross_module_integration": "Implement cross-module integration",
        "architecture_violation": "Repair architecture dependency direction",
    }
    if scenario == "medium_feature":
        initial = {"calc.py": "def clamp(x):\n    return x\n"}
        final = {"calc.py": f"def clamp(x):\n    return max(0, min({value}, x))\n"}
        evaluator = (
            "from calc import clamp\n"
            f"assert [clamp(x) for x in (-1, 0, {value}, {value + 1})] == [0,0,{value},{value}]\n"
        )
    elif scenario == "large_refactor":
        initial = {f"part{i}.py": f"VALUE = {i}\n" for i in range(12)}
        initial["calc.py"] = "def answer():\n    return 0\n"
        final = {f"part{i}.py": f"def value():\n    return {i}\n" for i in range(12)}
        final["calc.py"] = (
            "\n".join(f"import part{i}" for i in range(12))
            + "\ndef answer():\n    return "
            + "+".join(f"part{i}.value()" for i in range(12))
            + "\n"
        )
        evaluator = "from calc import answer\nassert answer() == 66\n"
        evaluator += "\n".join(
            f"import part{i}\nassert part{i}.value() == {i}\nassert not hasattr(part{i}, 'VALUE')"
            for i in range(12)
        )
    elif scenario == "cross_module_integration":
        initial["consumer.py"] = (
            "from calc import answer\ndef render():\n    return str(answer())\n"
        )
        final["consumer.py"] = (
            "from calc import answer\ndef render():\n    return 'value=' + str(answer())\n"
        )
        evaluator += f"from consumer import render\nassert render() == 'value={value}'\n"
    elif scenario == "architecture_violation":
        initial = {"storage.py": f"VALUE = {value}\n", "calc.py": "def answer():\n    return 0\n"}
        # A numerically correct but invalid direction is caught by the same acceptance in every arm.
        evaluator += (
            "import ast\nfrom pathlib import Path\n"
            "tree = ast.parse(Path('calc.py').read_text())\n"
            "assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(tree))\n"
        )
    first = dict(final)
    if scenario == "failing_tests":
        first = {"calc.py": f"def answer():\n    return {value - 1}\n"}
    elif scenario == "cross_module_integration":
        first.pop("consumer.py")
    elif scenario == "architecture_violation":
        first = {"calc.py": "from storage import VALUE\ndef answer():\n    return VALUE\n"}
    return Fixture(descriptions[scenario], initial, first, final, evaluator)


class _ScriptedProvider(FakeProvider):
    """Edits are prewritten fixtures: no live client or inference is performed."""

    def __init__(self, fixture: Fixture) -> None:
        super().__init__(fixture.first)
        self.fixture = fixture

    async def execute(
        self,
        request: ProviderRequest,
        artifact_dir: Path,
        cancelled: Callable[[], bool],
    ) -> ProviderResult:
        if request.role == Role.DEBUGGER:
            return await FakeProvider(self.fixture.repaired).execute(
                request, artifact_dir, cancelled
            )
        return await super().execute(request, artifact_dir, cancelled)


@contextmanager
def _ceiling(directory: Path) -> Iterator[None]:
    previous = os.environ.get("GIT_CEILING_DIRECTORIES")
    os.environ["GIT_CEILING_DIRECTORIES"] = str(directory)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("GIT_CEILING_DIRECTORIES", None)
        else:
            os.environ["GIT_CEILING_DIRECTORIES"] = previous


def _write(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        target = safe_path(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _accept(evaluator: Path, workspace: Path) -> bool:
    return (
        subprocess.run(
            [sys.executable, str(evaluator)],
            cwd=workspace,
            capture_output=True,
            timeout=15,
            check=False,
        ).returncode
        == 0
    )


def _row(parent: Path, scenario: str, repetition: int, seed: int, arm: str) -> dict[str, Any]:
    fixture = _fixture(scenario, seed)
    root = parent / "p"
    root.mkdir()
    git(root, "init", "-b", "main")
    _write(root, fixture.initial)
    (root / ".gitignore").write_text(".engineering/\n__pycache__/\n", encoding="utf-8")
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Benchmark",
        "-c",
        "user.email=offline@example.invalid",
        "commit",
        "-m",
        "seeded fixture",
    )
    base = git(root, "rev-parse", "HEAD")
    original = {name: (root / name).read_bytes() for name in fixture.initial}
    evaluator = parent / "accept.py"
    evaluator.write_text(
        "import sys\nfrom pathlib import Path\nsys.dont_write_bytecode=True\n"
        "sys.path.insert(0, str(Path.cwd()))\n" + fixture.evaluator,
        encoding="utf-8",
    )
    evaluator_bytes = evaluator.read_bytes()
    if _accept(evaluator, root):
        raise ValueError("Seeded fixture must fail initial acceptance")
    config = ProjectConfig(
        name="offline-fixture",
        instructions=[],
        checks=[
            Check(
                name="acceptance",
                argv=[sys.executable, str(evaluator)],
                confirmed=True,
                timeout_seconds=15,
            ),
        ],
    )
    task = Task(
        id="fixture",
        project=root,
        config=config,
        spec=TaskSpec(
            description=fixture.description,
            acceptance=["Pass external acceptance"],
            provider="fake",
            budgets=Budgets(model_calls=8, wall_seconds=90),
            context_paths=list(fixture.initial),
        ),
    )
    provider = _ScriptedProvider(fixture)
    started = time.perf_counter()
    first_pass = False
    repairs = 0
    if arm == ARMS[2]:
        store = Store(root)
        try:
            store.create(task)
            result = asyncio.run(Engine(store, provider).execute(task.id))
        finally:
            store.close()
        workspace = result.workspace
        assert workspace is not None
        declared = result.state == State.COMPLETED
        repairs = len(result.repairs)
        first_pass = declared and repairs == 0
        calls = result.provider_calls
        state = result.state.value
    else:
        workspace = prepare(task)
        request = ProviderRequest(
            task_id=task.id,
            execution_id="fixture",
            workspace=workspace,
            prompt=build_packet(task),
            timeout_seconds=15,
        )
        result_provider = asyncio.run(
            provider.execute(request, parent / "artifacts", lambda: False)
        )
        calls = 1
        declared = result_provider.status == "success"
        if arm == ARMS[1]:
            declared = declared and _accept(evaluator, workspace)
        state = "accepted" if declared else "rejected"
    elapsed = time.perf_counter() - started
    assessment_started = time.perf_counter()
    passed = _accept(evaluator, workspace)
    assessment_seconds = time.perf_counter() - assessment_started
    if arm != ARMS[2]:
        first_pass = passed
    unchanged = (
        git(root, "rev-parse", "HEAD") == base
        and not git(root, "status", "--porcelain", "--untracked-files=normal")
        and all((root / name).read_bytes() == value for name, value in original.items())
    )
    if not unchanged or evaluator.read_bytes() != evaluator_bytes:
        raise ValueError("Benchmark mutated source checkout or external acceptance")
    return dict(
        scenario=scenario,
        repetition=repetition,
        seed=seed,
        arm=arm,
        verified_success=passed,
        first_pass_success=first_pass,
        declared_success=declared,
        provider_calls=calls,
        repairs=repairs,
        human_intervention_required=int(not declared),
        human_intervention=0,
        unnecessary_invocations=None,
        escaped_defects=int(declared and not passed),
        elapsed_seconds=elapsed,
        external_assessment_seconds=assessment_seconds,
        state=state,
        input_tokens=None,
        output_tokens=None,
        cost_usd=None,
        source_unchanged=unchanged,
    )


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    durations = sorted(float(row["elapsed_seconds"]) for row in rows)
    return {
        "runs": len(rows),
        **{
            name: sum(int(row[name]) for row in rows)
            for name in (
                "verified_success",
                "first_pass_success",
                "provider_calls",
                "repairs",
                "human_intervention",
                "human_intervention_required",
                "escaped_defects",
            )
        },
        "verified_success_rate": sum(bool(r["verified_success"]) for r in rows) / len(rows),
        "first_pass_success_rate": sum(bool(r["first_pass_success"]) for r in rows) / len(rows),
        "escape_rate": sum(int(r["escaped_defects"]) for r in rows) / len(rows),
        "tokens_per_verified_success": None,
        "cost_usd_per_verified_success": None,
        "unnecessary_invocations": None,
        "elapsed_median_seconds": statistics.median(durations),
        "elapsed_p95_seconds": durations[max(0, math.ceil(len(durations) * 0.95) - 1)],
        "input_tokens": None,
        "output_tokens": None,
        "cost_usd": None,
    }


def context_microbenchmark(task: Task, *, iterations: int = 20) -> dict[str, Any]:
    """Measure packet construction including Git, current hashes and redaction."""
    if (
        isinstance(iterations, bool)
        or not isinstance(iterations, int)
        or not 1 <= iterations <= 1000
    ):
        raise ValueError("iterations must be an integer from 1 through 1000")
    cache = ContextCache()
    cached_times: list[float] = []
    plain_times: list[float] = []
    for index in range(iterations):
        packets = []
        # Alternate order to avoid giving one path every cold filesystem read.
        for cached in (False, True) if index % 2 == 0 else (True, False):
            started = time.perf_counter()
            packets.append(build_packet(task, cache=cache if cached else None))
            elapsed = time.perf_counter() - started
            (cached_times if cached else plain_times).append(elapsed)
        if packets[0] != packets[1]:
            raise ValueError("Cached and uncached packets differ")
    return {
        "iterations": iterations,
        "equal_packets": True,
        "cache": cache.snapshot(),
        "cached_median_seconds": statistics.median(cached_times),
        "uncached_median_seconds": statistics.median(plain_times),
        "cached_seconds": cached_times,
        "uncached_seconds": plain_times,
        "scope": "Local packet construction only; no inference or token/cost saving claim",
    }


def run_benchmark(
    *,
    repetitions: int = 1,
    seed: int = 0,
    scenarios: list[str] | None = None,
) -> dict[str, Any]:
    """Run six bounded, seeded fixture categories against identical external acceptance.

    Synchronous; call outside an active asyncio loop. A/B are standalone benchmark
    paths. C invokes the unchanged production Engine safeguards. Temporary repositories
    are disposable and never use the caller's checkout as their source.
    """
    if (
        isinstance(repetitions, bool)
        or not isinstance(repetitions, int)
        or not 1 <= repetitions <= 10
    ):
        raise ValueError("repetitions must be an integer from 1 through 10")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer from 0 through 2**32-1")
    selected = list(SCENARIOS) if scenarios is None else scenarios
    if (
        not isinstance(selected, list)
        or not selected
        or len(selected) > len(SCENARIOS)
        or any(not isinstance(item, str) or item not in SCENARIOS for item in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError("scenarios must be unique known scenario names")
    order = [
        (scenario, repetition, arm)
        for repetition in range(repetitions)
        for scenario in selected
        for arm in ARMS
    ]
    random.Random(seed).shuffle(order)
    rows = []
    # A short temp root avoids deep role-snapshot Git object paths on Windows.
    with tempfile.TemporaryDirectory(prefix="eb-") as temporary:
        parent = Path(temporary).resolve()
        with _ceiling(parent):
            for index, (scenario, repetition, arm) in enumerate(order):
                directory = parent / str(index)
                directory.mkdir()
                rows.append(_row(directory, scenario, repetition, seed + repetition, arm))
            micro = parent / "micro"
            micro.mkdir()
            git(micro, "init", "-b", "main")
            _write(micro, {"reference.txt": "A bounded reference sentence.\n" * 2000})
            git(micro, "add", ".")
            git(
                micro,
                "-c",
                "user.name=Benchmark",
                "-c",
                "user.email=offline@example.invalid",
                "commit",
                "-m",
                "context fixture",
            )
            task = Task(
                project=micro,
                workspace=micro,
                config=ProjectConfig(instructions=[]),
                spec=TaskSpec(
                    description="Fix fixture",
                    acceptance=["Same packet"],
                    context_paths=["reference.txt"],
                ),
            )
            context = context_microbenchmark(task)
    return {
        "schema_version": 1,
        "fixture_kind": "deterministic_scripted_edits",
        "limitations": [
            "Scripted fixture edits do not measure model intelligence or real-model quality.",
            "human_intervention_required is a next-action proxy; actual human actions are zero.",
            "Workflow time excludes external assessment; B/C include their own checks.",
            "Unnecessary invocations are unknown: this fixture has no objective call oracle.",
            "Usage and cost remain unknown; no live model calls are made.",
            "P95 uses nearest rank; small samples do not support population claims.",
        ],
        "seed": seed,
        "repetitions": repetitions,
        "scenarios": selected,
        "raw": rows,
        "summary": {arm: _summary([row for row in rows if row["arm"] == arm]) for arm in ARMS},
        "context_microbenchmark": context,
    }
