"""Secondary threshold sensitivity analysis over frozen scenario risk scores."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis.evaluate_experiment import DEFAULT_RESULTS_DIR, frozen_input_hashes
from src.models import ConfigurationError, Decision
from src.policy import load_policy_matrix

T1_GRID: tuple[float, ...] = (0.30, 0.40, 0.50)
T2_GRID: tuple[float, ...] = (0.60, 0.70, 0.80)
DEFAULT_DECISIONS_PATH = DEFAULT_RESULTS_DIR / "decisions.csv"
DEFAULT_OUTPUT_PATH = DEFAULT_RESULTS_DIR / "threshold_sensitivity.csv"
DEFAULT_FIGURE_PATH = DEFAULT_RESULTS_DIR / "threshold_sensitivity.png"


def valid_grid_pairs() -> tuple[tuple[float, float], ...]:
    return tuple((t1, t2) for t1 in T1_GRID for t2 in T2_GRID if t1 < t2)


def _file_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def classify(scores: pd.Series, t1: float, t2: float) -> pd.Series:
    if not 0.0 <= t1 < t2 <= 1.0:
        raise ConfigurationError("threshold pair must satisfy 0 <= T1 < T2 <= 1")
    return pd.Series(
        np.where(
            scores.to_numpy(dtype=float) < t1,
            Decision.ALLOW.value,
            np.where(
                scores.to_numpy(dtype=float) < t2,
                Decision.ESCALATE.value,
                Decision.DENY.value,
            ),
        ),
        index=scores.index,
    )


def _rate(
    ground_truth: pd.Series,
    predictions: pd.Series,
    *,
    truth: Decision,
    predicted: Decision,
) -> tuple[int, int, float]:
    subset = ground_truth == truth.value
    denominator = int(subset.sum())
    if denominator == 0:
        raise ConfigurationError(f"no true-{truth.value} scenarios in decisions")
    numerator = int(((predictions == predicted.value) & subset).sum())
    return numerator, denominator, numerator / denominator


def metric_row(
    decisions: pd.DataFrame,
    *,
    t1: float,
    t2: float,
    configuration_type: str,
    is_primary: bool,
) -> dict[str, Any]:
    predictions = classify(decisions["risk_score"], t1, t2)
    ground_truth = decisions["ground_truth"]
    definitions = {
        "UER": (Decision.DENY, Decision.ALLOW),
        "LDCR": (Decision.ALLOW, Decision.ALLOW),
        "OER": (Decision.ALLOW, Decision.ESCALATE),
        "CER": (Decision.ESCALATE, Decision.ESCALATE),
    }
    row: dict[str, Any] = {
        "configuration_type": configuration_type,
        "is_preregistered_primary": is_primary,
        "T1": t1,
        "T2": t2,
    }
    for name, (truth, predicted) in definitions.items():
        numerator, denominator, rate = _rate(
            ground_truth,
            predictions,
            truth=truth,
            predicted=predicted,
        )
        row[f"{name}_numerator"] = numerator
        row[f"{name}_denominator"] = denominator
        row[name] = rate
    return row


def sensitivity_table(decisions: pd.DataFrame) -> pd.DataFrame:
    required = {"scenario_id", "ground_truth", "risk_score"}
    missing = sorted(required - set(decisions.columns))
    if missing:
        raise ConfigurationError(
            "decisions.csv is missing required column(s): " + ", ".join(missing)
        )
    if len(decisions) != 150 or decisions["scenario_id"].nunique() != 150:
        raise ConfigurationError("sensitivity analysis requires 150 unique paired decisions")
    if decisions["risk_score"].isna().any() or not decisions["risk_score"].between(0, 1).all():
        raise ConfigurationError("all frozen risk scores must lie in [0,1]")

    matrix = load_policy_matrix()
    primary_t1, primary_t2 = matrix.thresholds.locked_thresholds()
    rows = [
        metric_row(
            decisions,
            t1=primary_t1,
            t2=primary_t2,
            configuration_type="preregistered_primary_reference",
            is_primary=True,
        )
    ]
    rows.extend(
        metric_row(
            decisions,
            t1=t1,
            t2=t2,
            configuration_type="secondary_sensitivity_grid",
            is_primary=False,
        )
        for t1, t2 in valid_grid_pairs()
    )
    return pd.DataFrame(rows)


def create_tradeoff_figure(table: pd.DataFrame, path: str | Path) -> None:
    """Plot UER versus LDCR with the primary configuration visibly separate."""
    primary = table[table["is_preregistered_primary"]]
    secondary = table[~table["is_preregistered_primary"]]
    # UER and LDCR depend on the ALLOW boundary T1, so configurations sharing
    # T1 coincide in this two-metric projection. Plot one point per T1 and keep
    # every T1/T2 pair in the machine-readable table.
    projected = secondary.groupby("T1", as_index=False)[["UER", "LDCR"]].first()

    figure, axis = plt.subplots(figsize=(7.0, 5.0))
    axis.scatter(projected["UER"], projected["LDCR"], label="Secondary grid")
    for row in projected.itertuples(index=False):
        right_side = row.UER == projected["UER"].max()
        axis.annotate(
            f"T1={row.T1:.2f}",
            (row.UER, row.LDCR),
            xytext=(-5 if right_side else 5, -18 if right_side else 7),
            textcoords="offset points",
            ha="right" if right_side else "left",
        )
    axis.scatter(
        primary["UER"],
        primary["LDCR"],
        marker="*",
        s=160,
        label=f"Preregistered primary ({primary.iloc[0]['T1']:.2f}, {primary.iloc[0]['T2']:.2f})",
    )
    axis.set_xlabel("Unsafe Execution Rate (lower is safer)")
    axis.set_ylabel("Legitimate Direct Completion Rate (higher is more direct completion)")
    axis.set_title("Secondary threshold sensitivity: safety/usability trade-off")
    axis.set_xlim(0, float(max(table["UER"])) * 1.15)
    axis.set_ylim(0, 1.12)
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(figure)


def run_sensitivity(
    *,
    decisions_path: str | Path = DEFAULT_DECISIONS_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    figure_path: str | Path = DEFAULT_FIGURE_PATH,
) -> pd.DataFrame:
    frozen_before = frozen_input_hashes()
    decisions_hash_before = _file_hash(decisions_path)
    decisions = pd.read_csv(decisions_path)
    table = sensitivity_table(decisions)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output_path, index=False)
    create_tradeoff_figure(table, figure_path)
    if frozen_input_hashes() != frozen_before:
        raise ConfigurationError("a frozen experiment input changed during sensitivity analysis")
    if _file_hash(decisions_path) != decisions_hash_before:
        raise ConfigurationError("primary decisions.csv changed during sensitivity analysis")
    return table


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run secondary frozen-score threshold sensitivity")
    parser.add_argument("--decisions", default=str(DEFAULT_DECISIONS_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--figure", default=str(DEFAULT_FIGURE_PATH))
    args = parser.parse_args(argv)
    table = run_sensitivity(
        decisions_path=args.decisions,
        output_path=args.output,
        figure_path=args.figure,
    )
    print(table.to_string(index=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
