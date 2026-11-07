"""Validation tests for policy/dataset loading and configuration completeness."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml

from src.models import (
    ConfigurationError,
    ContextRisk,
    Decision,
    Destination,
    Role,
    Scenario,
    Sensitivity,
    Tool,
)
from src.policy import (
    COMPONENT_KEYS,
    DIMENSION_ENUMS,
    PolicyMatrix,
    PolicyRule,
    load_policy_matrix,
    load_scenarios,
    load_yaml_mapping,
    validate_ground_truth_against_matrix,
)


def shipped_matrix() -> PolicyMatrix:
    """Load the repository's ``data/policy_matrix.yaml``."""
    return load_policy_matrix()


# --------------------------------------------------------------------------- #
# Shipped configuration: structural validity and pilot-calibrated runtime inputs
# --------------------------------------------------------------------------- #


def test_shipped_policy_matrix_is_structurally_valid() -> None:
    matrix = shipped_matrix()
    assert matrix.source_path.name == "policy_matrix.yaml"
    assert matrix.schema_version
    assert matrix.status == "pilot-calibrated"
    assert not matrix.locked_for_primary_experiment


def test_shipped_dimensions_match_the_code_level_enums() -> None:
    matrix = shipped_matrix()
    assert set(matrix.dimensions) == set(DIMENSION_ENUMS)
    assert matrix.dimensions["role"] == tuple(member.value for member in Role)
    assert matrix.dimensions["tool"] == tuple(member.value for member in Tool)
    assert matrix.dimensions["sensitivity"] == tuple(
        member.value for member in Sensitivity
    )
    assert matrix.dimensions["destination"] == tuple(
        member.value for member in Destination
    )
    assert matrix.dimensions["context_risk"] == tuple(
        member.value for member in ContextRisk
    )


def test_shipped_risk_model_enumerates_normalized_dimension_values() -> None:
    matrix = shipped_matrix()
    for component in COMPONENT_KEYS:
        dimension = matrix.risk_model.component_dimensions[component]
        expected = set(matrix.dimensions[dimension])
        assert set(matrix.risk_model.factor_mappings[component]) == expected
        assert all(
            value is not None and 0.0 <= value <= 1.0
            for value in matrix.risk_model.factor_mappings[component].values()
        )
    assert sum(matrix.risk_model.locked_weights().values()) == pytest.approx(1.0)


def test_shipped_ground_truth_abac_and_risk_inputs_are_authored() -> None:
    matrix = shipped_matrix()
    assert matrix.thresholds.t1 == pytest.approx(0.20)
    assert matrix.thresholds.t2 == pytest.approx(0.50)
    assert matrix.thresholds.preregistered
    assert matrix.ground_truth_rules
    assert matrix.ground_truth_rules[-1].rule_id == "GT-D999"
    assert matrix.ground_truth_rules[-1].decision is Decision.DENY
    assert matrix.ground_truth_rules[-1].match == {}
    assert matrix.abac.rules
    assert matrix.abac.default_decision is Decision.DENY
    assert matrix.abac.escalation_collapse is Decision.DENY
    assert matrix.abac.context_assumption is ContextRisk.NORMAL
    assert matrix.abac.missing_items() == ()
    assert not matrix.metrics.is_low_risk_defined


def test_shipped_threshold_grid_records_the_draft_ranges() -> None:
    """The grid is carried over verbatim from the manuscript draft (IV.G)."""
    thresholds = shipped_matrix().thresholds
    assert thresholds.sensitivity_grid["T1"] == (0.30, 0.40, 0.50)
    assert thresholds.sensitivity_grid["T2"] == (0.60, 0.70, 0.80)
    combinations = thresholds.grid_combinations()
    assert len(combinations) == 9
    assert all(t1 < t2 for t1, t2 in combinations)
    assert "IV.G" in thresholds.grid_source


