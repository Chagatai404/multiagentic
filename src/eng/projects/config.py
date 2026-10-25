import configparser
import json
import tomllib
from pathlib import Path
from typing import Any

import yaml

from eng.core.models import Check, ProjectConfig
from eng.execution.workspace import repository_root

RUNTIME_IGNORES = ["state/", "worktrees/", "artifacts/", "locks/"]


def initialize(path: Path) -> ProjectConfig:
    root = repository_root(path)
    directory = root / ".engineering"
    config_path = directory / "project.yaml"
    if config_path.exists():
        raise ValueError(".engineering/project.yaml already exists; edit it explicitly")
    checks = []
    languages = []
    pyproject = root / "pyproject.toml"
    pytest_ini = root / "pytest.ini"
    pytest_configured = False
    if pyproject.exists():
        try:
            document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (ValueError, OSError) as error:
            raise ValueError(f"Invalid pyproject.toml: {error}") from error
        tool = document.get("tool", {})
        pytest = tool.get("pytest", {}) if isinstance(tool, dict) else {}
        pytest_configured = isinstance(pytest, dict) and isinstance(pytest.get("ini_options"), dict)
    if pytest_ini.exists():
        try:
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(pytest_ini.read_text(encoding="utf-8"))
        except (configparser.Error, OSError, ValueError) as error:
            raise ValueError(f"Invalid pytest.ini: {error}") from error
        pytest_configured = True
    if pyproject.exists() or pytest_ini.exists():
        languages.append("python")
    if pytest_configured:
        checks.append(Check(name="tests", argv=["{python}", "-m", "pytest", "-q"]))
    package = root / "package.json"
    if package.exists():
        try:
            manifest = json.loads(package.read_text(encoding="utf-8"))
        except (ValueError, OSError) as error:
            raise ValueError(f"Invalid package.json: {error}") from error
        if not isinstance(manifest, dict):
            raise ValueError("Invalid package.json: expected an object")
        scripts = manifest.get("scripts", {})
        if not isinstance(scripts, dict):
            raise ValueError("Invalid package.json: scripts must be an object")
        test = scripts.get("test")
        if test is not None and not isinstance(test, str):
            raise ValueError("Invalid package.json: scripts.test must be a string")
        languages.append("javascript")
        if isinstance(test, str) and test.strip():
            checks.append(Check(name="npm-tests", argv=["npm", "test"]))
    config = ProjectConfig(name=root.name, languages=languages, checks=checks)
    directory.mkdir(exist_ok=True)
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
