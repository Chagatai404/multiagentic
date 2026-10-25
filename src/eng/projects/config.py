import sys
from pathlib import Path
from typing import Any

import yaml

from eng.core.models import Check, ProjectConfig
from eng.execution.workspace import repository_root

RUNTIME_IGNORES = ["state/", "worktrees/", "artifacts/", "locks/"]


def initialize(path: Path) -> ProjectConfig:
    root = repository_root(path)
    directory = root / ".engineering"
    directory.mkdir(exist_ok=True)
    config_path = directory / "project.yaml"
    if config_path.exists():
        raise ValueError(".engineering/project.yaml already exists; edit it explicitly")
    checks = []
    languages = []
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists():
        languages.append("python")
        checks.append(Check(name="tests", argv=[sys.executable, "-m", "pytest", "-q"]))
    if (root / "package.json").exists():
        languages.append("javascript")
        # npm.cmd needs an explicit platform adapter; don't execute it through a shell.
    config = ProjectConfig(name=root.name, languages=languages, checks=checks)
    config_path.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    (directory / ".gitignore").write_text("\n".join(RUNTIME_IGNORES) + "\n", encoding="utf-8")
    return config


def merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(root: Path, user_config: Path | None = None) -> ProjectConfig:
    raw = ProjectConfig().model_dump(mode="json")
    paths = [user_config] if user_config is not None else []
    paths.append(root / ".engineering" / "project.yaml")
    for path in paths:
        if path is not None and path.is_file():
            if path.stat().st_size > 1_000_000:
                raise ValueError(f"Configuration too large: {path}")
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise ValueError(f"Configuration must be a mapping: {path}")
            raw = merge(raw, document)
    return ProjectConfig.model_validate(raw)
