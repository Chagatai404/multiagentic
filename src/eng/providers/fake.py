from collections.abc import Callable
from pathlib import Path

from eng.core.models import Capabilities, ProviderRequest, ProviderResult
from eng.execution.workspace import safe_path


class FakeProvider:
    """Explicit deterministic edits for offline demos; never pretends to understand a task."""

    name = "fake"
    capabilities = Capabilities(kind="fake", file_editing=True, working_directory_isolation=True)

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
        for relative, content in self.changes.items():
            target = safe_path(request.workspace, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return ProviderResult(
            status="success", summary=f"Applied {len(self.changes)} fixture edits"
        )
