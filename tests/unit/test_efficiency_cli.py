import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from eng.cli import app
from eng.core.engine import Engine
from eng.core.models import (
    Budgets,
    ClassificationOverrides,
    ProjectConfig,
    ProviderRequest,
    ProviderResult,
    Risk,
    Role,
    RoleLimits,
    State,
    Task,
    TaskSpec,
    Usage,
    VerificationResult,
)
from eng.projects.config import load_config
from eng.providers.fake import FakeProvider
from eng.storage.store import Store


class ReviewTwice(FakeProvider):
    def __init__(self, usage: Usage | None = None) -> None:
        super().__init__({"answer.txt": "42"})
        self.reviews = 0
        self.usage = usage or Usage()

    async def execute(
        self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
    ) -> ProviderResult:
        if request.role == Role.REVIEWER:
            self.reviews += 1
            return ProviderResult(
                status="success",
                usage=self.usage,
                summary=json.dumps(
                    {
                        "summary": "Review",
                        "verdict": "changes_requested" if self.reviews == 1 else "pass",
                        "findings": ["Clarify the implementation"] if self.reviews == 1 else [],
                    }
                ),
            )
        result = await super().execute(request, artifact_dir, cancelled)
        result.usage = self.usage
        return result


def test_role_review_extension_resumes_within_overall_cap(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(repo)
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(
            description="Fix answer",
            acceptance=["42"],
            provider="fake",
            classification_overrides=ClassificationOverrides(risk=Risk.MEDIUM),
            budgets=Budgets(model_calls=4, role_limits={Role.REVIEWER: RoleLimits(model_calls=1)}),
        ),
    )
    store.create(task)
    provider = ReviewTwice()
    paused = asyncio.run(Engine(store, provider).execute(task.id))
    assert paused.state == State.PAUSED and paused.next_role == Role.REVIEWER
    assert provider.reviews == 1 and paused.provider_calls == 3
    store.close()

    monkeypatch.setattr("eng.cli.provider_for", lambda *args: provider)
    result = CliRunner().invoke(
        app, ["resume", task.id, "-p", str(repo), "--extend-role-model-calls", "reviewer=1"]
    )
    assert result.exit_code == 0, result.output
    store = Store(repo)
    completed = store.load(task.id)
    assert completed.state == State.COMPLETED and provider.reviews == 2
    assert completed.spec.budgets.model_calls == 4 and completed.provider_calls == 4
    assert completed.spec.budgets.role_limits[Role.REVIEWER].model_calls == 2
    audit = [
        json.loads(event["payload"])
        for event in store.events(task.id)
        if event["kind"] == "budget_extended"
    ][-1]
    assert audit["role_model_calls"] == {"reviewer": 1}
    store.close()


@pytest.mark.parametrize("known", [True, False])
def test_clear_role_reported_limit_keeps_enclosing_limits(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    known: bool,
) -> None:
    store = Store(repo)
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(
            description="Fix answer",
            acceptance=["42"],
            provider="fake",
            classification_overrides=ClassificationOverrides(risk=Risk.MEDIUM),
            budgets=Budgets(
                model_calls=4,
                reported_output_tokens=100,
                role_limits={
                    Role.REVIEWER: RoleLimits(reported_input_tokens=1),
                },
            ),
        ),
    )
    store.create(task)
    provider = ReviewTwice(Usage(input_tokens=1 if known else None, output_tokens=1))
    paused = asyncio.run(Engine(store, provider).execute(task.id))
    assert paused.state == State.PAUSED and paused.next_role == Role.REVIEWER
    assert "threshold" in paused.message if known else "unknown" in paused.message
    store.close()
    monkeypatch.setattr("eng.cli.provider_for", lambda *args: provider)
    result = CliRunner().invoke(
        app, ["resume", task.id, "-p", str(repo), "--clear-role-limits", "reviewer"]
    )
    assert result.exit_code == 0, result.output
    store = Store(repo)
    saved = store.load(task.id)
    assert saved.state == State.COMPLETED and saved.provider_calls == 4
    assert saved.spec.budgets.model_calls == 4
    assert saved.spec.budgets.reported_output_tokens == 100
    assert Role.REVIEWER not in saved.spec.budgets.role_limits
    store.close()