def test_shipped_mechanism_configuration_has_no_pending_authoring_item() -> None:
    matrix = shipped_matrix()
    missing = matrix.missing_authoring_items()
    assert matrix.is_ready_for_primary_experiment
    assert not any(item.startswith("risk_model") for item in missing)
    assert not any(item.startswith("thresholds") for item in missing)
    assert missing == ()
    assert not matrix.metrics.is_low_risk_defined
    assert not any(item.startswith("abac_baseline") for item in missing)
    assert not any(item.startswith("ground_truth_matrix.rules") for item in missing)
    assert matrix.source_path.is_file()


def test_shipped_weights_mappings_and_thresholds_are_locked() -> None:
    matrix = shipped_matrix()
    assert matrix.risk_model.missing_items() == ()
    assert matrix.risk_model.factor_value("contextual_risk", ContextRisk.NORMAL) == 0.0
    assert matrix.thresholds.locked_thresholds() == pytest.approx((0.20, 0.50))


# --------------------------------------------------------------------------- #
# Rule semantics (in-memory fixtures; not experimental rules)
# --------------------------------------------------------------------------- #


def make_rule(
    rule_id: str = "P001",
    *,
    decision: Decision = Decision.DENY,
    match: dict[str, object] | None = None,
    priority: int = 0,
) -> PolicyRule:
    return PolicyRule(
        rule_id=rule_id,
        decision=decision,
        match=match if match is not None else {"tool": ["DELETE_RECORD"]},
        priority=priority,
    )


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


def test_rule_matching_honours_null_as_wildcard_and_is_case_tolerant() -> None:
    rule = make_rule(
        match={
            "role": ["analyst"],
            "destination": None,
            "sensitivity": ["INTERNAL", "confidential"],
        }
    )
    assert rule.matches(make_scenario())
    assert rule.matches(make_scenario(role=Role.ANALYST, destination=Destination.EXTERNAL))
    assert not rule.matches(make_scenario(role=Role.MANAGER))
    assert not rule.matches(make_scenario(sensitivity=Sensitivity.RESTRICTED))


def test_rule_rejects_unknown_attribute_and_empty_value_list() -> None:
    with pytest.raises(ValueError, match="unknown matching attribute"):
        make_rule(match={"resource": ["customer_records"]})
    with pytest.raises(ValueError, match="empty value list"):
        make_rule(match={"tool": []})


def test_rule_from_dict_validates_structure() -> None:
    rule = PolicyRule.from_dict(
        {
            "rule_id": "P010",
            "decision": "deny",
            "match": {"tool": ["DELETE_RECORD"]},
            "description": "deletions are prohibited",
            "rationale": "irreversible operation",
        }
    )
    assert rule.decision is Decision.DENY
    assert rule.to_dict()["match"] == {"tool": ["DELETE_RECORD"]}

    with pytest.raises(ConfigurationError, match="missing required key"):
        PolicyRule.from_dict({"rule_id": "P011", "decision": "ALLOW"})
    with pytest.raises(ConfigurationError, match="unknown key"):
        PolicyRule.from_dict(
            {
                "rule_id": "P012",
                "decision": "ALLOW",
                "match": {},
                "expected_behaviour": "allow",
            }
        )
    with pytest.raises(ConfigurationError, match="no decision"):
        PolicyRule.from_dict({"rule_id": "P013", "decision": None, "match": {}})
    with pytest.raises(ConfigurationError, match="MAYBE"):
        PolicyRule.from_dict({"rule_id": "P014", "decision": "MAYBE", "match": {}})


