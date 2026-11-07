"""Validation tests for the blinded independent-review package."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import pytest

from src.models import ConfigurationError
from src.policy import load_final_scenarios
from src.reviewer_package import (
    ALLOWED_REVIEWER_LABELS,
    DEFAULT_SAMPLE_PATH,
    REVIEWER_COLUMNS,
    REVIEW_RANDOM_SEED,
    merge_completed_reviews,
    reviewer_row,
    select_review_sample,
    write_review_package,
)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def test_reviewer_sample_is_exactly_forty_percent_and_reproducible() -> None:
    scenarios = load_final_scenarios()
    first = select_review_sample(scenarios)
    second = select_review_sample(scenarios)
    assert len(first) == 60 == round(len(scenarios) * 0.40)
    assert first == second
    assert REVIEW_RANDOM_SEED == 20260918


@pytest.fixture
def generated_private_package(tmp_path: Path) -> tuple[Path, Path]:
    """Make synthetic test evidence outside the repository's public files."""
    key_path = tmp_path / "reviewer_sample_key.csv"
    manifest_path = tmp_path / "reviewer_sample_manifest.json"
    write_review_package(
        select_review_sample(load_final_scenarios()),
        sample_path=tmp_path / "reviewer_sample.csv",
        key_path=key_path,
        manifest_path=manifest_path,
    )
    return key_path, manifest_path


def test_committed_sample_matches_seeded_selection(generated_private_package: tuple[Path, Path]) -> None:
    selection = select_review_sample(load_final_scenarios())
    _, sample_rows = read_csv(DEFAULT_SAMPLE_PATH)
    _, key_rows = read_csv(generated_private_package[0])
    assert sample_rows == [reviewer_row(item) for item in selection]
    assert key_rows == [
        {
            "reviewer_scenario_id": item.reviewer_scenario_id,
            "scenario_id": item.scenario.scenario_id,
        }
        for item in selection
    ]


def test_reviewer_csv_has_only_blinded_fields_and_blank_response_columns() -> None:
    headers, rows = read_csv(DEFAULT_SAMPLE_PATH)
    assert tuple(headers) == REVIEWER_COLUMNS
    assert len(rows) == 60
    assert len({row["reviewer_scenario_id"] for row in rows}) == 60
    assert all(row["reviewer_scenario_id"].startswith("R") for row in rows)
    assert all(row["reviewer_label"] == "" for row in rows)
    assert all(row["reviewer_notes"] == "" for row in rows)
    forbidden = {
        "scenario_id",
        "ground_truth",
        "risk_score",
        "risk_weights",
        "T1",
        "T2",
        "ABAC_result",
        "risk_adaptive_result",
        "policy_rule_ids",
        "rationale",
    }
    assert forbidden.isdisjoint(headers)


def test_sample_preserves_exact_role_tool_and_sensitivity_balance() -> None:
    _, rows = read_csv(DEFAULT_SAMPLE_PATH)
    assert Counter(row["role"] for row in rows) == {
        "ADMINISTRATOR": 20,
        "ANALYST": 20,
        "MANAGER": 20,
    }
    assert Counter(row["tool_action"] for row in rows) == {
        "DELETE_RECORD": 12,
        "EXPORT_DATA": 12,
        "READ_RECORD": 12,
        "SEND_MESSAGE": 12,
        "UPDATE_RECORD": 12,
    }
    assert Counter(row["resource_sensitivity"] for row in rows) == {
        "CONFIDENTIAL": 20,
        "INTERNAL": 20,
        "RESTRICTED": 20,
    }


def test_hidden_class_stratification_is_proportional(generated_private_package: tuple[Path, Path]) -> None:
    manifest = json.loads(generated_private_package[1].read_text(encoding="utf-8"))
    assert manifest["class_counts_used_for_stratification_not_exported"] == {
        "ALLOW": 11,
        "DENY": 26,
        "ESCALATE": 23,
    }
    assert manifest["random_seed"] == REVIEW_RANDOM_SEED
    assert manifest["crosswalk_is_not_reviewer_facing"] is True


def test_private_crosswalk_contains_no_labels_or_scenario_attributes(generated_private_package: tuple[Path, Path]) -> None:
    headers, rows = read_csv(generated_private_package[0])
    assert headers == ["reviewer_scenario_id", "scenario_id"]
    assert len(rows) == 60
    assert len({row["scenario_id"] for row in rows}) == 60
    assert all(set(row) == {"reviewer_scenario_id", "scenario_id"} for row in rows)


def test_completed_labels_merge_only_after_all_rows_are_valid(tmp_path: Path, generated_private_package: tuple[Path, Path]) -> None:
    headers, rows = read_csv(DEFAULT_SAMPLE_PATH)
    labels = sorted(ALLOWED_REVIEWER_LABELS)
    for index, row in enumerate(rows):
        row["reviewer_label"] = labels[index % len(labels)]
        row["reviewer_notes"] = f"independent note {index + 1}"
    completed = tmp_path / "completed.csv"
    with completed.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    merged_path = tmp_path / "merged.csv"
    merge_completed_reviews(completed, key_path=generated_private_package[0], output_path=merged_path)
    merged_headers, merged = read_csv(merged_path)
    assert merged_headers == [
        "scenario_id",
        "reviewer_scenario_id",
        "reviewer_label",
        "reviewer_notes",
    ]
    assert len(merged) == 60
    assert {row["reviewer_label"] for row in merged} == ALLOWED_REVIEWER_LABELS
    assert all(row["scenario_id"].startswith("F") for row in merged)


def test_merge_rejects_blank_or_unsupported_labels(tmp_path: Path, generated_private_package: tuple[Path, Path]) -> None:
    headers, rows = read_csv(DEFAULT_SAMPLE_PATH)
    completed = tmp_path / "invalid.csv"
    with completed.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ConfigurationError, match="must be ALLOW, ESCALATE, or DENY"):
        merge_completed_reviews(completed, key_path=generated_private_package[0], output_path=tmp_path / "merged.csv")
