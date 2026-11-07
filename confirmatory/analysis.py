"""Prespecified confirmatory metrics and paired comparisons."""

from __future__ import annotations

import json
from typing import Any, Callable

import numpy as np
import pandas as pd
from scipy import stats

from src.models import ConfigurationError, Decision

ANALYSIS_SEED = 20260918
BOOTSTRAP_REPLICATES = 10_000
CI_METHOD = "95% empirical scenario-resampling percentile interval"
PRIMARY_METRICS = ("UER", "LDCR")
DESCRIPTIVE_METRICS = ("OER", "CER")

METRIC_DEFINITIONS: dict[str, tuple[Decision, Decision]] = {
    "UER": (Decision.DENY, Decision.ALLOW),
    "LDCR": (Decision.ALLOW, Decision.ALLOW),
    "OER": (Decision.ALLOW, Decision.ESCALATE),
    "CER": (Decision.ESCALATE, Decision.ESCALATE),
}
METHOD_COLUMNS = {
    "context_aware_binary_abac": "context_abac_decision",
    "risk_adaptive": "risk_adaptive_decision",
}


def _event_values(
    decisions: pd.DataFrame,
    column: str,
    metric: str,
) -> np.ndarray:
    truth, predicted = METRIC_DEFINITIONS[metric]
    subset = decisions.loc[decisions["ground_truth"] == truth.value, column]
    if subset.empty:
        raise ConfigurationError(f"no true-{truth.value} scenarios for {metric}")
    return (subset == predicted.value).to_numpy(dtype=bool)


def _empirical_rate_interval(values: np.ndarray, *, seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(values), size=(BOOTSTRAP_REPLICATES, len(values)))
    rates = values[indices].mean(axis=1)
    lower, upper = np.percentile(rates, [2.5, 97.5])
    return float(lower), float(upper)


def summary_metrics(decisions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    seed_offset = 0
    for method, column in METHOD_COLUMNS.items():
        for metric in (*PRIMARY_METRICS, *DESCRIPTIVE_METRICS):
            values = _event_values(decisions, column, metric)
            lower, upper = _empirical_rate_interval(
                values, seed=ANALYSIS_SEED + seed_offset
            )
            seed_offset += 1
            rows.append(
                {
                    "method": method,
                    "metric": metric,
                    "analysis_role": (
                        "primary_confirmatory"
                        if metric in PRIMARY_METRICS
                        else "descriptive_structural"
                    ),
                    "numerator": int(values.sum()),
                    "denominator": len(values),
                    "rate": float(values.mean()),
                    "ci_level": 0.95,
                    "ci_lower": lower,
                    "ci_upper": upper,
                    "ci_method": CI_METHOD,
                    "generalization_scope": "frozen purposive synthetic benchmark only",
                }
            )
    return pd.DataFrame(rows)


def _paired_bootstrap_difference(
    comparator: np.ndarray,
    risk: np.ndarray,
    *,
    seed: int,
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    indices = rng.integers(
        0, len(comparator), size=(BOOTSTRAP_REPLICATES, len(comparator))
    )
    differences = risk[indices].mean(axis=1) - comparator[indices].mean(axis=1)
    lower, upper = np.percentile(differences, [2.5, 97.5])
    return float(lower), float(upper)


def _holm_adjust(p_values: list[float]) -> list[float]:
    order = np.argsort(p_values)
    adjusted = np.empty(len(p_values), dtype=float)
    running = 0.0
    total = len(p_values)
    for rank, index in enumerate(order):
        candidate = min(1.0, (total - rank) * p_values[int(index)])
        running = max(running, candidate)
        adjusted[int(index)] = running
    return adjusted.tolist()


def primary_paired_tests(decisions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for offset, metric in enumerate(PRIMARY_METRICS, start=100):
        comparator = _event_values(
            decisions, METHOD_COLUMNS["context_aware_binary_abac"], metric
        )
        risk = _event_values(decisions, METHOD_COLUMNS["risk_adaptive"], metric)
        comparator_only = int(np.sum(comparator & ~risk))
        risk_only = int(np.sum(~comparator & risk))
        discordant = comparator_only + risk_only
        raw_p = (
            1.0
            if discordant == 0
            else float(
                stats.binomtest(
                    min(comparator_only, risk_only),
                    discordant,
                    0.5,
                    alternative="two-sided",
                ).pvalue
            )
        )
        lower, upper = _paired_bootstrap_difference(
            comparator, risk, seed=ANALYSIS_SEED + offset
        )
        rows.append(
            {
                "metric": metric,
                "comparison": "risk_adaptive minus context_aware_binary_abac",
                "test": "exact McNemar on prespecified binary event",
                "n": len(comparator),
                "paired_table": json.dumps(
                    {
                        "both_event": int(np.sum(comparator & risk)),
                        "comparator_only": comparator_only,
                        "risk_adaptive_only": risk_only,
                        "neither_event": int(np.sum(~comparator & ~risk)),
                    },
                    sort_keys=True,
                ),
                "raw_p_value": raw_p,
                "holm_adjusted_p_value": np.nan,
                "holm_family": "UER and LDCR primary confirmatory comparisons",
                "effect": float(risk.mean() - comparator.mean()),
                "effect_ci_lower": lower,
                "effect_ci_upper": upper,
                "effect_ci_method": CI_METHOD + ", paired scenarios",
                "generalization_scope": "frozen purposive synthetic benchmark only",
            }
        )
    adjusted = _holm_adjust([float(row["raw_p_value"]) for row in rows])
    for row, value in zip(rows, adjusted, strict=True):
        row["holm_adjusted_p_value"] = value
    return pd.DataFrame(rows)


def escalation_resolution(decisions: pd.DataFrame) -> pd.DataFrame:
    subset = decisions[decisions["ground_truth"] == Decision.ESCALATE.value]
    rows: list[dict[str, Any]] = []
    for method, column, categories in (
        (
            "context_aware_binary_abac",
            "context_abac_decision",
            (Decision.ALLOW, Decision.DENY),
        ),
        (
            "risk_adaptive",
            "risk_adaptive_decision",
            (Decision.ALLOW, Decision.ESCALATE, Decision.DENY),
        ),
    ):
        for category in categories:
            numerator = int((subset[column] == category.value).sum())
            rows.append(
                {
                    "method": method,
                    "predicted_decision": category.value,
                    "numerator": numerator,
                    "denominator": len(subset),
                    "rate": numerator / len(subset),
                    "analysis_role": "descriptive_structural",
                }
            )
    return pd.DataFrame(rows)

