"""Integrity checks for the committed experiment measurements."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis.evaluate_experiment import (
    DEFAULT_RESULTS_DIR,
    escalation_analysis,
    frozen_input_hashes,
    primary_metrics,
)


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(DEFAULT_RESULTS_DIR / name)


def test_all_required_machine_readable_outputs_exist() -> None:
    for name in (
        "decisions.csv",
        "summary_metrics.csv",
        "escalation_analysis.csv",
        "statistical_tests.csv",
        "latency_summary.csv",
    ):
        assert (DEFAULT_RESULTS_DIR / name).is_file()


def test_decisions_are_complete_matched_pairs() -> None:
    decisions = load("decisions.csv")
    assert len(decisions) == 150
    assert decisions["scenario_id"].nunique() == 150
    assert decisions["ground_truth"].value_counts().to_dict() == {
        "DENY": 65,
        "ESCALATE": 58,
        "ALLOW": 27,
    }
    assert set(decisions["abac_decision"]) <= {"ALLOW", "DENY"}
    assert set(decisions["risk_adaptive_decision"]) <= {
        "ALLOW",
        "ESCALATE",
        "DENY",
    }
    assert decisions[["abac_latency_ms", "risk_adaptive_latency_ms"]].notna().all().all()


def test_summary_metrics_recompute_exactly_from_decisions() -> None:
    decisions = load("decisions.csv")
    committed = load("summary_metrics.csv")
    recomputed = primary_metrics(decisions)
    key = ["method", "metric"]
    merged = committed.merge(recomputed, on=key, suffixes=("_actual", "_expected"))
    assert len(merged) == 8
    for column in ("numerator", "denominator", "rate", "ci_lower", "ci_upper"):
        assert np.allclose(merged[f"{column}_actual"], merged[f"{column}_expected"])
    assert set(committed["metric"]) == {"UER", "LDCR", "OER", "CER"}


def test_escalation_output_recomputes_and_partitions_true_escalates() -> None:
    decisions = load("decisions.csv")
    committed = load("escalation_analysis.csv")
    recomputed = escalation_analysis(decisions)
    merged = committed.merge(
        recomputed, on=["method", "metric"], suffixes=("_actual", "_expected")
    )
    assert len(merged) == 5
    assert np.array_equal(merged["numerator_actual"], merged["numerator_expected"])
    assert set(committed["denominator"]) == {58}
    abac = committed[committed["method"] == "abac_binary"]
    risk = committed[committed["method"] == "risk_adaptive"]
    assert abac["numerator"].sum() == 58
    assert risk["numerator"].sum() == 58


def test_latency_summary_matches_raw_authorization_latencies() -> None:
    decisions = load("decisions.csv")
    summary = load("latency_summary.csv").set_index("method")
    for method, column in (
        ("abac_binary", "abac_latency_ms"),
        ("risk_adaptive", "risk_adaptive_latency_ms"),
    ):
        values = decisions[column].to_numpy()
        assert summary.loc[method, "n"] == 150
        assert summary.loc[method, "mean_ms"] == pytest.approx(np.mean(values))
        assert summary.loc[method, "median_ms"] == pytest.approx(np.median(values))
        assert summary.loc[method, "p95_ms"] == pytest.approx(np.percentile(values, 95))
        assert summary.loc[method, "p99_ms"] == pytest.approx(np.percentile(values, 99))


def test_statistics_use_mcnemar_only_for_binary_events() -> None:
    tests = load("statistical_tests.csv")
    mcnemar = tests[tests["test"].str.startswith("exact McNemar")]
    assert set(mcnemar["comparison"].str.split(":").str[0]) == {
        "UER",
        "LDCR",
        "OER",
        "CER",
    }
    three_way = tests[tests["comparison"] == "paired three-way decisions"].iloc[0]
    assert three_way["test"] == "descriptive 3x3 paired contingency table"
    assert pd.isna(three_way["p_value"])
    latency = tests[tests["comparison"].str.startswith("authorization latency")].iloc[0]
    assert latency["test"] in {"Wilcoxon signed-rank test", "paired t-test"}


def test_manifest_proves_frozen_inputs_did_not_change() -> None:
    manifest = json.loads(
        (DEFAULT_RESULTS_DIR / "evaluation_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["scenario_count"] == 150
    assert manifest["matched_pair_design"] is True
    assert manifest["authorization_logic_only_latency"] is True
    assert manifest["frozen_input_hashes_before"] == manifest["frozen_input_hashes_after"]
    assert manifest["frozen_input_hashes_after"] == frozen_input_hashes()
