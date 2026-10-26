import json
import re
import sys
from pathlib import Path

import pytest
import yaml
from conftest import commit
from typer.testing import CliRunner

from eng.cli import app
from eng.core.models import CommandProviderConfig, ProjectConfig
from eng.execution.workspace import git
from eng.providers.registry import build_registry

runner = CliRunner()

AGENT = """\
import re
import sys
from pathlib import Path

prompt = sys.stdin.read()
node = re.search(r"NODE:(\\w+)", prompt).group(1)
if node == "wild":
    Path("files/outside.txt").write_text("OUTSIDE")
    Path("files/wild.txt").write_text("WILD")
else:
    Path(f"files/{node}.txt").write_text(node.upper())
print(f"done {node}")
"""


@pytest.fixture
def scripted_repo(plan_repo: Path, tmp_path: Path) -> Path:
    script = tmp_path / "agent.py"
    script.write_text(AGENT, encoding="utf-8")
    path = plan_repo / ".engineering" / "project.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["provider"] = "scripted"
    config["command_providers"] = {"scripted": {"argv": ["{python}", str(script)]}}
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    commit(plan_repo)
    return plan_repo


def write_plan(tmp_path: Path, nodes: list[dict[str, object]], **extra: object) -> Path:
    document = {"name": "cli", "nodes": nodes, **extra}
    path = tmp_path / "plan.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def spec_node(
    node_id: str, owns: list[str], depends_on: list[str] | None = None
) -> dict[str, object]:
    return {
        "id": node_id,
        "description": f"NODE:{node_id} create its file",
        "acceptance": ["its file exists"],
        "owns": owns,
        "depends_on": depends_on or [],
    }


