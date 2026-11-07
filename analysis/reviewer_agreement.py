"""Independent-review agreement analysis without ground-truth mutation."""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from src.models import ConfigurationError, Decision, Scenario
from src.policy import DEFAULT_SCENARIOS_PATH, load_final_scenarios
from src.reviewer_package import DEFAULT_KEY_PATH, DEFAULT_SAMPLE_PATH

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results" / "exploratory"
DEFAULT_AGREEMENT_PATH = DEFAULT_RESULTS_DIR / "reviewer_agreement.csv"
DEFAULT_DISAGREEMENTS_PATH = DEFAULT_RESULTS_DIR / "reviewer_disagreements.csv"
DEFAULT_REPORT_PATH = Path(__file__).resolve().parent.parent / "GROUND_TRUTH_VALIDATION.md"
LABELS = tuple(decision.value for decision in Decision)


@dataclass(frozen=True, slots=True)
class AgreementResult:
    sample_count: int
    agreement_count: int
    raw_agreement: float
    cohens_kappa: float
    confusion: Mapping[str, Mapping[str, int]]
    per_label: Mapping[str, tuple[int, int, float]]
    joined: pd.DataFrame


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_csv(path: str | Path) -> pd.DataFrame:
    resolved = Path(path)
    if not resolved.is_file():
        raise ConfigurationError(f"required reviewer file not found: {resolved}")
    return pd.read_csv(resolved, dtype=str, keep_default_na=False)


def load_joined_reviews(
    scenarios: Sequence[Scenario],
    *,
    completed_sample_path: str | Path = DEFAULT_SAMPLE_PATH,
    key_path: str | Path = DEFAULT_KEY_PATH,
) -> pd.DataFrame:
    """Join completed blinded labels to immutable original labels in memory."""
    reviews = _read_csv(completed_sample_path)
    key = _read_csv(key_path)
    required_reviews = {"reviewer_scenario_id", "reviewer_label", "reviewer_notes"}
    required_key = {"reviewer_scenario_id", "scenario_id"}
    if missing := sorted(required_reviews - set(reviews.columns)):
        raise ConfigurationError(
            "completed reviewer CSV is missing column(s): " + ", ".join(missing)
        )
    if missing := sorted(required_key - set(key.columns)):
        raise ConfigurationError("reviewer key is missing column(s): " + ", ".join(missing))
    if reviews["reviewer_scenario_id"].duplicated().any():
        raise ConfigurationError("completed reviewer CSV contains duplicate reviewer IDs")
    if key["reviewer_scenario_id"].duplicated().any() or key["scenario_id"].duplicated().any():
        raise ConfigurationError("reviewer key contains duplicate IDs")
    if len(reviews) != len(key):
        raise ConfigurationError("completed reviewer CSV does not contain the full sample")

    reviews = reviews.copy()
    reviews["reviewer_label"] = reviews["reviewer_label"].str.strip().str.upper()
    invalid = reviews.loc[
        ~reviews["reviewer_label"].isin(LABELS),
        ["reviewer_scenario_id", "reviewer_label"],
    ]
    if not invalid.empty:
        examples = ", ".join(
            f"{row.reviewer_scenario_id}={row.reviewer_label or '<blank>'}"
            for row in invalid.head(10).itertuples(index=False)
        )
        raise ConfigurationError(
            "reviewer_label must be ALLOW, ESCALATE, or DENY for every sampled "
            f"row; invalid entries: {examples}"
        )

    scenario_rows = pd.DataFrame(
        [
            {
                "scenario_id": scenario.scenario_id,
                "scenario_description": scenario.description,
                "role": scenario.role.value,
                "tool": scenario.tool.value,
                "sensitivity": scenario.sensitivity.value,
                "destination": scenario.destination.value,
                "context_risk": scenario.context_risk.value,
                "original_ground_truth": (
                    scenario.ground_truth.value if scenario.ground_truth else ""
                ),
            }
            for scenario in scenarios
        ]
    )
    joined = key.merge(
        reviews[["reviewer_scenario_id", "reviewer_label", "reviewer_notes"]],
        on="reviewer_scenario_id",
        how="left",
        validate="one_to_one",
    ).merge(scenario_rows, on="scenario_id", how="left", validate="one_to_one")
    if joined[["reviewer_label", "original_ground_truth"]].eq("").any().any():
        raise ConfigurationError("review sample could not be fully joined to final scenarios")
    return joined


