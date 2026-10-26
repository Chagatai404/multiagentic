import json
from collections.abc import Callable
from pathlib import Path

from eng.core.models import Capabilities, ProviderRequest, ProviderResult, Role
from eng.execution.workspace import safe_path


class FakeProvider:
    """Explicit deterministic edits for offline demos; never pretends to understand a task."""

    name = "fake"
    # Accepts and ignores a requested model, so routing is testable offline.
    capabilities = Capabilities(
        kind="fake", file_editing=True, working_directory_isolation=True, model_selection=True
    )

    def __init__(self, changes: dict[str, str] | None = None) -> None:
        self.changes = changes or {}

    async def execute(
        self,
        request: ProviderRequest,
        artifact_dir: Path,
        cancelled: Callable[[], bool],
    ) -> ProviderResult:
        if cancelled():
            return ProviderResult(status="cancelled", error_kind="cancelled")
        if request.role == Role.VERIFIER:
            raise ValueError("Verifier does not use a model provider")
        if request.role == Role.PLANNER:
            return ProviderResult(
                status="success",
                summary=json.dumps(
                    {
                        "summary": "Deterministic fixture plan",
                        "steps": ["Apply configured fixture edits", "Run configured checks"],
                    }
                ),
            )
        if request.role == Role.REVIEWER:
            return ProviderResult(
                status="success",
                summary=json.dumps(
                    {
                        "summary": "Deterministic fixture review",
                        "verdict": "pass",
                        "findings": [],
                    }
                ),
            )
        for relative, content in self.changes.items():
            target = safe_path(request.workspace, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return ProviderResult(
            status="success", summary=f"Applied {len(self.changes)} fixture edits"
        )
