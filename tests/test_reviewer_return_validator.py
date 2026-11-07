"""Return validation rejects changed or incomplete blinded review data."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from confirmatory.reviewer_return_validator import (
    FIELDS,
    ReviewValidationError,
    validate_return,
    write_manifest,
)

REPO = Path(__file__).resolve().parent.parent
FROZEN = [
    REPO / "confirmatory/inputs/scenarios.yaml",
    REPO / "confirmatory/inputs/policy_matrix.yaml",
    REPO / "confirmatory/inputs/risk_config.yaml",
    REPO / "confirmatory/inputs/context_aware_abac.yaml",
    REPO / "confirmatory/inputs/analysis_plan.md",
]


def write_csv(path: Path, rows: list[dict[str, str]], fields=FIELDS) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path, list[dict[str, str]]]:
    rows = [
        dict.fromkeys(FIELDS, "") | {"reviewer_scenario_id": f"R{i:03d}", "role": "ANALYST"}
        for i in (1, 2, 3)
    ]
    outbound, returned = tmp_path / "outbound.csv", tmp_path / "returned.csv"
    write_csv(outbound, rows)
    for row, label in zip(rows, ("ALLOW", "ESCALATE", "DENY"), strict=True):
        row["reviewer_label"] = label
    write_csv(returned, rows)
    return outbound, returned, rows


def test_valid_return_preserves_bytes_and_writes_safe_manifest(files, tmp_path: Path) -> None:
    outbound, returned, _ = files
    before = returned.read_bytes()
    assert validate_return(outbound, returned) == 3
    manifest = write_manifest(outbound, returned, tmp_path / "manifest.json")
    assert returned.read_bytes() == before
    assert manifest["returned_reviewer_sample_sha256"] == hashlib.sha256(before).hexdigest()
    assert manifest["labels_auto_adjudicated"] is False
    assert "ground_truth" not in (tmp_path / "manifest.json").read_text()


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda r: r[0].update(reviewer_label=""), "reviewer_label"),
        (lambda r: r[0].update(reviewer_label="allow"), "reviewer_label"),
        (lambda r: r[0].update(reviewer_label="OTHER"), "reviewer_label"),
        (lambda r: r[1].update(reviewer_scenario_id="R001"), "duplicate"),
        (lambda r: r.pop(), "missing"),
        (lambda r: r[0].update(reviewer_scenario_id="R999"), "unexpected"),
        (lambda r: r[0].update(role="MANAGER"), "role changed"),
    ],
)
def test_invalid_return_rejected(files, change, error: str) -> None:
    outbound, returned, rows = files
    change(rows)
    write_csv(returned, rows)
    with pytest.raises(ReviewValidationError, match=error):
        validate_return(outbound, returned)


def test_answer_key_column_rejected(files) -> None:
    outbound, returned, rows = files
    for row in rows:
        row["ground_truth"] = "DENY"
    write_csv(returned, rows, (*FIELDS, "ground_truth"))
    with pytest.raises(ReviewValidationError, match="columns must be exactly"):
        validate_return(outbound, returned)


def test_optional_notes_can_be_omitted(files) -> None:
    outbound, returned, rows = files
    write_csv(returned, rows, FIELDS[:-1])
    assert validate_return(outbound, returned) == 3


def test_review_workflow_does_not_change_frozen_inputs(files, tmp_path: Path) -> None:
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in FROZEN}
    outbound, returned, _ = files
    write_manifest(outbound, returned, tmp_path / "manifest.json")
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in FROZEN} == before
