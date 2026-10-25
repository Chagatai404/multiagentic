"""Resolve the narrow set of portable check launchers without invoking a shell."""

import shutil
import sys
from pathlib import Path


def resolve_command(argv: list[str]) -> list[str]:
    resolved = [sys.executable if item == "{python}" else item for item in argv]
    if sys.platform != "win32" or Path(resolved[0]).name.lower() not in {
        "npm",
        "npm.cmd",
        "npm.ps1",
    }:
        return resolved
    executable = shutil.which(resolved[0])
    if executable is None:
        raise ValueError("npm executable is unavailable")
    entry = Path(executable).parent / "node_modules/npm/bin/npm-cli.js"
    node = shutil.which("node")
    if node is None or not entry.is_file():
        raise ValueError("Unsupported npm installation: Node.js and adjacent npm-cli.js required")
    return [node, str(entry), *resolved[1:]]
