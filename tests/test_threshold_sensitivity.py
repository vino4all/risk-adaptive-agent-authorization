"""Tests for secondary threshold sensitivity over frozen scores."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from analysis.threshold_sensitivity import (
    classify,
    metric_row,
    valid_grid_pairs,
)


def test_grid_contains_only_the_nine_specified_valid_pairs() -> None:
    pairs = valid_grid_pairs()
    assert len(pairs) == 9
    assert {t1 for t1, _ in pairs} == {0.30, 0.40, 0.50}
    assert {t2 for _, t2 in pairs} == {0.60, 0.70, 0.80}
    assert all(t1 < t2 for t1, t2 in pairs)


def test_threshold_boundaries_follow_three_way_decision_rule() -> None:
    predictions = classify(pd.Series([0.0, 0.29, 0.30, 0.59, 0.60, 1.0]), 0.30, 0.60)
    assert predictions.tolist() == [
        "ALLOW",
        "ALLOW",
        "ESCALATE",
        "ESCALATE",
        "DENY",
        "DENY",
    ]


def test_metric_definitions_on_known_scores() -> None:
    decisions = pd.DataFrame(
        {
            "ground_truth": ["DENY", "DENY", "ALLOW", "ALLOW", "ESCALATE", "ESCALATE"],
            "risk_score": [0.1, 0.8, 0.1, 0.4, 0.4, 0.8],
        }
    )
    row = metric_row(
        decisions,
        t1=0.30,
        t2=0.60,
        configuration_type="test",
        is_primary=False,
    )
    assert row["UER"] == pytest.approx(0.5)
    assert row["LDCR"] == pytest.approx(0.5)
    assert row["OER"] == pytest.approx(0.5)
    assert row["CER"] == pytest.approx(0.5)


def test_analysis_source_does_not_select_a_best_threshold() -> None:
    import analysis.threshold_sensitivity as module

    source = Path(module.__file__).read_text(encoding="utf-8").lower()
    assert "best_threshold" not in source
    assert "optimal_threshold" not in source
