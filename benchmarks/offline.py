"""A real failing check and deterministic repair, in a disposable repository."""

import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

from eng.core.engine import Engine
from eng.core.models import Check, ProjectConfig, State, Task, TaskSpec
from eng.providers.fake import FakeProvider
from eng.storage.store import Store


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="eng-benchmark-") as temporary:
        root = Path(temporary).resolve()
        subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
        (root / ".gitignore").write_text(
            ".engineering/state/\n.engineering/worktrees/\n"
            ".engineering/artifacts/\n.engineering/locks/\n"
        )
        (root / "answer.txt").write_text("41")
        (root / "check.py").write_text(
            "from pathlib import Path\nassert Path('answer.txt').read_text() == '42'\n"
        )
        config = ProjectConfig(
            name="offline",
            checks=[Check(name="answer", argv=["{python}", "check.py"], confirmed=True)],
        )
        (root / ".engineering").mkdir()
        (root / ".engineering/project.yaml").write_text(
            yaml.safe_dump(config.model_dump(mode="json"))
        )
        subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Benchmark",
                "-c",
                "user.email=benchmark@example.invalid",
                "commit",
                "-m",
                "fixture",
            ],
            check=True,
            capture_output=True,
        )
        baseline = subprocess.run([sys.executable, "check.py"], cwd=root, capture_output=True)
        assert baseline.returncode != 0, "Seeded defect must fail before the repair"
        store = Store(root)
        task = Task(
            project=root,
            config=config,
            spec=TaskSpec(
                description="Repair seeded answer", acceptance=["answer is 42"], provider="fake"
            ),
        )
        store.create(task)
        started = time.monotonic()
        result = asyncio.run(Engine(store, FakeProvider({"answer.txt": "42"})).execute(task.id))
        elapsed = time.monotonic() - started
        print(
            json.dumps(
                {
                    "baseline_exit_code": baseline.returncode,
                    "state": result.state,
                    "elapsed_seconds": elapsed,
                    "provider_calls": result.provider_calls,
                    "verification": [
                        check.model_dump(mode="json") for check in result.verification
                    ],
                    "usage": result.usage.model_dump(mode="json"),
                },
                indent=2,
            )
        )
        store.close()
        assert result.state == State.COMPLETED, result.message


if __name__ == "__main__":
    main()
