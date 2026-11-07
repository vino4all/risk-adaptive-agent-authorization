"""Validation tests for the strongly typed domain models."""

from __future__ import annotations

import pytest

from src.models import (
    CONTEXT_RISK_DEFINITIONS,
    AuthorizationResult,
    ContextRisk,
    Decision,
    Destination,
    Method,
    PolicyOutcome,
    RiskAssessment,
    RiskFactors,
    Role,
    Scenario,
    Sensitivity,
    Tool,
)


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("enum_type", "expected"),
    [
        (Decision, ["ALLOW", "ESCALATE", "DENY"]),
        (Role, ["ANALYST", "MANAGER", "ADMINISTRATOR"]),
        (
            Tool,
            [
                "READ_RECORD",
                "UPDATE_RECORD",
                "EXPORT_DATA",
                "SEND_MESSAGE",
                "DELETE_RECORD",
            ],
        ),
        (Sensitivity, ["INTERNAL", "CONFIDENTIAL", "RESTRICTED"]),
        (Destination, ["INTERNAL", "CONTROLLED_EXTERNAL", "EXTERNAL"]),
        (ContextRisk, ["NORMAL", "UNUSUAL", "HIGH_VOLUME", "ANOMALOUS"]),
    ],
)
def test_enum_members_match_specification(enum_type: type, expected: list[str]) -> None:
    assert [member.value for member in enum_type] == expected


def test_decision_is_three_way_and_method_covers_both_systems() -> None:
    assert len(list(Decision)) == 3
    assert {member.value for member in Method} == {"risk_adaptive", "abac_binary"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ALLOW", Decision.ALLOW),
        ("allow", Decision.ALLOW),
        ("Escalate", Decision.ESCALATE),
        ("deny", Decision.DENY),
        ("controlled-external", Destination.CONTROLLED_EXTERNAL),
        ("controlled external", Destination.CONTROLLED_EXTERNAL),
        ("High Volume", ContextRisk.HIGH_VOLUME),
        ("high_volume", ContextRisk.HIGH_VOLUME),
    ],
)
def test_enum_parsing_tolerates_case_and_separators(raw: str, expected: object) -> None:
    assert type(expected)(raw) is expected


def test_enum_parse_error_lists_allowed_values() -> None:
    with pytest.raises(ValueError) as excinfo:
        Decision.parse("MAYBE")
    message = str(excinfo.value)
    assert "MAYBE" in message
    for member in Decision:
        assert member.value in message


def test_context_risk_definitions_cover_all_levels_with_spec_wording() -> None:
    assert set(CONTEXT_RISK_DEFINITIONS) == set(ContextRisk)
    assert "no unusual execution context" in CONTEXT_RISK_DEFINITIONS[ContextRisk.NORMAL]
    assert "atypical contextual condition" in CONTEXT_RISK_DEFINITIONS[ContextRisk.UNUSUAL]
    assert "bulk" in CONTEXT_RISK_DEFINITIONS[ContextRisk.HIGH_VOLUME].lower()
    assert (
        "strong contextual deviation"
        in CONTEXT_RISK_DEFINITIONS[ContextRisk.ANOMALOUS]
    )


def test_context_risk_is_supplied_not_inferred() -> None:
    """No inference path for ContextRisk may exist in the models module."""
    from pathlib import Path

    import src.models as models

    source = Path(models.__file__).read_text(encoding="utf-8")
    assert "def infer" not in source
    assert "openai" not in source.lower()
    assert "anthropic" not in source.lower()


# --------------------------------------------------------------------------- #
# Scenario
# --------------------------------------------------------------------------- #


def make_scenario(**overrides: object) -> Scenario:
    """Build a scenario from in-memory test values (no experimental data)."""
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


def test_scenario_accepts_enum_and_string_values() -> None:
    scenario = Scenario(
        scenario_id="T002",
        role="Analyst",
        tool="update_record",
        sensitivity="Confidential",
        destination="controlled-external",
        context_risk="unusual",
        ground_truth="escalate",
    )
    assert scenario.role is Role.ANALYST
    assert scenario.tool is Tool.UPDATE_RECORD
    assert scenario.sensitivity is Sensitivity.CONFIDENTIAL
    assert scenario.destination is Destination.CONTROLLED_EXTERNAL
    assert scenario.context_risk is ContextRisk.UNUSUAL
    assert scenario.ground_truth is Decision.ESCALATE
    assert scenario.is_labelled


def test_scenario_rejects_empty_identifier_and_unknown_values() -> None:
    with pytest.raises(ValueError, match="scenario_id"):
        make_scenario(scenario_id="  ")
    with pytest.raises(ValueError, match="tool"):
        make_scenario(tool="DROP_TABLE")
    with pytest.raises(ValueError, match="context_risk"):
        make_scenario(context_risk="SUSPICIOUS")


def test_scenario_supports_unlabelled_state() -> None:
    scenario = make_scenario(ground_truth=None)
    assert scenario.ground_truth is None
    assert not scenario.is_labelled


def test_scenario_from_dict_collects_unknown_keys_into_metadata() -> None:
    entry = {
        "scenario_id": "T003",
        "role": "ANALYST",
        "tool": "EXPORT_DATA",
        "sensitivity": "RESTRICTED",
        "destination": "EXTERNAL",
        "context_risk": "HIGH_VOLUME",
        "ground_truth": "DENY",
        "operation": "EXPORT",
        "context": "bulk_export",
    }
    scenario = Scenario.from_dict(entry)
    assert scenario.metadata == {"operation": "EXPORT", "context": "bulk_export"}
    assert scenario.to_dict()["metadata"]["context"] == "bulk_export"


