"""Run the frozen matched-pair experiment and write measurement outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from src.abac import ABACEngine
from src.calibration import DEFAULT_RISK_CONFIG_PATH, verify_calibrated_configuration
from src.evaluator import Evaluator
from src.models import ConfigurationError, Decision, Method, Scenario
from src.policy import (
    DEFAULT_POLICY_MATRIX_PATH,
    DEFAULT_SCENARIOS_PATH,
    load_final_scenarios,
    load_policy_matrix,
)
from src.risk_engine import RiskEngine

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results" / "exploratory"
ANALYSIS_SEED = 20260918
BOOTSTRAP_REPLICATES = 10_000
CI_LEVEL = 0.95


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen_input_hashes() -> dict[str, str]:
    return {
        "scenarios_sha256": _sha256(DEFAULT_SCENARIOS_PATH),
        "policy_matrix_sha256": _sha256(DEFAULT_POLICY_MATRIX_PATH),
        "risk_config_sha256": _sha256(DEFAULT_RISK_CONFIG_PATH),
    }


def evaluate_frozen_scenarios(scenarios: Sequence[Scenario]) -> pd.DataFrame:
    """Evaluate identical scenarios once per method, timing authorization only."""
    matrix = load_policy_matrix()
    verify_calibrated_configuration(matrix)
    abac = Evaluator(ABACEngine.from_policy_matrix(matrix), Method.ABAC_BINARY)
    risk = Evaluator(RiskEngine.from_policy_matrix(matrix), Method.RISK_ADAPTIVE)

    rows: list[dict[str, Any]] = []
    for index, scenario in enumerate(scenarios):
        # Alternate call order to avoid assigning all first-call/cache effects to
        # one method. Each recorded duration still encloses authorization only.
        if index % 2 == 0:
            abac_result = abac.evaluate(scenario)
            risk_result = risk.evaluate(scenario)
        else:
            risk_result = risk.evaluate(scenario)
            abac_result = abac.evaluate(scenario)
        rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "role": scenario.role.value,
                "tool": scenario.tool.value,
                "sensitivity": scenario.sensitivity.value,
                "destination": scenario.destination.value,
                "context_risk": scenario.context_risk.value,
                "ground_truth": scenario.ground_truth.value if scenario.ground_truth else None,
                "abac_decision": abac_result.decision.value,
                "risk_adaptive_decision": risk_result.decision.value,
                "risk_score": risk_result.score,
                "abac_latency_ms": abac_result.latency_ms,
                "risk_adaptive_latency_ms": risk_result.latency_ms,
                "abac_explanation": abac_result.explanation,
                "risk_adaptive_explanation": risk_result.explanation,
                "abac_correct_for_binary_safe_execution": (
                    abac_result.correct_for_binary_safe_execution
                ),
                "true_escalate_resolved_as_allow": (
                    abac_result.true_escalate_resolved_as_allow
                ),
                "true_escalate_resolved_as_deny": (
                    abac_result.true_escalate_resolved_as_deny
                ),
            }
        )
    frame = pd.DataFrame(rows)
    if frame["scenario_id"].duplicated().any() or len(frame) != len(scenarios):
        raise ConfigurationError("paired evaluation did not produce one row per scenario")
    return frame


def wilson_interval(successes: int, total: int) -> tuple[float, float]:
    if total <= 0:
        raise ConfigurationError("rate denominator must be positive")
    z = float(stats.norm.ppf(0.5 + CI_LEVEL / 2))
    estimate = successes / total
    denominator = 1 + z * z / total
    centre = (estimate + z * z / (2 * total)) / denominator
    half = z * np.sqrt(
        estimate * (1 - estimate) / total + z * z / (4 * total * total)
    ) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def _metric_row(
    method: str, metric: str, numerator: int, denominator: int
) -> dict[str, Any]:
    lower, upper = wilson_interval(numerator, denominator)
    return {
        "method": method,
        "metric": metric,
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator,
        "ci_level": CI_LEVEL,
        "ci_lower": lower,
        "ci_upper": upper,
        "ci_method": "Wilson score interval",
    }


def primary_metrics(decisions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    definitions: tuple[tuple[str, str, Callable[[pd.Series], pd.Series]], ...] = (
        (
            "UER",
            Decision.DENY.value,
            lambda values: values == Decision.ALLOW.value,
        ),
        (
            "LDCR",
            Decision.ALLOW.value,
            lambda values: values == Decision.ALLOW.value,
        ),
        (
            "OER",
            Decision.ALLOW.value,
            lambda values: values == Decision.ESCALATE.value,
        ),
        (
            "CER",
            Decision.ESCALATE.value,
            lambda values: values == Decision.ESCALATE.value,
        ),
    )
    for method, column in (
        (Method.ABAC_BINARY.value, "abac_decision"),
        (Method.RISK_ADAPTIVE.value, "risk_adaptive_decision"),
    ):
        for metric, label, event in definitions:
            subset = decisions.loc[decisions["ground_truth"] == label, column]
            rows.append(_metric_row(method, metric, int(event(subset).sum()), len(subset)))
    return pd.DataFrame(rows)


def escalation_analysis(decisions: pd.DataFrame) -> pd.DataFrame:
    subset = decisions[decisions["ground_truth"] == Decision.ESCALATE.value]
    denominator = len(subset)
    definitions = (
        (Method.ABAC_BINARY.value, "resolved_ALLOW", "abac_decision", Decision.ALLOW),
        (Method.ABAC_BINARY.value, "resolved_DENY", "abac_decision", Decision.DENY),
        (
            Method.RISK_ADAPTIVE.value,
            "correctly_ESCALATE_CER",
            "risk_adaptive_decision",
            Decision.ESCALATE,
        ),
        (
            Method.RISK_ADAPTIVE.value,
            "incorrectly_ALLOW",
            "risk_adaptive_decision",
            Decision.ALLOW,
        ),
        (
            Method.RISK_ADAPTIVE.value,
            "incorrectly_DENY",
            "risk_adaptive_decision",
            Decision.DENY,
        ),
    )
    return pd.DataFrame(
        [
            _metric_row(
                method,
                metric,
                int((subset[column] == decision.value).sum()),
                denominator,
            )
            for method, metric, column, decision in definitions
        ]
    )


def _paired_table(a: np.ndarray, b: np.ndarray) -> dict[str, int]:
    return {
        "both_event": int(np.sum(a & b)),
        "abac_only": int(np.sum(a & ~b)),
        "risk_adaptive_only": int(np.sum(~a & b)),
        "neither_event": int(np.sum(~a & ~b)),
    }


def _paired_bootstrap_difference(
    a: np.ndarray, b: np.ndarray, *, seed_offset: int
) -> tuple[float, float]:
    rng = np.random.default_rng(ANALYSIS_SEED + seed_offset)
    n = len(a)
    indices = rng.integers(0, n, size=(BOOTSTRAP_REPLICATES, n))
    differences = b[indices].mean(axis=1) - a[indices].mean(axis=1)
    return tuple(float(value) for value in np.percentile(differences, [2.5, 97.5]))


def _mcnemar_row(
    decisions: pd.DataFrame,
    *,
    metric: str,
    ground_truth: Decision,
    event: Callable[[pd.Series], pd.Series],
    seed_offset: int,
) -> dict[str, Any]:
    subset = decisions[decisions["ground_truth"] == ground_truth.value]
    a = event(subset["abac_decision"]).to_numpy(dtype=bool)
    b = event(subset["risk_adaptive_decision"]).to_numpy(dtype=bool)
    table = _paired_table(a, b)
    discordant = table["abac_only"] + table["risk_adaptive_only"]
    p_value = (
        1.0
        if discordant == 0
        else float(
            stats.binomtest(
                min(table["abac_only"], table["risk_adaptive_only"]),
                discordant,
                0.5,
                alternative="two-sided",
            ).pvalue
        )
    )
    lower, upper = _paired_bootstrap_difference(a, b, seed_offset=seed_offset)
    return {
        "analysis_subset": f"ground_truth={ground_truth.value}",
        "comparison": f"{metric}: risk_adaptive minus abac_binary",
        "test": "exact McNemar (exact binomial on discordant pairs)",
        "n": len(subset),
        "paired_table": json.dumps(table, sort_keys=True),
        "statistic": min(table["abac_only"], table["risk_adaptive_only"]),
        "p_value": p_value,
        "effect": float(b.mean() - a.mean()),
        "effect_ci_lower": lower,
        "effect_ci_upper": upper,
        "effect_ci_method": f"paired percentile bootstrap, {BOOTSTRAP_REPLICATES} replicates, seed {ANALYSIS_SEED + seed_offset}",
        "notes": "Binary paired event comparison; McNemar is valid for this metric-specific event.",
    }


def decision_statistical_tests(decisions: pd.DataFrame) -> list[dict[str, Any]]:
    rows = [
        _mcnemar_row(
            decisions,
            metric="UER",
            ground_truth=Decision.DENY,
            event=lambda values: values == Decision.ALLOW.value,
            seed_offset=1,
        ),
        _mcnemar_row(
            decisions,
            metric="LDCR",
            ground_truth=Decision.ALLOW,
            event=lambda values: values == Decision.ALLOW.value,
            seed_offset=2,
        ),
        _mcnemar_row(
            decisions,
            metric="OER",
            ground_truth=Decision.ALLOW,
            event=lambda values: values == Decision.ESCALATE.value,
            seed_offset=3,
        ),
        _mcnemar_row(
            decisions,
            metric="CER",
            ground_truth=Decision.ESCALATE,
            event=lambda values: values == Decision.ESCALATE.value,
            seed_offset=4,
        ),
    ]
    categories = [decision.value for decision in Decision]
    contingency = pd.crosstab(
        pd.Categorical(decisions["abac_decision"], categories=categories),
        pd.Categorical(decisions["risk_adaptive_decision"], categories=categories),
        dropna=False,
    ).reindex(index=categories, columns=categories, fill_value=0)
    rows.append(
        {
            "analysis_subset": "all scenarios",
            "comparison": "paired three-way decisions",
            "test": "descriptive 3x3 paired contingency table",
            "n": len(decisions),
            "paired_table": json.dumps(
                {
                    row: {column: int(contingency.loc[row, column]) for column in categories}
                    for row in categories
                },
                sort_keys=True,
            ),
            "statistic": np.nan,
            "p_value": np.nan,
            "effect": np.nan,
            "effect_ci_lower": np.nan,
            "effect_ci_upper": np.nan,
            "effect_ci_method": "not applicable",
            "notes": "Descriptive only: McNemar's binary test is not applied mechanically to three-category outcomes.",
        }
    )
    return rows


def latency_outputs(decisions: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    summaries: list[dict[str, Any]] = []
    arrays: dict[str, np.ndarray] = {}
    for method, column in (
        (Method.ABAC_BINARY.value, "abac_latency_ms"),
        (Method.RISK_ADAPTIVE.value, "risk_adaptive_latency_ms"),
    ):
        values = decisions[column].to_numpy(dtype=float)
        arrays[method] = values
        summaries.append(
            {
                "method": method,
                "n": len(values),
                "mean_ms": float(np.mean(values)),
                "median_ms": float(np.median(values)),
                "p95_ms": float(np.percentile(values, 95)),
                "p99_ms": float(np.percentile(values, 99)),
            }
        )

    differences = arrays[Method.RISK_ADAPTIVE.value] - arrays[Method.ABAC_BINARY.value]
    if np.allclose(differences, differences[0]):
        shapiro_stat, shapiro_p = np.nan, np.nan
        normality_note = "Paired differences are constant; normality test is undefined."
    else:
        shapiro = stats.shapiro(differences)
        shapiro_stat, shapiro_p = float(shapiro.statistic), float(shapiro.pvalue)
        normality_note = "Shapiro-Wilk test applied to paired latency differences."
    diagnostic = {
        "analysis_subset": "all paired scenarios",
        "comparison": "latency distribution of risk_adaptive minus abac_binary",
        "test": "Shapiro-Wilk normality diagnostic",
        "n": len(differences),
        "paired_table": "",
        "statistic": shapiro_stat,
        "p_value": shapiro_p,
        "effect": float(np.mean(differences)),
        "effect_ci_lower": np.nan,
        "effect_ci_upper": np.nan,
        "effect_ci_method": "not applicable",
        "notes": normality_note,
    }

    rng = np.random.default_rng(ANALYSIS_SEED + 100)
    indices = rng.integers(0, len(differences), size=(BOOTSTRAP_REPLICATES, len(differences)))
    median_bootstrap = np.median(differences[indices], axis=1)
    ci_lower, ci_upper = (float(value) for value in np.percentile(median_bootstrap, [2.5, 97.5]))
    if np.isnan(shapiro_p) or shapiro_p < 0.05:
        test_name = "Wilcoxon signed-rank test"
        test_result = stats.wilcoxon(
            arrays[Method.RISK_ADAPTIVE.value],
            arrays[Method.ABAC_BINARY.value],
            alternative="two-sided",
            zero_method="wilcox",
        )
        statistic, p_value = float(test_result.statistic), float(test_result.pvalue)
        notes = "Selected after paired-difference normality inspection; no normality assumption."
    else:
        test_name = "paired t-test"
        test_result = stats.ttest_rel(
            arrays[Method.RISK_ADAPTIVE.value],
            arrays[Method.ABAC_BINARY.value],
        )
        statistic, p_value = float(test_result.statistic), float(test_result.pvalue)
        notes = "Selected only after paired differences did not reject normality at alpha=0.05."
    comparison = {
        "analysis_subset": "all paired scenarios",
        "comparison": "authorization latency: risk_adaptive minus abac_binary",
        "test": test_name,
        "n": len(differences),
        "paired_table": "",
        "statistic": statistic,
        "p_value": p_value,
        "effect": float(np.median(differences)),
        "effect_ci_lower": ci_lower,
        "effect_ci_upper": ci_upper,
        "effect_ci_method": f"paired percentile bootstrap of median difference, {BOOTSTRAP_REPLICATES} replicates, seed {ANALYSIS_SEED + 100}",
        "notes": notes,
    }
    return pd.DataFrame(summaries), [diagnostic, comparison]


def run_and_write(results_dir: str | Path = DEFAULT_RESULTS_DIR) -> dict[str, Path]:
    output_dir = Path(results_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    before = frozen_input_hashes()
    scenarios = load_final_scenarios()
    decisions = evaluate_frozen_scenarios(scenarios)
    after = frozen_input_hashes()
    if before != after:
        raise ConfigurationError("a frozen experiment input changed during evaluation")

    metrics = primary_metrics(decisions)
    escalation = escalation_analysis(decisions)
    statistical_rows = decision_statistical_tests(decisions)
    latency, latency_tests = latency_outputs(decisions)
    statistical = pd.DataFrame(statistical_rows + latency_tests)

    paths = {
        "decisions": output_dir / "decisions.csv",
        "summary_metrics": output_dir / "summary_metrics.csv",
        "escalation_analysis": output_dir / "escalation_analysis.csv",
        "statistical_tests": output_dir / "statistical_tests.csv",
        "latency_summary": output_dir / "latency_summary.csv",
    }
    decisions.to_csv(paths["decisions"], index=False)
    metrics.to_csv(paths["summary_metrics"], index=False)
    escalation.to_csv(paths["escalation_analysis"], index=False)
    statistical.to_csv(paths["statistical_tests"], index=False)
    latency.to_csv(paths["latency_summary"], index=False)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenario_count": len(scenarios),
        "matched_pair_design": True,
        "authorization_logic_only_latency": True,
        "analysis_seed": ANALYSIS_SEED,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "frozen_input_hashes_before": before,
        "frozen_input_hashes_after": after,
        "outputs": {name: str(path) for name, path in paths.items()},
    }
    (output_dir / "evaluation_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return paths


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run frozen paired evaluation and statistics")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    args = parser.parse_args(argv)
    paths = run_and_write(args.results_dir)
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
