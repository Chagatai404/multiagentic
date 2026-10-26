"""Offline efficiency cases exercise production gates, never paid providers."""

import tempfile
from pathlib import Path

import pytest

from eng.benchmark import run_benchmark


def test_efficiency_controls_measure_blocked_approval_and_disjoint_integration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path.parent))
    report = run_benchmark(seed=42, scenarios=["small_bug"], include_efficiency_cases=True)
    assert report["schema_version"] == 2
    assert len(report["raw"]) == 3
    assert {row["initial_complexity"] for row in report["raw"]} == {"small"}
    controls = {row["scenario"]: row for row in report["control_cases"]}
    approval = controls["high_risk_approval"]
    assert approval["state"] == "PAUSED"
    assert approval["provider_calls"] == 0
    assert approval["gate_preserved"] is True
    assert approval["declared_success"] is False
    disjoint = controls["disjoint_cross_module_plan"]
    assert disjoint["state"] == "READY"
    assert disjoint["node_statuses"] == ["INTEGRATED", "INTEGRATED"]
    assert disjoint["verified_success"] is True
    assert disjoint["promoted"] is False
    assert disjoint["source_unchanged"] is True
    assert disjoint["provider_calls"] == 2
    assert all(row["cost_usd"] is None for row in controls.values())
    assert all(row["input_tokens"] is None for row in controls.values())


def test_efficiency_switch_rejects_nonboolean() -> None:
    with pytest.raises(ValueError, match="include_efficiency_cases"):
        run_benchmark(include_efficiency_cases="yes")  # type: ignore[arg-type]
