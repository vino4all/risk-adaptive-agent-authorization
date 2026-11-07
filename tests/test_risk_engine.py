"""Validation tests for the risk-adaptive three-way authorization mechanism.

The numeric values in this module are **unit-test fixtures** chosen to make the
arithmetic checkable by hand.  They are not, and must not be mistaken for, the
experimental risk weights, factor mappings or thresholds -- those are authored in
``data/policy_matrix.yaml`` (draft sections III.D and III.E) and are still unset.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.evaluator import Evaluator
from src.experiment import (
    EXIT_CONFIGURATION_NOT_READY,
    EXIT_OK,
    build_readiness_report,
    main,
    run_experiment,
    write_results,
)
from src.models import (
    ConfigurationError,
    ContextRisk,
    Decision,
    Destination,
    Method,
    Role,
    Scenario,
    Sensitivity,
    Tool,
)
from src.policy import (
    COMPONENT_KEYS,
    RiskModelConfig,
    ThresholdConfig,
    load_policy_matrix,
    load_scenarios,
)
from src.risk_engine import DECISION_RULE, RiskEngine

# --- unit-test fixtures (NOT the experimental configuration) --------------- #

FIXTURE_WEIGHTS: dict[str, float] = {component: 0.25 for component in COMPONENT_KEYS}
FIXTURE_MAPPINGS: dict[str, dict[str, float]] = {
    "sensitivity": {
        Sensitivity.INTERNAL.value: 0.0,
        Sensitivity.CONFIDENTIAL.value: 0.5,
        Sensitivity.RESTRICTED.value: 1.0,
    },
    "action_severity": {
        Tool.READ_RECORD.value: 0.0,
        Tool.UPDATE_RECORD.value: 0.25,
        Tool.SEND_MESSAGE.value: 0.5,
        Tool.EXPORT_DATA.value: 0.75,
        Tool.DELETE_RECORD.value: 1.0,
    },
    "exposure_scope": {
        Destination.INTERNAL.value: 0.0,
        Destination.CONTROLLED_EXTERNAL.value: 0.5,
        Destination.EXTERNAL.value: 1.0,
    },
    "contextual_risk": {
        ContextRisk.NORMAL.value: 0.0,
        ContextRisk.UNUSUAL.value: 0.25,
        ContextRisk.HIGH_VOLUME.value: 0.5,
        ContextRisk.ANOMALOUS.value: 1.0,
    },
}
FIXTURE_T1 = 0.35
FIXTURE_T2 = 0.70
FIXTURE_COMPONENT_SOURCES = {
    "sensitivity": "sensitivity",
    "action_severity": "tool",
    "exposure_scope": "destination",
    "contextual_risk": "context_risk",
}


def fixture_risk_model() -> RiskModelConfig:
    return RiskModelConfig(
        formula="R = w_s*S + w_a*A + w_e*E + w_c*C",
        weights=dict(FIXTURE_WEIGHTS),
        factor_mappings=FIXTURE_MAPPINGS,
        component_dimensions=FIXTURE_COMPONENT_SOURCES,
        weight_locked=True,
    )


def fixture_thresholds() -> ThresholdConfig:
    return ThresholdConfig(t1=FIXTURE_T1, t2=FIXTURE_T2, preregistered=True)


def fixture_engine() -> RiskEngine:
    return RiskEngine(risk_model=fixture_risk_model(), thresholds=fixture_thresholds())


def make_scenario(**overrides: object) -> Scenario:
    payload: dict[str, object] = {
        "scenario_id": "T001",
        "role": Role.ANALYST,
        "tool": Tool.READ_RECORD,
        "sensitivity": Sensitivity.INTERNAL,
        "destination": Destination.INTERNAL,
        "context_risk": ContextRisk.NORMAL,
        "ground_truth": Decision.ALLOW,
    }
    payload.update(overrides)
    return Scenario(**payload)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Risk scoring
# --------------------------------------------------------------------------- #


def test_factor_lookup_uses_the_authored_mappings() -> None:
    engine = fixture_engine()
    factors = engine.factors(
        make_scenario(
            sensitivity=Sensitivity.RESTRICTED,
            tool=Tool.EXPORT_DATA,
            destination=Destination.EXTERNAL,
            context_risk=ContextRisk.HIGH_VOLUME,
        )
    )
    assert factors.as_dict() == {
        "sensitivity": 1.0,
        "action_severity": 0.75,
        "exposure_scope": 1.0,
        "contextual_risk": 0.5,
    }


def test_weighted_score_matches_hand_calculation() -> None:
    engine = fixture_engine()
    assessment = engine.score(
        make_scenario(
            sensitivity=Sensitivity.RESTRICTED,
            tool=Tool.EXPORT_DATA,
            destination=Destination.EXTERNAL,
            context_risk=ContextRisk.HIGH_VOLUME,
        )
    )
    # 0.25 * (1.00 + 0.75 + 1.00 + 0.50) = 0.8125
    assert assessment.score == pytest.approx(0.8125)
    assert assessment.weights == FIXTURE_WEIGHTS
    contributions = engine.contributions(
        make_scenario(
            sensitivity=Sensitivity.RESTRICTED,
            tool=Tool.EXPORT_DATA,
            destination=Destination.EXTERNAL,
            context_risk=ContextRisk.HIGH_VOLUME,
        )
    )
    assert sum(contributions.values()) == pytest.approx(assessment.score)


def test_lowest_and_highest_risk_scenarios_sit_at_the_score_bounds() -> None:
    engine = fixture_engine()
    lowest = engine.score(make_scenario())
    highest = engine.score(
        make_scenario(
            sensitivity=Sensitivity.RESTRICTED,
            tool=Tool.DELETE_RECORD,
            destination=Destination.EXTERNAL,
            context_risk=ContextRisk.ANOMALOUS,
        )
    )
    assert lowest.score == pytest.approx(0.0)
    assert highest.score == pytest.approx(1.0)


def test_context_risk_changes_the_score_without_any_inference() -> None:
    engine = fixture_engine()
    scores = {
        level: engine.score(make_scenario(context_risk=level)).score
        for level in ContextRisk
    }
    assert len(set(scores.values())) == len(ContextRisk)
    assert scores[ContextRisk.NORMAL] < scores[ContextRisk.ANOMALOUS]


def test_engine_contains_no_hard_coded_weights_or_thresholds() -> None:
    """Every numeric input must come from the authored configuration."""
    import src.risk_engine as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    numbers = {
        token
        for token in ("0.25", "0.30", "0.40", "0.50", "0.60", "0.70", "0.80")
        if token in source
    }
    assert numbers == set()


# --------------------------------------------------------------------------- #
# Decision function
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, Decision.ALLOW),
        (FIXTURE_T1 - 0.001, Decision.ALLOW),
        (FIXTURE_T1, Decision.ESCALATE),
        (0.5, Decision.ESCALATE),
        (FIXTURE_T2 - 0.001, Decision.ESCALATE),
        (FIXTURE_T2, Decision.DENY),
        (1.0, Decision.DENY),
    ],
)
def test_three_way_threshold_rule_boundaries(score: float, expected: Decision) -> None:
    """T1 is inclusive for ESCALATE and T2 is inclusive for DENY (section III.E)."""
    assert fixture_engine().decide(score) is expected


def test_scenario_exactly_on_the_escalation_threshold_is_escalated() -> None:
    engine = RiskEngine(
        risk_model=RiskModelConfig(
            formula="fixture",
            weights={
                "sensitivity": 1.0,
                "action_severity": 0.0,
                "exposure_scope": 0.0,
                "contextual_risk": 0.0,
            },
            factor_mappings={
                **FIXTURE_MAPPINGS,
                "sensitivity": {
                    Sensitivity.INTERNAL.value: 0.0,
                    Sensitivity.CONFIDENTIAL.value: FIXTURE_T1,
                    Sensitivity.RESTRICTED.value: 1.0,
                },
            },
            component_dimensions=FIXTURE_COMPONENT_SOURCES,
            weight_locked=True,
        ),
        thresholds=fixture_thresholds(),
    )
    outcome = engine.authorize(make_scenario(sensitivity=Sensitivity.CONFIDENTIAL))
    assert outcome.score == pytest.approx(FIXTURE_T1)
    assert outcome.decision is Decision.ESCALATE


def test_authorization_explains_score_factors_and_rule() -> None:
    outcome = fixture_engine().authorize(
        make_scenario(
            sensitivity=Sensitivity.CONFIDENTIAL,
            tool=Tool.SEND_MESSAGE,
            destination=Destination.CONTROLLED_EXTERNAL,
            context_risk=ContextRisk.UNUSUAL,
        )
    )
    assert outcome.score == pytest.approx(0.4375)
    assert outcome.decision is Decision.ESCALATE
    assert "R=0.4375" in outcome.explanation
    assert DECISION_RULE in outcome.explanation
    assert outcome.details["context_risk_supplied"] == ContextRisk.UNUSUAL.value
    assert outcome.details["thresholds"] == {"T1": FIXTURE_T1, "T2": FIXTURE_T2}


def test_high_risk_scenario_is_denied() -> None:
    outcome = fixture_engine().authorize(
        make_scenario(
            sensitivity=Sensitivity.RESTRICTED,
            tool=Tool.DELETE_RECORD,
            destination=Destination.EXTERNAL,
            context_risk=ContextRisk.ANOMALOUS,
        )
    )
    assert outcome.score == pytest.approx(1.0)
    assert outcome.decision is Decision.DENY


# --------------------------------------------------------------------------- #
# Unconfigured mechanism behaviour
# --------------------------------------------------------------------------- #


def test_unconfigured_mechanism_refuses_to_score() -> None:
    model = RiskModelConfig(
        formula="fixture",
        weights={component: None for component in COMPONENT_KEYS},
        factor_mappings={
            component: {member: None for member in mapping}
            for component, mapping in FIXTURE_MAPPINGS.items()
        },
        component_dimensions=FIXTURE_COMPONENT_SOURCES,
        weight_locked=False,
    )
    engine = RiskEngine(risk_model=model, thresholds=fixture_thresholds())
    assert any(item.startswith("risk_model.weights") for item in engine.preflight())
    with pytest.raises(ConfigurationError, match="risk weights are not locked"):
        engine.authorize(make_scenario())


def test_authored_weights_with_unset_mappings_still_refuse_to_run() -> None:
    model = RiskModelConfig(
        formula="R = w_s*S + w_a*A + w_e*E + w_c*C",
        weights=dict(FIXTURE_WEIGHTS),
        factor_mappings={
            component: {member: None for member in mapping}
            for component, mapping in FIXTURE_MAPPINGS.items()
        },
        component_dimensions=FIXTURE_COMPONENT_SOURCES,
        weight_locked=False,
    )
    engine = RiskEngine(risk_model=model, thresholds=fixture_thresholds())
    with pytest.raises(ConfigurationError, match="factor_mappings"):
        engine.authorize(make_scenario())
    with pytest.raises(ConfigurationError, match="risk_model.factor_mappings"):
        engine.factors(make_scenario())
    assert len(engine.preflight()) > 1


# --------------------------------------------------------------------------- #
# Evaluator: latency measurement is independent of tool execution
# --------------------------------------------------------------------------- #


class FakeClock:
    """Monotonic fake clock advanced by a fixed step on every reading."""

    def __init__(self, step_ns: int = 1_000_000) -> None:
        self.step_ns = step_ns
        self.now = 0

    def __call__(self) -> int:
        self.now += self.step_ns
        return self.now


class StubPolicy:
    """Minimal policy used to verify timing plumbing only."""

    def __init__(self, decision: Decision = Decision.ALLOW) -> None:
        self.decision = decision
        self.calls = 0

    def authorize(self, scenario: Scenario):  # noqa: ANN201 - test stub
        from src.models import PolicyOutcome

        self.calls += 1
        return PolicyOutcome(
            decision=self.decision, score=0.5, explanation="stub outcome"
        )

    def preflight(self) -> tuple[str, ...]:
        return ("stub: nothing to report",)


def test_evaluator_records_only_the_authorization_call() -> None:
    policy = StubPolicy()
    evaluator = Evaluator(
        policy=policy, method=Method.RISK_ADAPTIVE, clock=FakeClock(step_ns=1_000_000)
    )
    result = evaluator.evaluate(make_scenario())
    assert policy.calls == 1
    assert result.latency_ms == pytest.approx(1.0)
    assert result.scenario_id == "T001"
    assert result.decision is Decision.ALLOW
    assert result.method is Method.RISK_ADAPTIVE


def test_evaluation_run_packages_results_and_manifest() -> None:
    scenarios = [
        make_scenario(scenario_id="T001"),
        make_scenario(scenario_id="T002", tool=Tool.DELETE_RECORD),
    ]
    evaluator = Evaluator(
        policy=StubPolicy(Decision.ESCALATE),
        method=Method.RISK_ADAPTIVE,
        label="fixture-run",
        clock=FakeClock(),
    )
    run = evaluator.run(scenarios, scenario_source="fixture")
    assert run.label == "fixture-run"
    assert run.scenario_ids == ("T001", "T002")
    assert run.decision_counts() == {"ALLOW": 0, "ESCALATE": 2, "DENY": 0}
    assert {row["run_label"] for row in run.to_records()} == {"fixture-run"}
    manifest = run.to_manifest()
    assert manifest["scenario_count"] == 2
    assert manifest["method"] == "risk_adaptive"
    assert manifest["mean_latency_ms"] == pytest.approx(1.0)


def test_evaluator_surfaces_the_mechanism_preflight_gaps() -> None:
    evaluator = Evaluator(policy=StubPolicy(), method=Method.ABAC_BINARY)
    assert evaluator.preflight() == ("stub: nothing to report",)
    assert evaluator.label == "abac_binary"


def test_risk_engine_and_abac_are_interchangeable_through_the_evaluator() -> None:
    engine = fixture_engine()
    evaluator = Evaluator(policy=engine, method=Method.RISK_ADAPTIVE)
    run = evaluator.run([make_scenario()])
    assert run.results[0].score is not None
    assert run.results[0].decision is Decision.ALLOW
# --------------------------------------------------------------------------- #
# End-to-end pipeline on a fully authored *fixture* configuration
# --------------------------------------------------------------------------- #


def authored_fixture_matrix_document() -> dict[str, object]:
    """A complete but entirely fictitious configuration used to test wiring.

    These values exist only so the pipeline can be exercised end to end; they are
    not the experimental configuration.
    """
    return {
        "_meta": {
            "schema_version": "test-fixture",
            "status": "test-fixture",
            "locked_for_primary_experiment": False,
        },
        "dimensions": {
            "role": [member.value for member in Role],
            "tool": [member.value for member in Tool],
            "sensitivity": [member.value for member in Sensitivity],
            "destination": [member.value for member in Destination],
            "context_risk": [member.value for member in ContextRisk],
        },
        "ground_truth_matrix": {
            "rules": [
                {
                    "rule_id": "GT-READ",
                    "decision": "ALLOW",
                    "match": {"tool": ["READ_RECORD"]},
                },
                {
                    "rule_id": "GT-DELETE",
                    "decision": "DENY",
                    "match": {"tool": ["DELETE_RECORD"]},
                },
            ]
        },
        "risk_model": {
            "formula": "R = w_s*S + w_a*A + w_e*E + w_c*C",
            "weights": dict(FIXTURE_WEIGHTS),
            "weight_locked": True,
            "component_sources": FIXTURE_COMPONENT_SOURCES,
            "factor_mappings": {
                component: dict(mapping)
                for component, mapping in FIXTURE_MAPPINGS.items()
            },
        },
        "thresholds": {
            "T1_escalation": FIXTURE_T1,
            "T2_denial": FIXTURE_T2,
            "preregistered": True,
            "sensitivity_grid": {"T1": [FIXTURE_T1], "T2": [FIXTURE_T2]},
            "grid_source": "test fixture",
        },
        "abac_baseline": {
            "binary_only": True,
            "attributes": ["role", "tool", "sensitivity", "destination"],
            "default_decision": "DENY",
            "rules": [
                {
                    "rule_id": "B-READ-INTERNAL",
                    "decision": "ALLOW",
                    "match": {"tool": ["READ_RECORD"], "destination": ["INTERNAL"]},
                }
            ],
        },
        "metrics": {
            "low_risk_definition": "context_risk == NORMAL (test fixture only)",
            "low_risk_context_risks": ["NORMAL"],
        },
    }


FIXTURE_SCENARIOS: list[dict[str, object]] = [
    {
        "scenario_id": "S001",
        "role": "ANALYST",
        "tool": "READ_RECORD",
        "sensitivity": "INTERNAL",
        "destination": "INTERNAL",
        "context_risk": "NORMAL",
        "ground_truth": "ALLOW",
        "description": "routine internal read",
        "rationale": "test fixture",
    },
    {
        "scenario_id": "S002",
        "role": "ANALYST",
        "tool": "UPDATE_RECORD",
        "sensitivity": "CONFIDENTIAL",
        "destination": "INTERNAL",
        "context_risk": "UNUSUAL",
        "ground_truth": "ESCALATE",
        "description": "unusual-time update",
        "rationale": "test fixture",
    },
    {
        "scenario_id": "S003",
        "role": "ANALYST",
        "tool": "DELETE_RECORD",
        "sensitivity": "RESTRICTED",
        "destination": "EXTERNAL",
        "context_risk": "ANOMALOUS",
        "ground_truth": "DENY",
        "description": "restricted deletion",
        "rationale": "test fixture",
    },
    {
        "scenario_id": "S004",
        "role": "MANAGER",
        "tool": "SEND_MESSAGE",
        "sensitivity": "CONFIDENTIAL",
        "destination": "EXTERNAL",
        "context_risk": "HIGH_VOLUME",
        "ground_truth": "DENY",
        "description": "bulk message to an external destination",
        "rationale": "test fixture",
    },
]


def write_fixture_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """Write the fixture configuration and dataset, returning their paths."""
    matrix_path = tmp_path / "matrix.yaml"
    matrix_path.write_text(
        yaml.safe_dump(authored_fixture_matrix_document(), sort_keys=False),
        encoding="utf-8",
    )
    scenarios_path = tmp_path / "scenarios.yaml"
    scenarios_path.write_text(
        yaml.safe_dump(
            {"_meta": {"status": "test-fixture"}, "scenarios": FIXTURE_SCENARIOS},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return matrix_path, scenarios_path
