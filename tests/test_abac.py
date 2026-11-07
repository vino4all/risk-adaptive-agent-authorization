"""Validation tests for the deterministic binary ABAC baseline.

All rules used here are in-memory test fixtures written for unit testing; they
are explicitly *not* the experimental baseline configuration, which lives in
``data/policy_matrix.yaml``.
"""

from __future__ import annotations

import pytest

from src.abac import ABACEngine
from src.evaluator import Evaluator
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
from src.policy import ABACConfig, PolicyRule, load_policy_matrix


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


def fixture_config() -> ABACConfig:
    """A two-rule binary baseline fixture (not applicable to the experiment)."""
    return ABACConfig(
        rules=(
            PolicyRule(
                rule_id="B-DELETE",
                decision=Decision.DENY,
                match={"tool": [Tool.DELETE_RECORD.value]},
                priority=0,
            ),
            PolicyRule(
                rule_id="B-READ",
                decision=Decision.ALLOW,
                match={
                    "tool": [Tool.READ_RECORD.value],
                    "destination": [Destination.INTERNAL.value],
                },
                priority=1,
            ),
        ),
        default_decision=Decision.DENY,
        description="unit-test fixture",
    )


def test_binary_baseline_is_first_match_wins() -> None:
    engine = ABACEngine(config=fixture_config())
    allowed = engine.authorize(make_scenario(tool=Tool.READ_RECORD))
    denied = engine.authorize(make_scenario(tool=Tool.DELETE_RECORD))
    assert allowed.decision is Decision.ALLOW
    assert denied.decision is Decision.DENY
    assert allowed.details["matched_rule_id"] == "B-READ"
    assert denied.details["matched_rule_id"] == "B-DELETE"


def test_binary_baseline_never_reports_a_score() -> None:
    engine = ABACEngine(config=fixture_config())
    outcome = engine.authorize(make_scenario())
    assert outcome.score is None


def test_binary_baseline_applies_the_authored_default_for_unmatched_scenarios() -> None:
    engine = ABACEngine(config=fixture_config())
    outcome = engine.authorize(make_scenario(tool=Tool.SEND_MESSAGE))
    assert outcome.decision is Decision.DENY
    assert outcome.details["matched_rule_id"] is None
    assert "default_decision" in outcome.explanation


def test_binary_baseline_is_deterministic_across_repeated_evaluation() -> None:
    engine = ABACEngine(config=fixture_config())
    scenarios = [
        make_scenario(scenario_id=f"T{i:03d}", tool=tool)
        for i, tool in enumerate(Tool, start=1)
    ]
    first = [engine.authorize(scenario).decision for scenario in scenarios]
    second = [engine.authorize(scenario).decision for scenario in scenarios]
    assert first == second
    assert all(decision in {Decision.ALLOW, Decision.DENY} for decision in first)


def test_binary_baseline_ignores_context_risk() -> None:
    """The baseline evaluates role, tool, sensitivity and destination only."""
    engine = ABACEngine(config=fixture_config())
    outcomes = {
        engine.authorize(make_scenario(context_risk=level)).decision
        for level in ContextRisk
    }
    assert outcomes == {Decision.ALLOW}
    assert set(fixture_config().attributes) == {
        "role",
        "tool",
        "sensitivity",
        "destination",
    }


def test_unconfigured_baseline_refuses_to_produce_results() -> None:
    engine = ABACEngine(config=ABACConfig())
    assert engine.preflight() != ()
    with pytest.raises(ConfigurationError, match="ABAC baseline is not configured"):
        engine.authorize(make_scenario())


def test_missing_default_decision_is_reported_explicitly() -> None:
    config = ABACConfig(
        rules=(
            PolicyRule(
                rule_id="B-READ",
                decision=Decision.ALLOW,
                match={"tool": [Tool.READ_RECORD.value]},
            ),
        ),
        default_decision=None,
    )
    engine = ABACEngine(config=config)
    assert any("default_decision" in item for item in engine.preflight())
    with pytest.raises(ConfigurationError, match="default_decision"):
        engine.authorize(make_scenario(tool=Tool.SEND_MESSAGE))


def test_exploration_mode_labels_unconfigured_outcomes_as_non_experimental() -> None:
    """Smoke-test path only: results from it must never be reported."""
    engine = ABACEngine(config=ABACConfig(), allow_unconfigured=True)
    outcome = engine.authorize(make_scenario())
    assert outcome.decision is Decision.DENY
    assert outcome.details["configured"] is False
    assert "UNCONFIGURED EXPLORATION MODE" in outcome.explanation


