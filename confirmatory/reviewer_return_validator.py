"""Fail-closed validation of a completed, blinded confirmatory reviewer CSV."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTBOUND = ROOT / "confirmatory/reviewer_export/reviewer_sample.csv"
RETURNED = ROOT / "confirmatory/reviewer_returns/reviewer_sample_returned.csv"
MANIFEST = ROOT / "confirmatory/reviewer_returns/reviewer_return_manifest.json"
FREEZE = ROOT / "confirmatory/freeze_manifest.json"
VERSION = "confirmatory.reviewer_return_validator/1.0"
FIELDS = (
    "reviewer_scenario_id", "scenario_description", "role", "tool_action",
    "resource_sensitivity", "destination", "context_description",
    "reviewer_label", "reviewer_notes",
)
LABELS = {"ALLOW", "ESCALATE", "DENY"}


class ReviewValidationError(ValueError):
    """A reviewer return cannot safely enter agreement analysis."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path, *, returned: bool) -> list[dict[str, str]]:
    if not path.is_file():
        raise ReviewValidationError(f"CSV not found: {path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            expected = list(FIELDS)
            if returned and reader.fieldnames == expected[:-1]:
                expected = expected[:-1]  # reviewer_notes may be omitted
            if reader.fieldnames != expected:
                raise ReviewValidationError(
                    f"{path.name}: columns must be exactly {expected}; "
                    f"found {reader.fieldnames}"
                )
            rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise ReviewValidationError(f"{path.name}: invalid CSV: {exc}") from exc
    if not rows:
        raise ReviewValidationError(f"{path.name}: no scenario rows")
    for number, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            raise ReviewValidationError(f"{path.name}: malformed row {number}")
    return rows


def validate_return(outbound: Path = OUTBOUND, returned: Path = RETURNED) -> int:
    """Validate without changing either CSV or normalizing any value."""
    original = _read(outbound, returned=False)
    review = _read(returned, returned=True)
    original_ids = [row["reviewer_scenario_id"] for row in original]
    review_ids = [row["reviewer_scenario_id"] for row in review]
    if len(set(original_ids)) != len(original_ids):
        raise ReviewValidationError("outbound CSV contains duplicate reviewer_scenario_id")
    if any(row["reviewer_label"] or row["reviewer_notes"] for row in original):
        raise ReviewValidationError("outbound CSV response columns must be blank")
    if len(set(review_ids)) != len(review_ids):
        raise ReviewValidationError("returned CSV contains duplicate reviewer_scenario_id")
    missing = sorted(set(original_ids) - set(review_ids))
    unknown = sorted(set(review_ids) - set(original_ids))
    if missing or unknown:
        raise ReviewValidationError(f"scenario IDs differ: missing={missing}, unexpected={unknown}")
    if len(review) != len(original):
        raise ReviewValidationError(
            f"row count mismatch: expected {len(original)}, found {len(review)}"
        )
    by_id = {row["reviewer_scenario_id"]: row for row in original}
    for row in review:
        identifier = row["reviewer_scenario_id"]
        for field in FIELDS[1:-2]:
            if row[field] != by_id[identifier][field]:
                raise ReviewValidationError(f"{identifier}: {field} changed from outbound CSV")
        label = row["reviewer_label"]
        if label not in LABELS:
            raise ReviewValidationError(
                f"{identifier}: reviewer_label must be exactly ALLOW, ESCALATE, or DENY; "
                f"found {label!r}"
            )
    return len(review)


def write_manifest(
    outbound: Path = OUTBOUND, returned: Path = RETURNED, manifest: Path = MANIFEST
) -> dict[str, object]:
    count = validate_return(outbound, returned)
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    payload: dict[str, object] = {
        "outbound_reviewer_sample_sha256": _sha256(outbound),
        "returned_reviewer_sample_sha256": _sha256(returned),
        "row_count": count,
        "validation_status": "passed",
        "validation_timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_tree_sha256_at_freeze": freeze.get("source_tree_sha256"),
        "validator_module_version": VERSION,
        "labels_auto_adjudicated": False,
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outbound", type=Path, default=OUTBOUND)
    parser.add_argument("--returned", type=Path, default=RETURNED)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()
    try:
        result = write_manifest(args.outbound, args.returned, args.manifest)
    except (ReviewValidationError, OSError, ValueError) as exc:
        print(f"reviewer return validation failed: {exc}", file=sys.stderr)
        return 2
    print(f"reviewer return validation passed: {result['row_count']} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