def test_scenario_from_dict_strict_mode_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown key"):
        Scenario.from_dict(
            {
                "scenario_id": "T004",
                "role": "ANALYST",
                "tool": "READ_RECORD",
                "sensitivity": "INTERNAL",
                "destination": "INTERNAL",
                "context_risk": "NORMAL",
                "ground_truth": "ALLOW",
                "surprise": 1,
            },
            strict_unknown_keys=True,
        )


def test_scenario_from_dict_reports_missing_required_keys() -> None:
    with pytest.raises(ValueError) as excinfo:
        Scenario.from_dict({"scenario_id": "T005", "role": "ANALYST"})
    message = str(excinfo.value)
    assert "tool" in message and "context_risk" in message


def test_scenario_from_dict_allows_absent_label_only_when_requested() -> None:
    entry = {
        "scenario_id": "T006",
        "role": "MANAGER",
        "tool": "SEND_MESSAGE",
        "sensitivity": "CONFIDENTIAL",
        "destination": "INTERNAL",
        "context_risk": "NORMAL",
    }
    with pytest.raises(ValueError, match="ground_truth"):
        Scenario.from_dict(entry)
    scenario = Scenario.from_dict(entry, require_ground_truth=False)
    assert scenario.ground_truth is None


def test_scenario_round_trip() -> None:
    scenario = make_scenario(resource="customer_records", description="read")
    restored = Scenario.from_dict(scenario.to_dict())
    assert restored == scenario


# --------------------------------------------------------------------------- #
# Result models
# --------------------------------------------------------------------------- #


def test_authorization_result_validates_latency_and_score() -> None:
    with pytest.raises(ValueError, match="latency_ms"):
        AuthorizationResult(
            scenario_id="T001",
            decision=Decision.ALLOW,
            latency_ms=-1.0,
            explanation="",
        )
    with pytest.raises(ValueError, match="score"):
        AuthorizationResult(
            scenario_id="T001",
            decision=Decision.ALLOW,
            latency_ms=0.5,
            explanation="",
            score=1.4,
        )


def test_authorization_result_row_contains_all_specified_fields() -> None:
    result = AuthorizationResult(
        scenario_id="T001",
        decision=Decision.ESCALATE,
        latency_ms=0.125,
        explanation="within escalation band",
        score=0.55,
        method=Method.RISK_ADAPTIVE,
    )
    assert result.to_row() == {
        "scenario_id": "T001",
        "method": "risk_adaptive",
        "decision": "ESCALATE",
        "ground_truth": None,
        "correct_for_binary_safe_execution": None,
        "true_escalate_resolved_as_allow": False,
        "true_escalate_resolved_as_deny": False,
        "score": 0.55,
        "latency_ms": 0.125,
        "explanation": "within escalation band",
    }


def test_authorization_result_score_is_optional_for_the_binary_baseline() -> None:
    result = AuthorizationResult(
        scenario_id="T001",
        decision=Decision.DENY,
        latency_ms=0.01,
        explanation="baseline deny",
        method=Method.ABAC_BINARY,
        ground_truth=Decision.DENY,
        correct_for_binary_safe_execution=True,
    )
    assert result.score is None
    row = result.to_row()
    assert row["score"] is None
    assert row["ground_truth"] == "DENY"
    assert row["correct_for_binary_safe_execution"] is True
    assert row["true_escalate_resolved_as_allow"] is False
    assert row["true_escalate_resolved_as_deny"] is False


def test_binary_result_rejects_a_score_or_escalate_decision() -> None:
    common = {
        "scenario_id": "T001",
        "latency_ms": 0.01,
        "explanation": "invalid binary result",
        "method": Method.ABAC_BINARY,
        "ground_truth": Decision.ESCALATE,
        "correct_for_binary_safe_execution": False,
    }
    with pytest.raises(ValueError, match="must not contain a risk score"):
        AuthorizationResult(
            decision=Decision.ALLOW,
            score=0.5,
            true_escalate_resolved_as_allow=True,
            **common,
        )
    with pytest.raises(ValueError, match="must be ALLOW or DENY"):
        AuthorizationResult(decision=Decision.ESCALATE, **common)


def test_policy_outcome_validates_score_and_coerces_decision() -> None:
    outcome = PolicyOutcome(decision="allow", score=0.1, explanation="low risk")
    assert outcome.decision is Decision.ALLOW
    with pytest.raises(ValueError, match="score"):
        PolicyOutcome(decision=Decision.ALLOW, score=-0.2)


def test_risk_components_are_restricted_to_unit_interval() -> None:
    factors = RiskFactors(
        sensitivity=0.0,
        action_severity=0.5,
        exposure_scope=1.0,
        contextual_risk=0.25,
    )
    assert factors.as_dict()["exposure_scope"] == 1.0
    with pytest.raises(ValueError, match="sensitivity"):
        RiskFactors(
            sensitivity=1.5,
            action_severity=0.0,
            exposure_scope=0.0,
            contextual_risk=0.0,
        )


def test_risk_assessment_rejects_out_of_range_score() -> None:
    factors = RiskFactors(0.1, 0.2, 0.3, 0.4)
    with pytest.raises(ValueError, match="score"):
        RiskAssessment(
            scenario_id="T001",
            score=2.0,
            factors=factors,
            weights={"sensitivity": 1.0},
        )