def test_engine_can_be_built_from_a_policy_matrix() -> None:
    matrix = load_policy_matrix()
    engine = ABACEngine.from_policy_matrix(matrix)
    assert engine.config is matrix.abac
    assert engine.preflight() == matrix.abac.missing_items()


def test_shipped_baseline_is_authored_and_emits_only_binary_decisions() -> None:
    engine = ABACEngine.from_policy_matrix(load_policy_matrix())
    assert engine.preflight() == ()

    decisions = {
        engine.authorize(
            make_scenario(
                role=role,
                tool=tool,
                sensitivity=sensitivity,
                destination=destination,
                context_risk=context_risk,
            )
        ).decision
        for role in Role
        for tool in Tool
        for sensitivity in Sensitivity
        for destination in Destination
        for context_risk in ContextRisk
    }
    assert decisions <= {Decision.ALLOW, Decision.DENY}
    assert Decision.ESCALATE not in decisions
    assert set(engine.config.attributes) == {
        "role",
        "tool",
        "sensitivity",
        "destination",
    }
    assert all("context_risk" not in rule.match for rule in engine.config.rules)


@pytest.mark.parametrize(
    ("ground_truth", "decision", "expected_correct"),
    [
        (Decision.ALLOW, Decision.ALLOW, True),
        (Decision.ALLOW, Decision.DENY, False),
        (Decision.DENY, Decision.ALLOW, False),
        (Decision.DENY, Decision.DENY, True),
    ],
)
def test_binary_safe_correctness_for_non_escalate_ground_truth(
    ground_truth: Decision, decision: Decision, expected_correct: bool
) -> None:
    config = ABACConfig(
        rules=(
            PolicyRule(
                rule_id="B-FIXTURE",
                decision=decision,
                match={"tool": [Tool.READ_RECORD.value]},
            ),
        ),
        default_decision=Decision.DENY,
    )
    result = Evaluator(
        policy=ABACEngine(config=config), method=Method.ABAC_BINARY
    ).evaluate(make_scenario(ground_truth=ground_truth))

    assert result.correct_for_binary_safe_execution is expected_correct
    assert result.true_escalate_resolved_as_allow is False
    assert result.true_escalate_resolved_as_deny is False


def test_true_escalate_is_retained_and_resolved_as_deny_with_accounting() -> None:
    scenario = make_scenario(
        role=Role.ANALYST,
        tool=Tool.READ_RECORD,
        sensitivity=Sensitivity.RESTRICTED,
        destination=Destination.INTERNAL,
        context_risk=ContextRisk.NORMAL,
        ground_truth=Decision.ESCALATE,
    )
    result = Evaluator(
        policy=ABACEngine.from_policy_matrix(load_policy_matrix()),
        method=Method.ABAC_BINARY,
    ).evaluate(scenario)

    assert result.ground_truth is Decision.ESCALATE
    assert result.decision is Decision.DENY
    assert result.correct_for_binary_safe_execution is True
    assert result.true_escalate_resolved_as_allow is False
    assert result.true_escalate_resolved_as_deny is True
    assert "forced to DENY" in result.explanation


def test_true_escalate_resolved_as_allow_is_accounted_for_explicitly() -> None:
    config = ABACConfig(
        rules=(
            PolicyRule(
                rule_id="B-ALLOW-READ",
                decision=Decision.ALLOW,
                match={"tool": [Tool.READ_RECORD.value]},
            ),
        ),
        default_decision=Decision.DENY,
    )
    scenario = make_scenario(ground_truth=Decision.ESCALATE)
    result = Evaluator(
        policy=ABACEngine(config=config), method=Method.ABAC_BINARY
    ).evaluate(scenario)

    assert result.ground_truth is Decision.ESCALATE
    assert result.decision is Decision.ALLOW
    assert result.correct_for_binary_safe_execution is False
    assert result.true_escalate_resolved_as_allow is True
    assert result.true_escalate_resolved_as_deny is False


def test_binary_result_accounting_requires_ground_truth() -> None:
    scenario = make_scenario(ground_truth=None)
    evaluator = Evaluator(
        policy=ABACEngine(config=fixture_config()), method=Method.ABAC_BINARY
    )
    with pytest.raises(ConfigurationError, match="requires an independent ground_truth"):
        evaluator.evaluate(scenario)


def test_baseline_cannot_disable_binary_only_mode() -> None:
    with pytest.raises(ConfigurationError, match="binary_only must be true"):
        ABACConfig(binary_only=False)
