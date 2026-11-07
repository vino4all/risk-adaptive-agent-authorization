"""Post-hoc descriptive sensitivity of the frozen ordinal-to-scalar mappings."""

from __future__ import annotations

import csv
import argparse
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from confirmatory.analysis import METRIC_DEFINITIONS
from confirmatory.comparator import ContextAwareABACEngine
from confirmatory.provenance import REPOSITORY_ROOT, sha256_file, verify_freeze
from src.models import ConfigurationError, Decision
from src.policy import load_final_scenarios, load_policy_matrix
from src.risk_engine import RiskEngine

INPUT = REPOSITORY_ROOT / "confirmatory" / "inputs"
PRIMARY = REPOSITORY_ROOT / "confirmatory" / "results" / "authorization"
OUTPUT = REPOSITORY_ROOT / "confirmatory" / "results" / "ordinal_mapping_sensitivity"
PROTECTED = (
    INPUT / "scenarios.yaml",
    INPUT / "risk_config.yaml",
    INPUT / "policy_matrix.yaml",
    INPUT / "context_aware_abac.yaml",
    INPUT / "analysis_plan.md",
    PRIMARY / "decisions.csv",
    PRIMARY / "summary_metrics.csv",
    PRIMARY / "primary_statistical_tests.csv",
    PRIMARY / "escalation_analysis.csv",
    PRIMARY / "run_manifest.json",
)
TRANSITIONS = tuple(
    f"{old}_to_{new}"
    for old, new in (
        ("ALLOW", "ESCALATE"), ("ALLOW", "DENY"),
        ("ESCALATE", "ALLOW"), ("ESCALATE", "DENY"),
        ("DENY", "ESCALATE"), ("DENY", "ALLOW"),
    )
)

# This finite set is specified by the peer-review request before this run.
# Each alternative changes exactly one ordinal factor; no grid is searched.
CONFIGURATIONS = (
    ("primary", None, None),
    ("sensitivity_lower_middle", "sensitivity", {"INTERNAL": 0.0, "CONFIDENTIAL": 0.25, "RESTRICTED": 1.0}),
    ("sensitivity_upper_middle", "sensitivity", {"INTERNAL": 0.0, "CONFIDENTIAL": 0.75, "RESTRICTED": 1.0}),
    ("exposure_lower_middle", "exposure_scope", {"INTERNAL": 0.0, "CONTROLLED_EXTERNAL": 0.25, "EXTERNAL": 1.0}),
    ("exposure_upper_middle", "exposure_scope", {"INTERNAL": 0.0, "CONTROLLED_EXTERNAL": 0.75, "EXTERNAL": 1.0}),
    ("context_lower_middle", "contextual_risk", {"NORMAL": 0.0, "UNUSUAL": 0.20, "HIGH_VOLUME": 0.50, "ANOMALOUS": 1.0}),
    ("context_upper_middle", "contextual_risk", {"NORMAL": 0.0, "UNUSUAL": 0.50, "HIGH_VOLUME": 0.80, "ANOMALOUS": 1.0}),
    ("action_compressed", "action_severity", {"READ_RECORD": 0.0, "UPDATE_RECORD": 0.25, "SEND_MESSAGE": 0.25, "EXPORT_DATA": 0.50, "DELETE_RECORD": 1.0}),
    ("action_elevated", "action_severity", {"READ_RECORD": 0.0, "UPDATE_RECORD": 0.60, "SEND_MESSAGE": 0.60, "EXPORT_DATA": 0.85, "DELETE_RECORD": 1.0}),
)

# Declared before examining alternative outcomes: 10 percentage points for
# any metric, or 10% of scenarios (15/150) with a changed decision.  The
# primary qualitative finding is no observed UER gain over zero-event ABAC
# and at least a 10-point LDCR shortfall against its 100% completion rate.
MATERIAL_METRIC_CHANGE = 0.10
MATERIAL_DECISION_CHANGES = 15
QUALITATIVE_LDCR_SHORTFALL = 0.10


def _hashes() -> dict[str, str]:
    return {path.relative_to(REPOSITORY_ROOT).as_posix(): sha256_file(path) for path in PROTECTED}


