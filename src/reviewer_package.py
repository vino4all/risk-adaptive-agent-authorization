"""Create and later merge the blinded independent-review sample."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src.models import CONTEXT_RISK_DEFINITIONS, ConfigurationError, Decision, Scenario
from src.policy import DEFAULT_SCENARIOS_PATH, load_final_scenarios

REVIEW_RANDOM_SEED = 20260918
SAMPLE_FRACTION = 0.40
DEFAULT_SAMPLE_PATH = Path(__file__).resolve().parent.parent / "data" / "reviewer_sample.csv"
DEFAULT_KEY_PATH = Path(__file__).resolve().parent.parent / "data" / "reviewer_sample_key.csv"
DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "reviewer_sample_manifest.json"

REVIEWER_COLUMNS = (
    "reviewer_scenario_id",
    "scenario_description",
    "role",
    "tool_action",
    "resource_sensitivity",
    "destination",
    "context_description",
    "reviewer_label",
    "reviewer_notes",
)
KEY_COLUMNS = ("reviewer_scenario_id", "scenario_id")
ALLOWED_REVIEWER_LABELS = frozenset(decision.value for decision in Decision)
BALANCE_ATTRIBUTES = ("role", "tool", "sensitivity")


@dataclass(frozen=True, slots=True)
class BlindedSelection:
    reviewer_scenario_id: str
    scenario: Scenario


def _apportion(counts: Mapping[str, int], total: int) -> dict[str, int]:
    """Largest-remainder proportional allocation with deterministic ties."""
    population = sum(counts.values())
    exact = {key: total * count / population for key, count in counts.items()}
    allocated = {key: int(value) for key, value in exact.items()}
    remaining = total - sum(allocated.values())
    order = sorted(counts, key=lambda key: (-(exact[key] - allocated[key]), key))
    for key in order[:remaining]:
        allocated[key] += 1
    return allocated


def select_review_sample(
    scenarios: Sequence[Scenario],
    *,
    seed: int = REVIEW_RANDOM_SEED,
    fraction: float = SAMPLE_FRACTION,
) -> tuple[BlindedSelection, ...]:
    """Select a label-stratified, marginally balanced, reproducible sample."""
    if not scenarios:
        raise ConfigurationError("cannot sample an empty final dataset")
    sample_count = round(len(scenarios) * fraction)
    class_counts = Counter(scenario.ground_truth.value for scenario in scenarios if scenario.ground_truth)
    if set(class_counts) != ALLOWED_REVIEWER_LABELS:
        raise ConfigurationError("final dataset must contain all three ground-truth classes")
    class_quotas = _apportion(class_counts, sample_count)
    global_targets = {
        attribute: _apportion(
            Counter(str(getattr(scenario, attribute)) for scenario in scenarios),
            sample_count,
        )
        for attribute in BALANCE_ATTRIBUTES
    }
    class_targets = {
        label: {
            attribute: _apportion(
                Counter(
                    str(getattr(scenario, attribute))
                    for scenario in scenarios
                    if scenario.ground_truth and scenario.ground_truth.value == label
                ),
                quota,
            )
            for attribute in BALANCE_ATTRIBUTES
        }
        for label, quota in class_quotas.items()
    }

    rng = random.Random(seed)
    tie_break = {scenario.scenario_id: rng.random() for scenario in scenarios}
    selected: list[Scenario] = []
    global_counts = {attribute: Counter() for attribute in BALANCE_ATTRIBUTES}

    for label in sorted(class_quotas, key=lambda value: (class_quotas[value], value)):
        pool = [
            scenario
            for scenario in scenarios
            if scenario.ground_truth and scenario.ground_truth.value == label
        ]
        local_counts = {attribute: Counter() for attribute in BALANCE_ATTRIBUTES}
        for _ in range(class_quotas[label]):
            def priority(scenario: Scenario) -> tuple[float, float, float]:
                global_deficit = sum(
                    max(
                        global_targets[attribute][str(getattr(scenario, attribute))]
                        - global_counts[attribute][str(getattr(scenario, attribute))],
                        0,
                    )
                    for attribute in BALANCE_ATTRIBUTES
                )
                class_deficit = sum(
                    max(
                        class_targets[label][attribute][str(getattr(scenario, attribute))]
                        - local_counts[attribute][str(getattr(scenario, attribute))],
                        0,
                    )
                    for attribute in BALANCE_ATTRIBUTES
                )
                return (global_deficit, class_deficit, tie_break[scenario.scenario_id])

            chosen = max(pool, key=priority)
            pool.remove(chosen)
            selected.append(chosen)
            for attribute in BALANCE_ATTRIBUTES:
                value = str(getattr(chosen, attribute))
                global_counts[attribute][value] += 1
                local_counts[attribute][value] += 1

    rng.shuffle(selected)
    return tuple(
        BlindedSelection(f"R{index:03d}", scenario)
        for index, scenario in enumerate(selected, start=1)
    )


def reviewer_row(item: BlindedSelection) -> dict[str, str]:
    """Return the deliberately blinded reviewer-facing representation."""
    scenario = item.scenario
    return {
        "reviewer_scenario_id": item.reviewer_scenario_id,
        "scenario_description": scenario.description,
        "role": scenario.role.value,
        "tool_action": scenario.tool.value,
        "resource_sensitivity": scenario.sensitivity.value,
        "destination": scenario.destination.value,
        "context_description": CONTEXT_RISK_DEFINITIONS[scenario.context_risk],
        "reviewer_label": "",
        "reviewer_notes": "",
    }


def _write_csv(path: str | Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, str]]) -> None:
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def _sample_counts(selection: Sequence[BlindedSelection], attribute: str) -> dict[str, int]:
    return dict(
        sorted(Counter(str(getattr(item.scenario, attribute)) for item in selection).items())
    )


def write_review_package(
    selection: Sequence[BlindedSelection],
    *,
    sample_path: str | Path = DEFAULT_SAMPLE_PATH,
    key_path: str | Path = DEFAULT_KEY_PATH,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> None:
    """Write blinded CSV, private crosswalk, and non-sensitive audit manifest."""
    _write_csv(sample_path, REVIEWER_COLUMNS, (reviewer_row(item) for item in selection))
    _write_csv(
        key_path,
        KEY_COLUMNS,
        (
            {
                "reviewer_scenario_id": item.reviewer_scenario_id,
                "scenario_id": item.scenario.scenario_id,
            }
            for item in selection
        ),
    )
    sample_bytes = Path(sample_path).read_bytes()
    manifest = {
        "random_seed": REVIEW_RANDOM_SEED,
        "sample_fraction": SAMPLE_FRACTION,
        "final_scenario_count": 150,
        "reviewer_sample_count": len(selection),
        "sample_sha256": hashlib.sha256(sample_bytes).hexdigest(),
        "class_counts_used_for_stratification_not_exported": _sample_counts(selection, "ground_truth"),
        "role_counts": _sample_counts(selection, "role"),
        "tool_counts": _sample_counts(selection, "tool"),
        "sensitivity_counts": _sample_counts(selection, "sensitivity"),
        "reviewer_csv_columns": list(REVIEWER_COLUMNS),
        "blinded_fields": [
            "ground_truth",
            "risk_score",
            "risk_weights",
            "T1",
            "T2",
            "ABAC_result",
            "risk_adaptive_result",
            "policy_rule_ids",
            "ground_truth_rationale",
        ],
        "crosswalk_is_not_reviewer_facing": True,
    }
    Path(manifest_path).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def merge_completed_reviews(
    completed_sample_path: str | Path,
    *,
    key_path: str | Path = DEFAULT_KEY_PATH,
    output_path: str | Path,
) -> None:
    """Merge completed reviewer labels to original IDs after blinded review."""
    with Path(key_path).open(encoding="utf-8", newline="") as handle:
        key_rows = list(csv.DictReader(handle))
    crosswalk = {row["reviewer_scenario_id"]: row["scenario_id"] for row in key_rows}
    if len(crosswalk) != len(key_rows):
        raise ConfigurationError("reviewer crosswalk contains duplicate reviewer IDs")

    with Path(completed_sample_path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not set(REVIEWER_COLUMNS).issubset(reader.fieldnames):
            raise ConfigurationError("completed reviewer CSV is missing required columns")
        completed = list(reader)
    if len(completed) != len(crosswalk):
        raise ConfigurationError("completed reviewer CSV does not contain the full sample")

    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in completed:
        reviewer_id = row["reviewer_scenario_id"].strip()
        if reviewer_id in seen or reviewer_id not in crosswalk:
            raise ConfigurationError(f"unknown or duplicate reviewer_scenario_id: {reviewer_id}")
        seen.add(reviewer_id)
        label = row["reviewer_label"].strip().upper()
        if label not in ALLOWED_REVIEWER_LABELS:
            raise ConfigurationError(
                f"{reviewer_id}: reviewer_label must be ALLOW, ESCALATE, or DENY"
            )
        merged.append(
            {
                "scenario_id": crosswalk[reviewer_id],
                "reviewer_scenario_id": reviewer_id,
                "reviewer_label": label,
                "reviewer_notes": row["reviewer_notes"].strip(),
            }
        )
    _write_csv(
        output_path,
        ("scenario_id", "reviewer_scenario_id", "reviewer_label", "reviewer_notes"),
        merged,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or merge the blinded reviewer package")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("generate", help="write the deterministic blinded sample")
    merge = subparsers.add_parser("merge", help="merge completed reviewer labels")
    merge.add_argument("completed_csv")
    merge.add_argument("output_csv")
    args = parser.parse_args(argv)
    if args.command == "generate":
        write_review_package(select_review_sample(load_final_scenarios()))
    else:
        merge_completed_reviews(args.completed_csv, output_path=args.output_csv)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