def calculate_agreement(joined: pd.DataFrame) -> AgreementResult:
    """Calculate raw agreement, Cohen's kappa, confusion, and per-label rates."""
    required = {"original_ground_truth", "reviewer_label"}
    if missing := sorted(required - set(joined.columns)):
        raise ConfigurationError("joined review data is missing: " + ", ".join(missing))
    if len(joined) == 0:
        raise ConfigurationError("agreement analysis requires at least one reviewed row")
    if not joined["original_ground_truth"].isin(LABELS).all():
        raise ConfigurationError("original labels contain an unsupported value")
    if not joined["reviewer_label"].isin(LABELS).all():
        raise ConfigurationError("reviewer labels contain an unsupported value")

    confusion_frame = pd.crosstab(
        pd.Categorical(joined["original_ground_truth"], categories=LABELS),
        pd.Categorical(joined["reviewer_label"], categories=LABELS),
        dropna=False,
    ).reindex(index=LABELS, columns=LABELS, fill_value=0)
    confusion = {
        original: {reviewer: int(confusion_frame.loc[original, reviewer]) for reviewer in LABELS}
        for original in LABELS
    }
    total = len(joined)
    agreed = sum(confusion[label][label] for label in LABELS)
    observed = agreed / total
    original_margins = {label: sum(confusion[label].values()) for label in LABELS}
    reviewer_margins = {
        label: sum(confusion[original][label] for original in LABELS) for label in LABELS
    }
    expected = sum(
        original_margins[label] * reviewer_margins[label] for label in LABELS
    ) / (total * total)
    if expected == 1.0:
        raise ConfigurationError("Cohen's kappa is undefined because expected agreement is 1")
    kappa = (observed - expected) / (1 - expected)
    per_label = {
        label: (
            confusion[label][label],
            original_margins[label],
            confusion[label][label] / original_margins[label],
        )
        for label in LABELS
    }
    return AgreementResult(
        sample_count=total,
        agreement_count=agreed,
        raw_agreement=observed,
        cohens_kappa=kappa,
        confusion=confusion,
        per_label=per_label,
        joined=joined,
    )


def agreement_rows(result: AgreementResult) -> list[dict[str, Any]]:
    columns = {
        "record_type": "",
        "metric": "",
        "original_label": "",
        "reviewer_label": "",
        "numerator": "",
        "denominator": "",
        "value": "",
        "count": "",
    }
    rows = [
        columns
        | {
            "record_type": "summary",
            "metric": "raw_agreement",
            "numerator": result.agreement_count,
            "denominator": result.sample_count,
            "value": result.raw_agreement,
        },
        columns
        | {
            "record_type": "summary",
            "metric": "cohens_kappa",
            "denominator": result.sample_count,
            "value": result.cohens_kappa,
        },
    ]
    for label in LABELS:
        numerator, denominator, value = result.per_label[label]
        rows.append(
            columns
            | {
                "record_type": "per_label_agreement",
                "metric": "agreement_within_original_label",
                "original_label": label,
                "numerator": numerator,
                "denominator": denominator,
                "value": value,
            }
        )
    for original in LABELS:
        for reviewer in LABELS:
            rows.append(
                columns
                | {
                    "record_type": "confusion_matrix",
                    "metric": "count",
                    "original_label": original,
                    "reviewer_label": reviewer,
                    "count": result.confusion[original][reviewer],
                }
            )
    return rows


def disagreement_frame(result: AgreementResult) -> pd.DataFrame:
    columns = [
        "reviewer_scenario_id",
        "scenario_id",
        "scenario_description",
        "role",
        "tool",
        "sensitivity",
        "destination",
        "context_risk",
        "original_ground_truth",
        "reviewer_label",
        "reviewer_notes",
    ]
    disagreements = result.joined[
        result.joined["original_ground_truth"] != result.joined["reviewer_label"]
    ]
    return disagreements.reindex(columns=columns).sort_values("reviewer_scenario_id")