def test_ground_truth_lookup_and_label_cross_check() -> None:
    matrix = dataclasses.replace(
        shipped_matrix(),
        ground_truth_rules=(
            make_rule("GT1", decision=Decision.ALLOW, match={"tool": ["READ_RECORD"]}),
            make_rule("GT2", decision=Decision.DENY, match={"tool": ["DELETE_RECORD"]}),
        ),
    )
    allowed = make_scenario(scenario_id="S100", tool=Tool.READ_RECORD)
    mismatched = make_scenario(
        scenario_id="S101", tool=Tool.DELETE_RECORD, ground_truth=Decision.ALLOW
    )
    unmatched = make_scenario(scenario_id="S102", tool=Tool.SEND_MESSAGE)

    assert matrix.ground_truth_for(allowed) is Decision.ALLOW
    assert matrix.ground_truth_for(unmatched) is None

    mismatches = validate_ground_truth_against_matrix(
        [allowed, mismatched, unmatched], matrix
    )
    assert [entry.scenario_id for entry in mismatches] == ["S101", "S102"]
    assert "declared ALLOW" in mismatches[0].describe()
    assert "<no rule matched>" in mismatches[1].describe()


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {
                "role": Role.ANALYST,
                "tool": Tool.READ_RECORD,
                "sensitivity": Sensitivity.CONFIDENTIAL,
                "destination": Destination.INTERNAL,
                "context_risk": ContextRisk.NORMAL,
            },
            Decision.ALLOW,
        ),
        (
            {
                "role": Role.ANALYST,
                "tool": Tool.READ_RECORD,
                "sensitivity": Sensitivity.RESTRICTED,
                "destination": Destination.INTERNAL,
                "context_risk": ContextRisk.NORMAL,
            },
            Decision.ESCALATE,
        ),
        (
            {
                "role": Role.ANALYST,
                "tool": Tool.EXPORT_DATA,
                "sensitivity": Sensitivity.RESTRICTED,
                "destination": Destination.EXTERNAL,
                "context_risk": ContextRisk.HIGH_VOLUME,
            },
            Decision.DENY,
        ),
        (
            {
                "role": Role.MANAGER,
                "tool": Tool.EXPORT_DATA,
                "sensitivity": Sensitivity.RESTRICTED,
                "destination": Destination.CONTROLLED_EXTERNAL,
                "context_risk": ContextRisk.NORMAL,
            },
            Decision.ESCALATE,
        ),
        (
            {
                "role": Role.ADMINISTRATOR,
                "tool": Tool.DELETE_RECORD,
                "sensitivity": Sensitivity.CONFIDENTIAL,
                "destination": Destination.INTERNAL,
                "context_risk": ContextRisk.NORMAL,
            },
            Decision.ESCALATE,
        ),
        (
            {
                "role": Role.ADMINISTRATOR,
                "tool": Tool.UPDATE_RECORD,
                "sensitivity": Sensitivity.RESTRICTED,
                "destination": Destination.INTERNAL,
                "context_risk": ContextRisk.NORMAL,
            },
            Decision.ALLOW,
        ),
        (
            {
                "role": Role.ADMINISTRATOR,
                "tool": Tool.EXPORT_DATA,
                "sensitivity": Sensitivity.RESTRICTED,
                "destination": Destination.INTERNAL,
                "context_risk": ContextRisk.NORMAL,
            },
            Decision.ESCALATE,
        ),
        (
            {
                "role": Role.MANAGER,
                "tool": Tool.SEND_MESSAGE,
                "sensitivity": Sensitivity.INTERNAL,
                "destination": Destination.CONTROLLED_EXTERNAL,
                "context_risk": ContextRisk.NORMAL,
            },
            Decision.ALLOW,
        ),
        (
            {
                "role": Role.MANAGER,
                "tool": Tool.SEND_MESSAGE,
                "sensitivity": Sensitivity.INTERNAL,
                "destination": Destination.EXTERNAL,
                "context_risk": ContextRisk.NORMAL,
            },
            Decision.ESCALATE,
        ),
        (
            {
                "role": Role.ADMINISTRATOR,
                "tool": Tool.READ_RECORD,
                "sensitivity": Sensitivity.INTERNAL,
                "destination": Destination.INTERNAL,
                "context_risk": ContextRisk.ANOMALOUS,
            },
            Decision.ESCALATE,
        ),
        (
            {
                "role": Role.ADMINISTRATOR,
                "tool": Tool.EXPORT_DATA,
                "sensitivity": Sensitivity.INTERNAL,
                "destination": Destination.INTERNAL,
                "context_risk": ContextRisk.ANOMALOUS,
            },
            Decision.DENY,
        ),
        (
            {
                "role": Role.MANAGER,
                "tool": Tool.UPDATE_RECORD,
                "sensitivity": Sensitivity.INTERNAL,
                "destination": Destination.CONTROLLED_EXTERNAL,
                "context_risk": ContextRisk.NORMAL,
            },
            Decision.DENY,
        ),
    ],
)
def test_shipped_ground_truth_policy_boundary_cases(
    overrides: dict[str, object], expected: Decision
) -> None:
    scenario = make_scenario(**overrides)
    assert shipped_matrix().ground_truth_for(scenario) is expected