def _rates(truth: list[str], decisions: list[str]) -> dict[str, dict[str, float | int]]:
    result = {}
    for metric, (expected_truth, predicted) in METRIC_DEFINITIONS.items():
        denominator = sum(value == expected_truth.value for value in truth)
        numerator = sum(
            actual == expected_truth.value and decision == predicted.value
            for actual, decision in zip(truth, decisions, strict=True)
        )
        if denominator == 0:
            raise ConfigurationError(f"no denominator for {metric}")
        result[metric] = {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator}
    return result


def run(output_dir: str | Path = OUTPUT) -> dict:
    destination = Path(output_dir).resolve()
    if destination == REPOSITORY_ROOT.resolve() or REPOSITORY_ROOT.resolve() in destination.parents:
        if destination != OUTPUT.resolve():
            raise ConfigurationError("alternate output directory must be outside the repository")
    freeze = verify_freeze()
    before = _hashes()
    if destination.exists() and any(destination.iterdir()):
        raise ConfigurationError(f"output directory is nonempty: {destination}")
    matrix = load_policy_matrix(INPUT / "policy_matrix.yaml")
    scenarios = load_final_scenarios(INPUT / "scenarios.yaml")
    recorded = pd.read_csv(PRIMARY / "decisions.csv").set_index("scenario_id")
    if len(scenarios) != 150 or len(recorded) != 150 or not recorded.index.is_unique:
        raise ConfigurationError("expected 150 distinct frozen scenario/decision pairs")
    if set(recorded.index) != {scenario.scenario_id for scenario in scenarios}:
        raise ConfigurationError("recorded decision identifiers differ from frozen scenarios")
    weights = matrix.risk_model.locked_weights()
    if any(weight != 0.25 for weight in weights.values()) or matrix.thresholds.locked_thresholds() != (0.20, 0.50):
        raise ConfigurationError("frozen weights or thresholds differ from requested values")
    comparator = ContextAwareABACEngine.from_files(matrix)
    primary_engine = RiskEngine.from_policy_matrix(matrix)
    truth = []
    primary_decisions = []
    primary_scores = []
    for scenario in scenarios:
        row = recorded.loc[scenario.scenario_id]
        decision = primary_engine.authorize(scenario)
        comparator_decision = comparator.authorize(scenario).decision.value
        if (
            scenario.ground_truth is None
            or scenario.ground_truth.value != row.ground_truth
            or comparator_decision != row.context_abac_decision
            or decision.decision.value != row.risk_adaptive_decision
            or abs(decision.score - float(row.risk_score)) > 1e-12
        ):
            raise ConfigurationError(f"primary replay mismatch: {scenario.scenario_id}")
        truth.append(row.ground_truth)
        primary_decisions.append(decision.decision.value)
        primary_scores.append(decision.score)
    primary_rates = _rates(truth, primary_decisions)
    for metric, values in primary_rates.items():
        recorded_metric = pd.read_csv(PRIMARY / "summary_metrics.csv")
        original = recorded_metric.loc[
            (recorded_metric.method == "risk_adaptive") & (recorded_metric.metric == metric)
        ].iloc[0]
        if (values["numerator"], values["denominator"]) != (int(original.numerator), int(original.denominator)):
            raise ConfigurationError(f"primary metric replay mismatch: {metric}")

    results = []
    changes = []
    mappings = {}
    for name, component, alternative in CONFIGURATIONS:
        factor_mappings = {key: dict(value) for key, value in matrix.risk_model.factor_mappings.items()}
        if component is not None:
            assert alternative is not None
            if set(alternative) != set(factor_mappings[component]):
                raise ConfigurationError(f"incomplete mapping: {name}")
            factor_mappings[component] = alternative
        for values in factor_mappings.values():
            if min(values.values()) < 0 or max(values.values()) > 1:
                raise ConfigurationError(f"out-of-range mapping: {name}")
        engine = RiskEngine(replace(matrix.risk_model, factor_mappings=factor_mappings), matrix.thresholds)
        decisions = []
        counts = {decision.value: 0 for decision in Decision}
        transitions = {transition: 0 for transition in TRANSITIONS}
        for index, scenario in enumerate(scenarios):
            outcome = engine.authorize(scenario)
            new = outcome.decision.value
            old = primary_decisions[index]
            decisions.append(new)
            counts[new] += 1
            if new != old:
                transitions[f"{old}_to_{new}"] += 1
                changes.append({
                    "configuration": name, "scenario_id": scenario.scenario_id,
                    "ground_truth": truth[index], "primary_decision": old,
                    "alternative_decision": new, "transition": f"{old}_to_{new}",
                    "primary_score": primary_scores[index], "alternative_score": outcome.score,
                })
        rates = _rates(truth, decisions)
        row = {"configuration": name, "changed_component": component or "none", "decision_changes": sum(transitions.values())}
        row.update({f"{key}_count": value for key, value in counts.items()})
        row.update(transitions)
        for metric, values in rates.items():
            row[f"{metric}_numerator"] = values["numerator"]
            row[f"{metric}_denominator"] = values["denominator"]
            row[metric] = values["rate"]
            difference = values["rate"] - primary_rates[metric]["rate"]
            row[f"{metric}_difference"] = difference
            if metric in ("UER", "LDCR"):
                row[f"{metric}_absolute_difference"] = abs(difference)
        results.append(row)
        mappings[name] = factor_mappings

    alternatives = results[1:]
    material = [row["configuration"] for row in alternatives if row["decision_changes"] >= MATERIAL_DECISION_CHANGES or any(abs(row[f"{metric}_difference"]) >= MATERIAL_METRIC_CHANGE for metric in METRIC_DEFINITIONS)]
    comparator_rates = _rates(truth, [recorded.loc[scenario.scenario_id].context_abac_decision for scenario in scenarios])
    conclusion_changed = any(
        row["UER"] < comparator_rates["UER"]["rate"]
        or comparator_rates["LDCR"]["rate"] - row["LDCR"] < QUALITATIVE_LDCR_SHORTFALL
        for row in alternatives
    )
    classification = "MAPPING-SENSITIVE" if conclusion_changed else "PARTIALLY ROBUST" if material else "ROBUST"
    after = _hashes()
    if before != after or {key: before[key] for key in freeze["required_inputs"]} != freeze["required_inputs"]:
        raise ConfigurationError("protected input or primary-output hash changed")
    summary = {
        "analysis_role": "post-hoc exploratory descriptive robustness",
        "configurations": [name for name, _, _ in CONFIGURATIONS],
        "mappings": mappings,
        "formula_weights": weights,
        "thresholds": {"T1": 0.20, "T2": 0.50},
        "metric_definitions": {metric: {"truth": pair[0].value, "predicted": pair[1].value} for metric, pair in METRIC_DEFINITIONS.items()},
        "materiality_rule": {"absolute_metric_rate_change": MATERIAL_METRIC_CHANGE, "decision_changes_of_150": MATERIAL_DECISION_CHANGES, "qualitative_ldcr_shortfall": QUALITATIVE_LDCR_SHORTFALL},
        "primary_metrics": primary_rates,
        "comparator_metrics": comparator_rates,
        "results": results,
        "material_change_configurations": material,
        "qualitative_conclusion_changed": conclusion_changed,
        "classification": classification,
        "protected_sha256_before": before,
        "protected_sha256_after": after,
        "integrity_verified": before == after,
        "statement": "This sensitivity analysis does not modify or replace the prespecified primary mapping or confirmatory results.",
    }
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / "ordinal_mapping_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    with (destination / "ordinal_mapping_decision_changes.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["configuration", "scenario_id", "ground_truth", "primary_decision", "alternative_decision", "transition", "primary_score", "alternative_score"])
        writer.writeheader()
        writer.writerows(changes)
    (destination / "ordinal_mapping_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if _hashes() != before:
        raise ConfigurationError("protected hash changed while writing outputs")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(OUTPUT))
    args = parser.parse_args()
    result = run(args.output_dir)
    print(json.dumps({"classification": result["classification"], "material_change_configurations": result["material_change_configurations"]}, indent=2))
