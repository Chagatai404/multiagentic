"""E3: explicit classification routing of models and providers."""

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml
from typer.testing import CliRunner

from eng.cli import app
from eng.core.engine import Engine
from eng.core.models import Budgets, Capabilities, ProjectConfig, Role, State, Task, TaskSpec
from eng.core.plan import PlanSpec
from eng.projects.config import load_config
from eng.providers.fake import FakeProvider
from eng.scheduling.runner import PlanRunner
from eng.storage.store import Store

ROUTES = [
    {
        "label": "strict-review",
        "when": {"risks": ["medium", "high"], "roles": ["reviewer"]},
        "model": "strong",
    },
    {"label": "cheap-small", "when": {"complexities": ["small"]}, "model": "mini"},
]


def configure(repo: Path, **values: Any) -> ProjectConfig:
    path = repo / ".engineering" / "project.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document.update(values)
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    identity = ["-c", "user.name=t", "-c", "user.email=t@e.invalid"]
    for command in (["add", "."], [*identity, "commit", "-qm", "routes"]):
        subprocess.run(["git", "-C", str(repo), *command], check=True, capture_output=True)
    return load_config(repo)


def kinds(store: Store, task_id: str, kind: str) -> list[dict[str, Any]]:
    return [json.loads(e["payload"]) for e in store.events(task_id) if e["kind"] == kind]


def run_task(repo: Path, provider: FakeProvider, **spec: Any) -> tuple[Store, Task]:
    store = Store(repo)
    task = Task(
        project=repo,
        spec=TaskSpec(
            description="Fix the answer",
            acceptance=["answer is 42"],
            provider="fake",
            budgets=Budgets(model_calls=3),
            **spec,
        ),
        config=load_config(repo),
    )
    store.create(task)
    return store, asyncio.run(Engine(store, provider).execute(task.id))


def test_models_follow_routes_and_escalation_reroutes_later_roles(repo: Path) -> None:
    configure(repo, routing=ROUTES, role_models={"reviewer": "configured"})
    # The edit touches a storage path, escalating risk to medium so review becomes due.
    provider = FakeProvider({"answer.txt": "42", "storage/notes.txt": "x"})
    store, task = run_task(repo, provider)
    assert task.state == State.COMPLETED
    models = [(r.role, r.model) for r in store.invocations(task.id)]
    assert models == [(Role.ENGINEER, "mini"), (Role.REVIEWER, "strong")]
    routed = kinds(store, task.id, "model_routed")
    assert [(e["role"], e["route"], e["risk"]) for e in routed] == [
        ("engineer", "cheap-small", "low"),
        ("reviewer", "strict-review", "medium"),
    ]


def test_explicit_task_model_wins_over_routes(repo: Path) -> None:
    configure(repo, routing=ROUTES)
    store, task = run_task(repo, FakeProvider({"answer.txt": "42"}), model="pinned")
    assert task.state == State.COMPLETED
    assert [r.model for r in store.invocations(task.id)] == ["pinned"]
    assert kinds(store, task.id, "model_routed") == []


class NoModelProvider(FakeProvider):
    capabilities = Capabilities(kind="fake", file_editing=True)


def test_routes_the_provider_cannot_honour_are_skipped(repo: Path) -> None:
    configure(repo, routing=ROUTES, role_models={"engineer": "configured"})
    store, task = run_task(repo, NoModelProvider({"answer.txt": "42"}))
    assert task.state == State.COMPLETED
    assert [r.model for r in store.invocations(task.id)] == ["configured"]
    (skipped,) = kinds(store, task.id, "route_skipped")
    assert skipped["route"] == "cheap-small" and "no model selection" in skipped["reason"]


def test_no_routes_keeps_existing_selection(repo: Path) -> None:
    store, task = run_task(repo, FakeProvider({"answer.txt": "42"}))
    assert task.state == State.COMPLETED
    assert [r.model for r in store.invocations(task.id)] == [None]
    assert kinds(store, task.id, "model_routed") == kinds(store, task.id, "route_skipped") == []


def test_cli_run_routes_the_provider_only_without_an_explicit_choice(repo: Path) -> None:
    configure(
        repo,
        provider="codex",
        routing=[{"label": "fixtures", "when": {"complexities": ["small"]}, "provider": "fake"}],
    )
    cli = CliRunner()
    arguments = ["run", "Fix the answer", "--accept", "42", "-p", str(repo)]
    result = cli.invoke(app, [*arguments, "--fake-change", "answer.txt=42"])
    assert result.exit_code == 0, result.output
    task = json.loads(result.output)
    assert task["spec"]["provider"] == "fake"
    store = Store(repo)
    (event,) = kinds(store, task["id"], "provider_routed")
    assert event == {"provider": "fake", "route": "fixtures", "index": 0}
    explicit = cli.invoke(app, [*arguments, "--provider", "codex", "--fake-change", "a=b"])
    assert explicit.exit_code != 0 and "--fake-change is only available" in explicit.output


def test_plan_nodes_freeze_routed_providers_and_explicit_ones_win(plan_repo: Path) -> None:
    configure(
        plan_repo,
        routing=[
            {"label": "complex", "when": {"complexities": ["complex"]}, "provider": "claude"},
            {"label": "default", "provider": "fake"},
        ],
    )
    spec = PlanSpec.model_validate(
        {
            "name": "routes",
            "nodes": [
                {"id": "a", "description": "Add a", "acceptance": ["ok"], "owns": ["files/a.txt"]},
                {
                    "id": "b",
                    "description": "Complex redesign",
                    "acceptance": ["ok"],
                    "owns": ["files/b.txt"],
                },
                {
                    "id": "c",
                    "description": "Add c",
                    "acceptance": ["ok"],
                    "owns": ["files/c.txt"],
                    "provider": "codex",
                },
            ],
        }
    )
    seen: list[str] = []

    def factory(name: str, config: ProjectConfig) -> FakeProvider:
        seen.append(name)
        return FakeProvider()

    store = Store(plan_repo)
    plan = PlanRunner(plan_repo, factory).create(store, spec)
    assert {n.spec.id: n.effective_provider for n in plan.nodes} == {
        "a": "fake",
        "b": "claude",
        "c": "codex",
    }
    assert set(seen) == {"fake", "claude", "codex"}
    plan_file = write(plan_repo, spec)
    preview = CliRunner().invoke(app, ["plan", "preview", str(plan_file), "-p", str(plan_repo)])
    assert preview.exit_code == 0, preview.output
    providers = {n["id"]: n["provider"] for n in json.loads(preview.output)["nodes"]}
    assert providers == {"a": "fake", "b": "claude", "c": "codex"}


def write(repo: Path, spec: PlanSpec) -> Path:
    path = repo.parent / "plan.yaml"
    path.write_text(yaml.safe_dump(spec.model_dump(mode="json", exclude_none=True)), "utf-8")
    return path