def test_shipped_ground_truth_matches_the_pilot_example() -> None:
    scenarios = load_scenarios(
        Path(__file__).resolve().parent.parent / "data" / "pilot_scenarios.yaml"
    )
    assert validate_ground_truth_against_matrix(scenarios, shipped_matrix()) == ()


def test_label_cross_check_is_empty_when_labels_match_the_authored_matrix() -> None:
    assert validate_ground_truth_against_matrix([make_scenario()], shipped_matrix()) == ()


# --------------------------------------------------------------------------- #
# Structural validation of policy matrix files
# --------------------------------------------------------------------------- #


def minimal_matrix_document() -> dict[str, object]:
    """A structurally valid, fully unset policy matrix document (test fixture)."""
    return {
        "_meta": {"schema_version": "test-fixture", "status": "test-fixture"},
        "dimensions": {
            "role": [member.value for member in Role],
            "tool": [member.value for member in Tool],
            "sensitivity": [member.value for member in Sensitivity],
            "destination": [member.value for member in Destination],
            "context_risk": [member.value for member in ContextRisk],
        },
        "ground_truth_matrix": {"rules": []},
        "risk_model": {
            "formula": "R = w_s*S + w_a*A + w_e*E + w_c*C",
            "weights": {component: None for component in COMPONENT_KEYS},
            "weight_locked": False,
            "component_sources": {
                "sensitivity": "sensitivity",
                "action_severity": "tool",
                "exposure_scope": "destination",
                "contextual_risk": "context_risk",
            },
            "factor_mappings": {
                "sensitivity": {member.value: None for member in Sensitivity},
                "action_severity": {member.value: None for member in Tool},
                "exposure_scope": {member.value: None for member in Destination},
                "contextual_risk": {member.value: None for member in ContextRisk},
            },
        },
        "thresholds": {
            "T1_escalation": None,
            "T2_denial": None,
            "preregistered": False,
            "sensitivity_grid": {"T1": [], "T2": []},
        },
        "abac_baseline": {
            "binary_only": True,
            "attributes": ["role", "tool", "sensitivity", "destination"],
            "default_decision": None,
            "rules": [],
        },
        "metrics": {},
    }


def write_matrix(tmp_path: Path, document: dict[str, object]) -> Path:
    path = tmp_path / "matrix.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_minimal_fixture_matrix_loads_and_stays_unconfigured(tmp_path: Path) -> None:
    matrix = load_policy_matrix(write_matrix(tmp_path, minimal_matrix_document()))
    assert matrix.status == "test-fixture"
    assert not matrix.is_ready_for_primary_experiment
    assert matrix.thresholds.grid_combinations() == ()


def test_dimension_drift_between_yaml_and_enums_is_rejected(tmp_path: Path) -> None:
    document = minimal_matrix_document()
    document["dimensions"]["tool"] = ["READ_RECORD"]  # type: ignore[index]
    with pytest.raises(ConfigurationError, match="dimensions.tool"):
        load_policy_matrix(write_matrix(tmp_path, document))


def test_mapping_key_drift_is_rejected(tmp_path: Path) -> None:
    document = minimal_matrix_document()
    mappings = document["risk_model"]["factor_mappings"]  # type: ignore[index]
    mappings["exposure_scope"].pop("EXTERNAL")  # type: ignore[union-attr]
    with pytest.raises(ConfigurationError, match="factor_mappings.exposure_scope"):
        load_policy_matrix(write_matrix(tmp_path, document))


def test_weights_that_do_not_sum_to_one_are_rejected(tmp_path: Path) -> None:
    document = minimal_matrix_document()
    document["risk_model"]["weights"] = {  # type: ignore[index]
        component: 0.4 for component in COMPONENT_KEYS
    }
    with pytest.raises(ConfigurationError, match="sum to 1.0"):
        load_policy_matrix(write_matrix(tmp_path, document))


