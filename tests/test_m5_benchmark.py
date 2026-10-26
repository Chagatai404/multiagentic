import json
import os
import tempfile
from pathlib import Path

import pytest

from eng.benchmark import ARMS, SCENARIOS, run_benchmark


@pytest.mark.parametrize(
    "kwargs",
    [
        {"repetitions": 0},
        {"repetitions": 11},
        {"repetitions": True},
        {"seed": -1},
        {"seed": 2**32},
        {"seed": True},
        {"scenarios": []},
        {"scenarios": ["unknown"]},
        {"scenarios": ["small_bug", "small_bug"]},
    ],
)
def test_benchmark_bounds(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        run_benchmark(**kwargs)  # type: ignore[arg-type]


def test_all_fixture_arms_use_same_external_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path.parent))
    original_ceiling = os.environ.get("GIT_CEILING_DIRECTORIES")
    report = run_benchmark(seed=12)
    assert os.environ.get("GIT_CEILING_DIRECTORIES") == original_ceiling
    assert json.loads(json.dumps(report))["fixture_kind"] == "deterministic_scripted_edits"
    assert report["scenarios"] == list(SCENARIOS)
    rows = report["raw"]
    assert len(rows) == 18
    assert all(row["source_unchanged"] for row in rows)
    assert all(row["input_tokens"] is None and row["cost_usd"] is None for row in rows)
    summary = report["summary"]
    assert summary[ARMS[0]]["verified_success"] == 3
    assert summary[ARMS[0]]["escaped_defects"] == 3
    assert summary[ARMS[1]]["verified_success"] == 3
    assert summary[ARMS[1]]["escaped_defects"] == 0
    assert summary[ARMS[2]]["verified_success"] == 6
    assert summary[ARMS[2]]["first_pass_success"] == 3
    assert summary[ARMS[2]]["repairs"] == 3
    assert report["context_microbenchmark"]["equal_packets"] is True
    assert report["context_microbenchmark"]["cache"]["hits"] > 0