def render_report(result: AgreementResult) -> str:
    confusion_header = "| Original \\ Reviewer | " + " | ".join(LABELS) + " |"
    confusion_rule = "| --- | " + " | ".join("---:" for _ in LABELS) + " |"
    confusion_rows = [
        f"| {original} | "
        + " | ".join(str(result.confusion[original][reviewer]) for reviewer in LABELS)
        + " |"
        for original in LABELS
    ]
    per_label_rows = [
        f"| {label} | {result.per_label[label][0]} | {result.per_label[label][1]} | {result.per_label[label][2]:.4f} |"
        for label in LABELS
    ]
    disagreement_count = result.sample_count - result.agreement_count
    return "\n".join(
        [
            "# Ground-Truth Label Validation",
            "",
            "## Agreement measurement",
            "",
            f"The independent reviewer completed {result.sample_count} blinded scenarios.",
            "",
            f"- Raw agreement: {result.agreement_count}/{result.sample_count} ({result.raw_agreement:.2%})",
            f"- Cohen's kappa: {result.cohens_kappa:.4f}",
            f"- Disagreements: {disagreement_count}",
            "",
            "Per-label agreement is the diagonal count divided by the number of scenarios carrying that original label.",
            "",
            "| Original label | Agreements | Original-label total | Agreement rate |",
            "| --- | ---: | ---: | ---: |",
            *per_label_rows,
            "",
            "## Confusion matrix",
            "",
            confusion_header,
            confusion_rule,
            *confusion_rows,
            "",
            "Rows are original independent ground-truth labels; columns are reviewer labels.",
            "",
            "## Later adjudication",
            "",
            "Agreement measurement does not alter or adjudicate any label. All disagreements are listed in `results/reviewer_disagreements.csv` for later human review.",
            "",
            "No disagreement was automatically resolved, and `data/scenarios.yaml` was not modified. Any later dataset change requires explicit human adjudication and a separately documented decision.",
            "",
        ]
    )


def write_outputs(
    result: AgreementResult,
    *,
    agreement_path: str | Path = DEFAULT_AGREEMENT_PATH,
    disagreements_path: str | Path = DEFAULT_DISAGREEMENTS_PATH,
    report_path: str | Path = DEFAULT_REPORT_PATH,
) -> None:
    Path(agreement_path).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(agreement_rows(result)).to_csv(agreement_path, index=False)
    disagreement_frame(result).to_csv(disagreements_path, index=False)
    Path(report_path).write_text(render_report(result), encoding="utf-8")


def run_agreement_analysis(
    *,
    completed_sample_path: str | Path = DEFAULT_SAMPLE_PATH,
    key_path: str | Path = DEFAULT_KEY_PATH,
) -> AgreementResult:
    frozen_hash = _sha256(DEFAULT_SCENARIOS_PATH)
    scenarios = load_final_scenarios()
    joined = load_joined_reviews(
        scenarios,
        completed_sample_path=completed_sample_path,
        key_path=key_path,
    )
    result = calculate_agreement(joined)
    if _sha256(DEFAULT_SCENARIOS_PATH) != frozen_hash:
        raise ConfigurationError("the frozen experiment dataset changed during agreement analysis")
    write_outputs(result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze independent reviewer agreement")
    parser.add_argument("--completed-sample", default=str(DEFAULT_SAMPLE_PATH))
    parser.add_argument("--key", default=str(DEFAULT_KEY_PATH))
    args = parser.parse_args(argv)
    try:
        result = run_agreement_analysis(
            completed_sample_path=args.completed_sample,
            key_path=args.key,
        )
    except ConfigurationError as exc:
        print(f"agreement analysis aborted: {exc}", file=sys.stderr)
        return 2
    print(f"raw_agreement={result.raw_agreement:.6f}")
    print(f"cohens_kappa={result.cohens_kappa:.6f}")
    print(f"disagreements={result.sample_count - result.agreement_count}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