def test_missing_top_level_section_is_reported(tmp_path: Path) -> None:
    document = minimal_matrix_document()
    document.pop("risk_model")
    with pytest.raises(ConfigurationError, match="risk_model"):
        load_policy_matrix(write_matrix(tmp_path, document))


def test_duplicate_rule_ids_are_rejected(tmp_path: Path) -> None:
    document = minimal_matrix_document()
    document["ground_truth_matrix"]["rules"] = [  # type: ignore[index]
        {"rule_id": "GT1", "decision": "ALLOW", "match": {"tool": ["READ_RECORD"]}},
        {"rule_id": "GT1", "decision": "DENY", "match": {"tool": ["DELETE_RECORD"]}},
    ]
    with pytest.raises(ConfigurationError, match="duplicate rule_id"):
        load_policy_matrix(write_matrix(tmp_path, document))


def test_the_baseline_rejects_non_binary_rules(tmp_path: Path) -> None:
    document = minimal_matrix_document()
    document["abac_baseline"]["rules"] = [  # type: ignore[index]
        {"rule_id": "B1", "decision": "ESCALATE", "match": {"tool": ["READ_RECORD"]}}
    ]
    with pytest.raises(ConfigurationError, match="non-binary decision"):
        load_policy_matrix(write_matrix(tmp_path, document))


def test_the_baseline_rejects_rules_outside_its_attributes(tmp_path: Path) -> None:
    document = minimal_matrix_document()
    document["abac_baseline"]["rules"] = [  # type: ignore[index]
        {"rule_id": "B2", "decision": "DENY", "match": {"context_risk": ["ANOMALOUS"]}}
    ]
    with pytest.raises(ConfigurationError, match="does not evaluate"):
        load_policy_matrix(write_matrix(tmp_path, document))


# --------------------------------------------------------------------------- #
# Scenario dataset loading
# --------------------------------------------------------------------------- #


def test_shipped_primary_dataset_contains_the_authored_final_scenarios() -> None:
    scenarios = load_scenarios()
    assert len(scenarios) == 150
    assert all(scenario.scenario_id.startswith("F") for scenario in scenarios)


def test_pilot_dataset_is_separate_balanced_and_policy_labelled() -> None:
    scenarios = load_scenarios(
        Path(__file__).resolve().parent.parent / "data" / "pilot_scenarios.yaml"
    )
    assert len(scenarios) == 24
    assert {scenario.role for scenario in scenarios} == set(Role)
    assert {scenario.tool for scenario in scenarios} == set(Tool)
    assert {scenario.sensitivity for scenario in scenarios} == set(Sensitivity)
    assert {scenario.ground_truth for scenario in scenarios} == set(Decision)
    assert all(scenario.scenario_id.startswith("P") for scenario in scenarios)
    assert all(scenario.metadata["dataset_partition"] == "pilot" for scenario in scenarios)
    assert validate_ground_truth_against_matrix(scenarios, shipped_matrix()) == ()


def test_scenario_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "scenarios.yaml"
    entry = {
        "scenario_id": "S001",
        "role": "ANALYST",
        "tool": "READ_RECORD",
        "sensitivity": "INTERNAL",
        "destination": "INTERNAL",
        "context_risk": "NORMAL",
        "ground_truth": "ALLOW",
    }
    path.write_text(
        yaml.safe_dump({"scenarios": [entry, dict(entry)]}, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="duplicate scenario_id"):
        load_scenarios(path)


def test_scenario_loader_requires_the_scenarios_key(tmp_path: Path) -> None:
    path = tmp_path / "scenarios.yaml"
    path.write_text(yaml.safe_dump({"dataset": []}), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="'scenarios' key"):
        load_scenarios(path)


def test_configuration_loading_reports_missing_and_invalid_files(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        load_yaml_mapping(tmp_path / "missing.yaml")

    not_a_mapping = tmp_path / "list.yaml"
    not_a_mapping.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="top-level mapping"):
        load_yaml_mapping(not_a_mapping)

    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="is empty"):
        load_yaml_mapping(empty)