def invoke(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def test_plan_validate_reports_order_and_rejects_overlap(tmp_path: Path) -> None:
    good = write_plan(tmp_path, [spec_node("b", ["b/**"], ["a"]), spec_node("a", ["a/**"])])
    code, output = invoke("plan", "validate", str(good))
    assert code == 0 and json.loads(output)["order"] == ["a", "b"]
    bad = write_plan(tmp_path, [spec_node("a", ["src/**"]), spec_node("b", ["src/x.py"])])
    code, output = invoke("plan", "validate", str(bad))
    assert code == 2 and "overlap" in output
    over = write_plan(tmp_path, [spec_node("a", ["x"])], concurrency=4)
    assert invoke("plan", "validate", str(over))[0] == 2


def test_full_plan_lifecycle_through_the_cli(scripted_repo: Path, tmp_path: Path) -> None:
    plan_file = write_plan(
        tmp_path,
        [
            spec_node("a", ["files/a.txt"]),
            spec_node("b", ["files/b.txt"]),
            spec_node("c", ["files/c.txt"], ["a", "b"]),
        ],
    )
    project = ["-p", str(scripted_repo)]
    base = git(scripted_repo, "rev-parse", "HEAD")
    code, output = invoke("plan", "create", str(plan_file), *project)
    assert code == 0, output
    plan_id = json.loads(output)["id"]
    code, output = invoke("plan", "run", plan_id, *project)
    assert code == 0, output
    assert json.loads(output)["status"] == "READY"
    # Dry run changes nothing and says what needs approval.
    code, output = invoke("plan", "promote", plan_id, *project)
    report = json.loads(output)
    assert code == 0 and report["promotable"] and not report["promoted"]
    assert git(scripted_repo, "rev-parse", "HEAD") == base
    code, output = invoke("plan", "promote", plan_id, *project, "--approve")
    assert code == 0 and json.loads(output)["promoted"] is True
    assert (scripted_repo / "files" / "c.txt").read_text() == "C"
    code, output = invoke("plan", "status", plan_id, *project)
    status = json.loads(output)
    assert status["plan"]["status"] == "PROMOTED"
    kinds = [event["kind"] for event in status["events"]]
    assert "promotion_approved" in kinds and "node_integrated" in kinds
    assert json.loads(invoke("plan", "status", *project)[1])[0]["id"] == plan_id
    code, output = invoke("plan", "usage", plan_id, *project)
    assert code == 0 and json.loads(output)["invocations"] == 3


def test_ownership_violation_exit_code_and_skipped_dependents(
    scripted_repo: Path, tmp_path: Path
) -> None:
    plan_file = write_plan(
        tmp_path,
        [spec_node("wild", ["files/wild.txt"]), spec_node("after", ["files/after.txt"], ["wild"])],
    )
    project = ["-p", str(scripted_repo)]
    plan_id = json.loads(invoke("plan", "create", str(plan_file), *project)[1])["id"]
    code, output = invoke("plan", "run", plan_id, *project)
    plan = json.loads(output)
    assert code == 1 and plan["status"] == "FAILED"
    statuses = {n["spec"]["id"]: n["status"] for n in plan["nodes"]}
    assert statuses == {"wild": "FAILED", "after": "SKIPPED"}
    assert invoke("plan", "promote", plan_id, *project, "--approve")[0] == 1


def test_cancel_and_unknown_plan(scripted_repo: Path, tmp_path: Path) -> None:
    plan_file = write_plan(tmp_path, [spec_node("a", ["files/a.txt"])])
    project = ["-p", str(scripted_repo)]
    plan_id = json.loads(invoke("plan", "create", str(plan_file), *project)[1])["id"]
    code, output = invoke("plan", "cancel", plan_id, *project)
    assert code == 0 and json.loads(output)["status"] == "CANCELLED"
    code, output = invoke("plan", "run", plan_id, *project)
    assert code == 2 and "cancelled" in output
    assert invoke("plan", "status", "nope", *project)[0] == 2


def test_nested_execution_is_refused(scripted_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENG_ACTIVE", "1")
    code, output = invoke("plan", "run", "abc", "-p", str(scripted_repo))
    assert code == 2 and "Nested" in output


def test_command_provider_config_and_discovery(scripted_repo: Path) -> None:
    code, output = invoke("providers", "-p", str(scripted_repo))
    assert code == 0 and "scripted" in json.loads(output)
    assert json.loads(output)["scripted"]["file_editing"] is True
    code, output = invoke("doctor", "-p", str(scripted_repo))
    doctor = json.loads(output)["scripted"]
    assert doctor["available"] is True and doctor["kind"] == "configured_command"
    assert re.search(r"python", doctor["executable"] or "")


def test_command_provider_run_through_eng_run(scripted_repo: Path) -> None:
    code, output = invoke(
        "run", "NODE:solo make the file", "--accept", "file exists", "-p", str(scripted_repo)
    )
    task = json.loads(output)
    assert code == 0 and task["state"] == "COMPLETED", output
    assert task["spec"]["provider"] == "scripted"
    workspace = Path(task["workspace"])
    assert (workspace / "files" / "solo.txt").read_text() == "SOLO"


def test_command_provider_validation() -> None:
    with pytest.raises(ValueError, match="credential"):
        CommandProviderConfig(argv=["x"], env_allow=["PLAIN_SETTING"])
    with pytest.raises(ValueError, match="Invalid"):
        CommandProviderConfig(argv=["x"], env_allow=["BAD-NAME_TOKEN"])
    assert CommandProviderConfig(argv=["x"], env_allow=["MYCLI_API_KEY"]).env_allow
    with pytest.raises(ValueError, match="reserved"):
        ProjectConfig(command_providers={"codex": CommandProviderConfig(argv=["x"])})
    with pytest.raises(ValueError, match="Invalid"):
        ProjectConfig(command_providers={"Bad Name": CommandProviderConfig(argv=["x"])})
    with pytest.raises(ValueError, match="Duplicate"):
        build_registry(command_providers={"fake": CommandProviderConfig(argv=[sys.executable])})
