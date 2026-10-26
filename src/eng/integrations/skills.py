"""Install the bundled workflow skill without replacing another tool's instructions."""

from importlib.resources import files
from pathlib import Path
from typing import Any

from eng.core.triggers import TriggerOrigin
from eng.integrations.install import InstallScope, _atomic_write, _exclude_locally, client_home

SKILL_NAME = "multiagentic-engineering"
MARKER = "<!-- managed by multiagentic-eng -->"


def skill_paths(scope: InstallScope, project: Path | None, extra_dirs: list[Path]) -> list[Path]:
    if scope is InstallScope.PROJECT:
        if project is None:
            raise ValueError("Project scope requires a project root")
        directories = [
            project / ".agents" / "skills",
            project / ".claude" / "skills",
            project / ".github" / "skills",
        ]
    else:
        directories = [
            Path.home() / ".agents" / "skills",
            client_home(TriggerOrigin.CLAUDE_CODE) / "skills",
            Path.home() / ".copilot" / "skills",
        ]
    return list(
        dict.fromkeys(
            directory.expanduser().resolve() / SKILL_NAME / "SKILL.md"
            for directory in [*directories, *extra_dirs]
        )
    )


def update_skills(
    scope: InstallScope,
    project: Path | None,
    *,
    extra_dirs: list[Path],
    remove: bool = False,
) -> list[dict[str, Any]]:
    paths = skill_paths(scope, project, extra_dirs)
    payload = files("eng").joinpath("resources", SKILL_NAME, "SKILL.md").read_bytes()
    # Validate every destination before changing any of them.
    for path in paths:
        if path.exists() and MARKER not in path.read_text(encoding="utf-8"):
            raise ValueError(f"Refusing to replace an unowned skill: {path}")
    results = []
    for path in paths:
        previous = path.read_bytes() if path.exists() else None
        changed = previous is not None if remove else previous != payload
        if changed:
            if remove:
                path.unlink()  # never recursively remove a skill directory or user resources
            else:
                _atomic_write(path, payload)
        if not remove and scope is InstallScope.PROJECT and project is not None:
            if path.is_relative_to(project):
                _exclude_locally(project, [path])
        results.append({"path": str(path), "installed": not remove, "changed": changed})
    return results
