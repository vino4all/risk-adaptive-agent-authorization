"""Tests for independent-review agreement measurement and safe joining."""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.reviewer_agreement import (
    agreement_rows,
    calculate_agreement,
    disagreement_frame,
    render_report,
)


def fixture_joined() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "reviewer_scenario_id": [f"R{i:03d}" for i in range(1, 7)],
            "scenario_id": [f"F{i:03d}" for i in range(1, 7)],
            "scenario_description": [f"scenario {i}" for i in range(1, 7)],
            "role": ["ANALYST"] * 6,
            "tool": ["READ_RECORD"] * 6,
            "sensitivity": ["INTERNAL"] * 6,
            "destination": ["INTERNAL"] * 6,
            "context_risk": ["NORMAL"] * 6,
            "original_ground_truth": ["ALLOW", "ALLOW", "ESCALATE", "ESCALATE", "DENY", "DENY"],
            "reviewer_label": ["ALLOW", "ESCALATE", "ESCALATE", "DENY", "DENY", "DENY"],
            "reviewer_notes": [""] * 6,
        }
    )


def test_raw_agreement_kappa_confusion_and_per_label_rates() -> None:
    result = calculate_agreement(fixture_joined())
    assert result.agreement_count == 4
    assert result.raw_agreement == pytest.approx(4 / 6)
    assert result.cohens_kappa == pytest.approx(0.5)
    assert result.confusion == {
        "ALLOW": {"ALLOW": 1, "ESCALATE": 1, "DENY": 0},
        "ESCALATE": {"ALLOW": 0, "ESCALATE": 1, "DENY": 1},
        "DENY": {"ALLOW": 0, "ESCALATE": 0, "DENY": 2},
    }
    assert result.per_label == {
        "ALLOW": (1, 2, 0.5),
        "ESCALATE": (1, 2, 0.5),
        "DENY": (2, 2, 1.0),
    }


def test_agreement_csv_rows_include_summary_per_label_and_full_confusion() -> None:
    rows = agreement_rows(calculate_agreement(fixture_joined()))
    assert len(rows) == 2 + 3 + 9
    assert [row["metric"] for row in rows[:2]] == ["raw_agreement", "cohens_kappa"]
    assert sum(row["record_type"] == "confusion_matrix" for row in rows) == 9


def test_disagreements_are_listed_without_changing_labels() -> None:
    joined = fixture_joined()
    before = joined.copy(deep=True)
    disagreements = disagreement_frame(calculate_agreement(joined))
    assert disagreements["reviewer_scenario_id"].tolist() == ["R002", "R004"]
    assert list(disagreements[["original_ground_truth", "reviewer_label"]].itertuples(index=False, name=None)) == [
        ("ALLOW", "ESCALATE"),
        ("ESCALATE", "DENY"),
    ]
    pd.testing.assert_frame_equal(joined, before)


def test_report_separates_measurement_from_later_adjudication() -> None:
    report = render_report(calculate_agreement(fixture_joined()))
    assert "## Agreement measurement" in report
    assert "## Later adjudication" in report
    assert "No disagreement was automatically resolved" in report
