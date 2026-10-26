"""E0 regressions: honest telemetry, native counters, and durable result JSON."""

import asyncio
from collections.abc import Callable
from pathlib import Path

from eng.agents import execute_role
from eng.core.accounting import usage_report
from eng.core.models import (
    InvocationRecord,
    InvocationTelemetry,
    ProjectConfig,
    ProviderRequest,
    ProviderResult,
    Role,
    State,
    Task,
    TaskSpec,
    Usage,
)
from eng.providers.fake import FakeProvider
from eng.storage.store import Store


def row(result: ProviderResult | None = None) -> InvocationRecord:
    return InvocationRecord(
        invocation_id="invocation",
        execution_id="execution",
        provider="fake",
        model="selected",
        role=Role.ENGINEER,
        status=result.status if result else "started",
        result=result,
    )


def test_legacy_unknowns_and_cost_provenance_are_explicit() -> None:
    report = usage_report([row(), row(ProviderResult(status="success"))])
    assert report.schema_version == 2
    assert report.totals["input_tokens"].known_subtotal is None
    assert report.totals["input_tokens"].missing == 2
    assert report.groups[0].actual_models == []
    assert report.groups[0].actual_model_missing == 2
    assert report.groups[0].packet_chars.known_subtotal is None
    assert report.outcomes == {"started": 1, "success": 1}
    assert "actual_model" in report.missing_telemetry
    assert report.measurement_sources["packet_chars"] == "measured"
    assert report.measurement_sources["internal_model_turns"] == "unavailable"
    assert report.measured_account_spend is None
    assert report.subscription_allowance is None


def test_selected_actual_models_and_native_counters_stay_distinct() -> None:
    result = ProviderResult(
        status="success",
        actual_model="observed",
        usage=Usage(
            input_tokens=100,
            cached_input_tokens=80,
            cost_usd=0.25,
            cost_source="client_estimate",
            source="provider",
        ),
    )
    report = usage_report([row(result)])
    group = report.groups[0]
    assert group.model == "selected" and group.actual_models == ["observed"]
    assert report.totals["input_tokens"].known_subtotal == 100
    assert report.totals["cached_input_tokens"].known_subtotal == 80
    assert group.reported_cost_usd.known_subtotal is None
    assert group.client_estimate_cost_usd.known_subtotal == 0.25
    assert group.pricing_estimate_usd.known_subtotal is None


def test_completed_does_not_invent_human_acceptance_or_repaired_defects(tmp_path: Path) -> None:
    task = Task(
        project=tmp_path,
        config=ProjectConfig(),
        spec=TaskSpec(description="Fix", acceptance=["works"]),
        state=State.COMPLETED,
    )
    report = usage_report([], tasks=[task])
    assert report.tasks[0].state == State.COMPLETED
    assert report.tasks[0].human_acceptance is None
    assert report.tasks[0].repaired_defects is None
    assert report.tasks[0].repair_attempts == 0


def test_adapter_entry_does_not_invent_process_timing_or_session_count() -> None:
    result = ProviderResult(
        status="error",
        error_kind="unavailable",
        telemetry=InvocationTelemetry(provider_invoked=True),
    )
    report = usage_report([row(result)])
    assert report.totals["provider_executions"].known_subtotal == 1
    assert report.totals["provider_duration_seconds"].known_subtotal is None
    assert report.measurement_sources["provider_cli_sessions"] == "unavailable"
    assert report.totals["packet_chars"].known_subtotal is None


class Observed(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.prompt = ""

    async def execute(
        self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
    ) -> ProviderResult:
        self.prompt = request.prompt
        return ProviderResult(status="success")


def test_packet_sizes_measure_the_actual_isolated_request_and_persist(repo: Path) -> None:
    task = Task(
        project=repo, config=ProjectConfig(), spec=TaskSpec(description="Fix", acceptance=["works"])
    )
    provider = Observed()
    request = ProviderRequest(
        task_id=task.id,
        execution_id="execution",
        role=Role.REVIEWER,
        workspace=repo,
        prompt=f"ç λ 🙂 {repo}",
        timeout_seconds=30,
    )
    result = asyncio.run(
        execute_role(provider, request, task, repo.parent / "artifacts", lambda: False)
    )
    assert result.telemetry is not None
    assert result.telemetry.packet_chars == len(provider.prompt)
    assert result.telemetry.packet_utf8_bytes == len(provider.prompt.encode("utf-8"))
    assert result.telemetry.packet_utf8_bytes > result.telemetry.packet_chars
    assert result.telemetry.provider_invoked is True
    assert result.actual_model is None
    store = Store(repo)
    store.create(task)
    task.execution_id = "execution"
    store.start_execution(task)
    task.pending_role = Role.REVIEWER
    task.pending_invocation_id = "invocation"
    store.begin_invocation(task)
    store.invocation(task, result.model_dump_json(), invocation_id="invocation", role=Role.REVIEWER)
    saved = store.invocations(task.id)[0].result
    assert saved is not None and saved.telemetry == result.telemetry
    store.close()


def test_mutation_then_exception_retains_measured_adapter_entry(repo: Path) -> None:
    class MutatesThenRaises(Observed):
        async def execute(
            self, request: ProviderRequest, artifact_dir: Path, cancelled: Callable[[], bool]
        ) -> ProviderResult:
            self.prompt = request.prompt
            (request.workspace / "answer.txt").write_text("mutated", encoding="utf-8")
            raise RuntimeError("fixture transport failed after mutation")

    task = Task(
        project=repo, config=ProjectConfig(), spec=TaskSpec(description="Fix", acceptance=["works"])
    )
    provider = MutatesThenRaises()
    result = asyncio.run(
        execute_role(
            provider,
            ProviderRequest(
                task_id=task.id,
                execution_id="execution",
                role=Role.REVIEWER,
                workspace=repo,
                prompt=f"ç 🙂 {repo}",
                timeout_seconds=30,
            ),
            task,
            repo.parent / "mutation-artifacts",
            lambda: False,
        )
    )
    assert result.error_kind == "role_mutation"
    report = usage_report([row(result)])
    assert report.totals["provider_executions"].known_subtotal == 1
    assert report.totals["packet_chars"].known_subtotal == len(provider.prompt)
    assert report.totals["packet_utf8_bytes"].known_subtotal == len(provider.prompt.encode("utf-8"))
    assert report.totals["input_tokens"].known_subtotal is None
    assert report.totals["reported_cost_usd"].known_subtotal is None
    assert report.totals["provider_duration_seconds"].known_subtotal is None
