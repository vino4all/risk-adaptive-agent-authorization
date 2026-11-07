"""Reproducible pilot-only calibration for the risk-adaptive mechanism.

The grids and loss function are deliberately small and fixed in source before
the final dataset exists.  Calibration reads only ``pilot_scenarios.yaml`` and
uses ground-truth labels supplied by the independent qualitative policy.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.models import ConfigurationError, Decision, Scenario
from src.policy import (
    COMPONENT_KEYS,
    DEFAULT_PILOT_SCENARIOS_PATH,
    PolicyMatrix,
    load_policy_matrix,
    load_scenarios,
    load_yaml_mapping,
    validate_ground_truth_against_matrix,
)

DEFAULT_RISK_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "risk_config.yaml"

# Ordinal mappings are fixed before candidate evaluation. They express only
# relative severity and are not fitted to scenario labels.
COMPONENT_MAPPINGS: Mapping[str, Mapping[str, float]] = {
    "sensitivity": {"INTERNAL": 0.0, "CONFIDENTIAL": 0.5, "RESTRICTED": 1.0},
    "action_severity": {
        "READ_RECORD": 0.0,
        "UPDATE_RECORD": 0.5,
        "SEND_MESSAGE": 0.5,
        "EXPORT_DATA": 0.75,
        "DELETE_RECORD": 1.0,
    },
    "exposure_scope": {"INTERNAL": 0.0, "CONTROLLED_EXTERNAL": 0.5, "EXTERNAL": 1.0},
    "contextual_risk": {"NORMAL": 0.0, "UNUSUAL": 0.33, "HIGH_VOLUME": 0.67, "ANOMALOUS": 1.0},
}

COMPONENT_SOURCES: Mapping[str, str] = {
    "sensitivity": "sensitivity",
    "action_severity": "tool",
    "exposure_scope": "destination",
    "contextual_risk": "context_risk",
}

# Ordered from simplest/stablest to more concentrated alternatives. This order
# is the declared tie/near-tie preference and is not changed after seeing data.
WEIGHT_CANDIDATES: tuple[tuple[str, Mapping[str, float]], ...] = (
    ("equal", {"sensitivity": 0.25, "action_severity": 0.25, "exposure_scope": 0.25, "contextual_risk": 0.25}),
    ("data_exposure", {"sensitivity": 0.30, "action_severity": 0.20, "exposure_scope": 0.30, "contextual_risk": 0.20}),
    ("context_aware", {"sensitivity": 0.25, "action_severity": 0.20, "exposure_scope": 0.25, "contextual_risk": 0.30}),
    ("data_action", {"sensitivity": 0.30, "action_severity": 0.30, "exposure_scope": 0.20, "contextual_risk": 0.20}),
    ("exposure_context", {"sensitivity": 0.20, "action_severity": 0.20, "exposure_scope": 0.30, "contextual_risk": 0.30}),
)

T1_CANDIDATES: tuple[float, ...] = (0.20, 0.30, 0.40)
T2_CANDIDATES: tuple[float, ...] = (0.50, 0.60, 0.70)
NEAR_TIE_LOSS_TOLERANCE = 2

# Larger penalties encode the preregistered priority ordering. In particular,
# one unsafe automatic ALLOW cannot be offset by convenience improvements over
# this 24-case pilot.
LOSS_PENALTIES: Mapping[str, int] = {
    "unsafe_automatic_allow": 100,
    "prohibited_not_denied": 20,
    "missed_correct_escalation": 8,
    "unnecessary_escalation": 4,
    "blocked_legitimate_completion": 10,
}


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """Auditable pilot outcome for one weight/threshold candidate."""

    weight_name: str
    weights: Mapping[str, float]
    t1: float
    t2: float
    loss: int
    unsafe_automatic_allow: int
    prohibited_not_denied: int
    correct_escalation: int
    missed_correct_escalation: int
    unnecessary_escalation: int
    legitimate_direct_completion: int
    blocked_legitimate_completion: int
    exact_matches: int
    minimum_threshold_margin: float

    def summary(self) -> dict[str, Any]:
        return {
            "weight_candidate": self.weight_name,
            "weights": dict(self.weights),
            "T1": self.t1,
            "T2": self.t2,
            "loss": self.loss,
            "unsafe_automatic_allow": self.unsafe_automatic_allow,
            "prohibited_not_denied": self.prohibited_not_denied,
            "correct_escalation": self.correct_escalation,
            "missed_correct_escalation": self.missed_correct_escalation,
            "unnecessary_escalation": self.unnecessary_escalation,
            "legitimate_direct_completion": self.legitimate_direct_completion,
            "blocked_legitimate_completion": self.blocked_legitimate_completion,
            "exact_matches": self.exact_matches,
            "minimum_threshold_margin": round(self.minimum_threshold_margin, 6),
        }


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    selected: CandidateEvaluation
    candidates: tuple[CandidateEvaluation, ...]
    similar: tuple[CandidateEvaluation, ...]
    pilot_count: int


def _score(scenario: Scenario, weights: Mapping[str, float]) -> float:
    values = {
        component: COMPONENT_MAPPINGS[component][
            str(getattr(scenario, COMPONENT_SOURCES[component]))
        ]
        for component in COMPONENT_KEYS
    }
    return sum(weights[component] * values[component] for component in COMPONENT_KEYS)


def _decision(score: float, t1: float, t2: float) -> Decision:
    if score < t1:
        return Decision.ALLOW
    if score < t2:
        return Decision.ESCALATE
    return Decision.DENY


def evaluate_candidate(
    scenarios: Sequence[Scenario],
    *,
    weight_name: str,
    weights: Mapping[str, float],
    t1: float,
    t2: float,
) -> CandidateEvaluation:
    """Evaluate one predetermined candidate on pilot labels only."""
    unsafe = prohibited_not_denied = correct_escalation = 0
    missed_escalation = unnecessary_escalation = direct_completion = 0
    blocked_completion = exact_matches = 0
    margins: list[float] = []
    for scenario in scenarios:
        if scenario.ground_truth is None:
            raise ConfigurationError(
                f"pilot scenario {scenario.scenario_id} has no ground_truth"
            )
        score = _score(scenario, weights)
        predicted = _decision(score, t1, t2)
        margins.append(min(abs(score - t1), abs(score - t2)))
        exact_matches += predicted is scenario.ground_truth
        unsafe += predicted is Decision.ALLOW and scenario.ground_truth is not Decision.ALLOW
        prohibited_not_denied += scenario.ground_truth is Decision.DENY and predicted is not Decision.DENY
        correct_escalation += scenario.ground_truth is Decision.ESCALATE and predicted is Decision.ESCALATE
        missed_escalation += scenario.ground_truth is Decision.ESCALATE and predicted is not Decision.ESCALATE
        unnecessary_escalation += scenario.ground_truth is Decision.ALLOW and predicted is Decision.ESCALATE
        direct_completion += scenario.ground_truth is Decision.ALLOW and predicted is Decision.ALLOW
        blocked_completion += scenario.ground_truth is Decision.ALLOW and predicted is Decision.DENY

    loss = (
        LOSS_PENALTIES["unsafe_automatic_allow"] * unsafe
        + LOSS_PENALTIES["prohibited_not_denied"] * prohibited_not_denied
        + LOSS_PENALTIES["missed_correct_escalation"] * missed_escalation
        + LOSS_PENALTIES["unnecessary_escalation"] * unnecessary_escalation
        + LOSS_PENALTIES["blocked_legitimate_completion"] * blocked_completion
    )
    return CandidateEvaluation(
        weight_name=weight_name,
        weights=dict(weights),
        t1=t1,
        t2=t2,
        loss=loss,
        unsafe_automatic_allow=unsafe,
        prohibited_not_denied=prohibited_not_denied,
        correct_escalation=correct_escalation,
        missed_correct_escalation=missed_escalation,
        unnecessary_escalation=unnecessary_escalation,
        legitimate_direct_completion=direct_completion,
        blocked_legitimate_completion=blocked_completion,
        exact_matches=exact_matches,
        minimum_threshold_margin=min(margins) if margins else 0.0,
    )


def calibrate(
    scenarios: Sequence[Scenario], policy_matrix: PolicyMatrix
) -> CalibrationResult:
    """Search the fixed coarse grid and apply the declared stable tie rule."""
    mismatches = validate_ground_truth_against_matrix(scenarios, policy_matrix)
    if mismatches:
        detail = "; ".join(item.describe() for item in mismatches[:5])
        raise ConfigurationError(
            "pilot labels do not match the independent policy matrix: " + detail
        )
    evaluations = tuple(
        evaluate_candidate(
            scenarios,
            weight_name=name,
            weights=weights,
            t1=t1,
            t2=t2,
        )
        for name, weights in WEIGHT_CANDIDATES
        for t1 in T1_CANDIDATES
        for t2 in T2_CANDIDATES
        if t1 < t2
    )
    minimum_unsafe = min(item.unsafe_automatic_allow for item in evaluations)
    security_floor = tuple(
        item for item in evaluations if item.unsafe_automatic_allow == minimum_unsafe
    )
    minimum_loss = min(item.loss for item in security_floor)
    similar = tuple(
        item
        for item in security_floor
        if item.loss <= minimum_loss + NEAR_TIE_LOSS_TOLERANCE
    )
    stability_rank = {name: index for index, (name, _) in enumerate(WEIGHT_CANDIDATES)}
    selected = min(
        similar,
        key=lambda item: (
            stability_rank[item.weight_name],
            item.loss,
            -item.minimum_threshold_margin,
            item.t1,
            item.t2,
        ),
    )
    return CalibrationResult(
        selected=selected,
        candidates=evaluations,
        similar=tuple(sorted(similar, key=lambda item: (item.loss, stability_rank[item.weight_name], item.t1, item.t2))),
        pilot_count=len(scenarios),
    )


def verify_persisted_config(
    result: CalibrationResult, path: str | Path = DEFAULT_RISK_CONFIG_PATH
) -> None:
    """Fail if the persisted selection differs from reproducible calibration."""
    document = load_yaml_mapping(path)
    if document.get("primary_evaluation_started") is True:
        # Verification remains safe; recalibration/rewriting is intentionally
        # not implemented once this flag is set.
        pass
    selected = document.get("selected_configuration")
    if not isinstance(selected, Mapping):
        raise ConfigurationError(f"{path}: selected_configuration must be a mapping")
    expected = result.selected
    checks = {
        "weights": dict(expected.weights),
        "T1": expected.t1,
        "T2": expected.t2,
    }
    for key, value in checks.items():
        if selected.get(key) != value:
            raise ConfigurationError(
                f"{path}: persisted {key} differs from pilot calibration; "
                "configuration is immutable after primary evaluation starts"
            )


def verify_calibrated_configuration(
    policy_matrix: PolicyMatrix,
    *,
    pilot_path: str | Path = DEFAULT_PILOT_SCENARIOS_PATH,
    risk_config_path: str | Path = DEFAULT_RISK_CONFIG_PATH,
) -> CalibrationResult:
    """Verify pilot labels, selection record, and operational configuration.

    Primary evaluation calls this guard before producing results. Any drift in
    weights, mappings, or thresholds fails closed rather than silently changing
    the preregistered mechanism.
    """
    result = calibrate(load_scenarios(pilot_path), policy_matrix)
    verify_persisted_config(result, risk_config_path)
    document = load_yaml_mapping(risk_config_path)
    if document.get("immutable_after_primary_evaluation_starts") is not True:
        raise ConfigurationError(
            f"{risk_config_path}: immutable_after_primary_evaluation_starts must be true"
        )
    selected = result.selected
    if policy_matrix.risk_model.locked_weights() != dict(selected.weights):
        raise ConfigurationError(
            "data/policy_matrix.yaml risk weights drift from pilot calibration"
        )
    if policy_matrix.thresholds.locked_thresholds() != (selected.t1, selected.t2):
        raise ConfigurationError(
            "data/policy_matrix.yaml thresholds drift from pilot calibration"
        )
    for component in COMPONENT_KEYS:
        if policy_matrix.risk_model.locked_mapping(component) != dict(
            COMPONENT_MAPPINGS[component]
        ):
            raise ConfigurationError(
                "data/policy_matrix.yaml factor mapping drift for " + component
            )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify reproducible pilot calibration")
    parser.add_argument("--pilot", default=str(DEFAULT_PILOT_SCENARIOS_PATH))
    parser.add_argument("--risk-config", default=str(DEFAULT_RISK_CONFIG_PATH))
    args = parser.parse_args(argv)
    result = verify_calibrated_configuration(
        load_policy_matrix(),
        pilot_path=args.pilot,
        risk_config_path=args.risk_config,
    )
    print(json.dumps({
        "pilot_count": result.pilot_count,
        "candidate_count": len(result.candidates),
        "selected": result.selected.summary(),
        "similar_configuration_count": len(result.similar),
        "similar": [item.summary() for item in result.similar],
    }, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