@pytest.mark.parametrize(
    "options",
    [
        ["--extend-role-model-calls", "verifier=1"],
        ["--extend-role-model-calls", "invalid=1"],
        ["--extend-role-model-calls", "reviewer=0"],
        ["--extend-role-model-calls", "reviewer=-1"],
        ["--extend-role-model-calls", "reviewer=100"],
        ["--extend-role-model-calls", "reviewer=1.5"],
        ["--extend-role-model-calls", "reviewer=4"],
        ["--extend-role-model-calls", "reviewer=1", "--clear-role-limits", "reviewer"],
        ["--clear-role-limits", "verifier"],
    ],
)
def test_invalid_role_recovery_does_not_mutate_or_approve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    options: list[str],
) -> None:
    monkeypatch.setattr("eng.cli.repository_root", lambda path: tmp_path)
    store = Store(tmp_path)
    task = Task(
        project=tmp_path,
        config=ProjectConfig(),
        spec=TaskSpec(
            description="Fix",
            acceptance=["pass"],
            budgets=Budgets(
                model_calls=4,
                role_limits={Role.REVIEWER: RoleLimits(model_calls=1)},
            ),
        ),
    )
    store.create(task)
    before = store.load(task.id).model_dump()
    events_before = store.events(task.id)
    store.close()
    result = CliRunner().invoke(
        app, ["resume", task.id, "--approve-high-risk", "--extend-seconds", "1", *options]
    )
    assert result.exit_code == 2, result.output
    store = Store(tmp_path)
    assert store.load(task.id).model_dump() == before
    assert store.events(task.id) == events_before
    store.close()


@pytest.mark.parametrize("known", [True, False])
def test_clearing_role_cannot_bypass_overall_reported_stop(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    known: bool,
) -> None:
    store = Store(repo)
    task = Task(
        project=repo,
        config=load_config(repo),
        spec=TaskSpec(
            description="Fix answer",
            acceptance=["42"],
            provider="fake",
            classification_overrides=ClassificationOverrides(risk=Risk.MEDIUM),
            budgets=Budgets(
                model_calls=4,
                reported_input_tokens=10,
                role_limits={
                    Role.REVIEWER: RoleLimits(reported_input_tokens=1),
                },
            ),
        ),
    )
    store.create(task)
    provider = ReviewTwice(Usage(input_tokens=10 if known else None))
    paused = asyncio.run(Engine(store, provider).execute(task.id))
    assert paused.state == State.PAUSED and provider.reviews == 0
    store.close()
    monkeypatch.setattr("eng.cli.provider_for", lambda *args: provider)
    result = CliRunner().invoke(
        app, ["resume", task.id, "-p", str(repo), "--clear-role-limits", "reviewer"]
    )
    assert result.exit_code == 1, result.output
    store = Store(repo)
    saved = store.load(task.id)
    assert saved.state == State.PAUSED and saved.provider_calls == 1
    assert provider.reviews == 0 and saved.spec.budgets.reported_input_tokens == 10
    assert Role.REVIEWER not in saved.spec.budgets.role_limits
    store.close()


