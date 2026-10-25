from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from eng.core.models import Capabilities, ProviderRequest, ProviderResult


class Provider(Protocol):
    name: str
    capabilities: Capabilities

    async def execute(
        self,
        request: ProviderRequest,
        artifact_dir: Path,
        cancelled: Callable[[], bool],
    ) -> ProviderResult: ...
