"""Unit tests for metric definitions and paired statistical handling."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis.evaluate_experiment import (
    decision_statistical_tests,
    escalation_analysis,
    latency_outputs,
    primary_metrics,
    wilson_interval,
)


def fixture_decisions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scenario_id": [f"T{i}" for i in range(1, 8)],
            "ground_truth": ["DENY", "DENY", "ALLOW", "ALLOW", "ESCALATE", "ESCALATE", "ESCALATE"],
            "abac_decision": ["ALLOW", "DENY", "ALLOW", "DENY", "ALLOW", "DENY", "DENY"],
            "risk_adaptive_decision": ["DENY", "DENY", "ALLOW", "ESCALATE", "ESCALATE", "ALLOW", "DENY"],
            "abac_latency_ms": [0.01, 0.02, 0.01, 0.02, 0.01, 0.02, 0.01],
            "risk_adaptive_latency_ms": [0.02, 0.04, 0.03, 0.04, 0.03, 0.10, 0.03],
        }
    )


def metric(frame: pd.DataFrame, method: str, name: str) -> pd.Series:
    return frame[(frame["method"] == method) & (frame["metric"] == name)].iloc[0]


def test_primary_metric_definitions_use_only_required_ground_truth_subsets() -> None:
    results = primary_metrics(fixture_decisions())
    assert metric(results, "abac_binary", "UER")["rate"] == pytest.approx(0.5)
    assert metric(results, "risk_adaptive", "UER")["rate"] == pytest.approx(0.0)
    assert metric(results, "abac_binary", "LDCR")["rate"] == pytest.approx(0.5)
    assert metric(results, "risk_adaptive", "LDCR")["rate"] == pytest.approx(0.5)
    assert metric(results, "abac_binary", "OER")["rate"] == pytest.approx(0.0)
    assert metric(results, "risk_adaptive", "OER")["rate"] == pytest.approx(0.5)
    assert metric(results, "risk_adaptive", "CER")["rate"] == pytest.approx(1 / 3)


def test_all_reported_rates_have_bounded_wilson_intervals() -> None:
    lower, upper = wilson_interval(0, 10)
    assert 0.0 <= lower <= upper <= 1.0
    assert upper > 0.0
    results = primary_metrics(fixture_decisions())
    assert ((results["ci_lower"] >= 0) & (results["ci_upper"] <= 1)).all()
    assert set(results["ci_method"]) == {"Wilson score interval"}


def test_true_escalate_analysis_is_explicit_and_exhaustive() -> None:
    results = escalation_analysis(fixture_decisions())
    abac = results[results["method"] == "abac_binary"]
    risk = results[results["method"] == "risk_adaptive"]
    assert dict(zip(abac["metric"], abac["numerator"])) == {
        "resolved_ALLOW": 1,
        "resolved_DENY": 2,
    }
    assert dict(zip(risk["metric"], risk["numerator"])) == {
        "correctly_ESCALATE_CER": 1,
        "incorrectly_ALLOW": 1,
        "incorrectly_DENY": 1,
    }
    assert set(results["denominator"]) == {3}


def test_mcnemar_is_metric_specific_and_three_way_table_is_descriptive() -> None:
    rows = decision_statistical_tests(fixture_decisions())
    metric_rows = rows[:4]
    assert all(row["test"].startswith("exact McNemar") for row in metric_rows)
    uer_table = json.loads(metric_rows[0]["paired_table"])
    assert uer_table["abac_only"] == 1
    assert uer_table["risk_adaptive_only"] == 0
    three_way = rows[4]
    assert three_way["test"] == "descriptive 3x3 paired contingency table"
    assert np.isnan(three_way["p_value"])
    assert "not applied mechanically" in three_way["notes"]


def test_latency_distribution_is_inspected_before_paired_test() -> None:
    frame = pd.concat([fixture_decisions()] * 5, ignore_index=True)
    frame.loc[len(frame) - 1, "risk_adaptive_latency_ms"] = 10.0
    summary, tests = latency_outputs(frame)
    assert set(summary["method"]) == {"abac_binary", "risk_adaptive"}
    assert {"mean_ms", "median_ms", "p95_ms", "p99_ms"}.issubset(summary.columns)
    assert tests[0]["test"] == "Shapiro-Wilk normality diagnostic"
    assert tests[1]["test"] == "Wilcoxon signed-rank test"


def test_deprecated_uer_esc_symbol_is_absent() -> None:
    import analysis.evaluate_experiment as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "UER_esc" not in source