def test_preview_resolves_config_and_never_opens_store_or_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("preview must not create state or construct a provider")

    monkeypatch.setattr("eng.cli.Store", forbidden)
    monkeypatch.setattr("eng.cli.provider_for", forbidden)
    root = tmp_path / "project"
    monkeypatch.setattr("eng.cli.repository_root", lambda path: root)
    (root / ".engineering").mkdir(parents=True)
    (root / ".engineering/project.yaml").write_text(
        "budgets:\n  model_calls: 4\n",
        encoding="utf-8",
    )
    user = tmp_path / "user.yaml"
    user.write_text("budgets:\n  context_chars: 1234\n", encoding="utf-8")
    plan = tmp_path / "plan.yaml"
    plan.write_text(
        yaml.safe_dump(
            {
                "name": "preview",
                "node_budgets": {"provider_seconds": 12},
                "nodes": [
                    {
                        "id": "css",
                        "description": "Fix button color",
                        "acceptance": ["blue"],
                        "owns": ["style.css"],
                        "budgets": {"model_calls": 2},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app, ["plan", "preview", str(plan), "-p", str(root), "--user-config", str(user)]
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["hypothetical"] is True
    assert report["predicted_cost_usd"] is None
    assert report["concurrency"] == 1
    node = report["nodes"][0]
    assert node["effective_budgets"]["model_calls"] == 2
    assert node["effective_budgets"]["provider_seconds"] == 12
    assert node["effective_budgets"]["context_chars"] == 1234
    assert node["minimum_role_calls"] == 1
    assert not (root / ".engineering/state").exists()


def test_nested_project_preview_matches_root(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("preview created runtime state or a provider")

    monkeypatch.setattr("eng.cli.Store", forbidden)
    monkeypatch.setattr("eng.cli.provider_for", forbidden)
    nested = repo / "nested"
    nested.mkdir()
    plan = repo.parent / "preview.yaml"
    plan.write_text(
        yaml.safe_dump(
            {
                "name": "preview",
                "nodes": [
                    {
                        "id": "one",
                        "description": "Fix color",
                        "acceptance": ["blue"],
                        "owns": ["style.css"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    root_result = runner.invoke(app, ["plan", "preview", str(plan), "-p", str(repo)])
    nested_result = runner.invoke(app, ["plan", "preview", str(plan), "-p", str(nested)])
    assert root_result.exit_code == nested_result.exit_code == 0
    assert json.loads(root_result.output) == json.loads(nested_result.output)
    assert not (repo / ".engineering/state").exists()


def test_efficiency_benchmark_flag_routes_to_offline_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def benchmark(**kwargs: object) -> dict[str, bool]:
        observed.update(kwargs)
        return {"offline": True}

    monkeypatch.setattr("eng.benchmark.run_benchmark", benchmark)
    result = CliRunner().invoke(app, ["benchmark", "--efficiency"])
    assert result.exit_code == 0, result.output
    assert observed["include_efficiency_cases"] is True


def test_usage_preserves_historical_checks_and_task_native_totals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("eng.cli.repository_root", lambda path: tmp_path)
    store = Store(tmp_path)
    task = Task(
        project=tmp_path,
        config=ProjectConfig(),
        spec=TaskSpec(description="Fix", acceptance=["works"]),
    )
    store.create(task)
    task.execution_id = "execution"
    store.start_execution(task)
    task.pending_invocation_id = "invocation"
    task.pending_role = Role.ENGINEER
    store.begin_invocation(task)
    store.invocation(
        task,
        ProviderResult(
            status="success",
            usage=Usage(
                input_tokens=10,
                output_tokens=2,
            ),
        ).model_dump_json(),
        invocation_id="invocation",
    )
    for outcome in ("FAIL", "PASS"):
        task.verification = [
            VerificationResult.model_validate(
                {
                    "check_id": "tests",
                    "command": ["test"],
                    "environment": "fixture",
                    "outcome": outcome,
                    "duration_seconds": 0.5,
                }
            )
        ]
        store.verification(task)
    store.checkpoint(task)
    store.close()
    result = CliRunner().invoke(app, ["usage", task.id])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["checks_scope"] == "supplied_history"
    assert report["check_outcomes"] == {"FAIL": 1, "PASS": 1}
    assert report["check_duration_seconds"] == 1.0
    assert report["tasks"][0]["fields"]["input_tokens"]["known_subtotal"] == 10
    assert report["tasks"][0]["human_acceptance"] is None
