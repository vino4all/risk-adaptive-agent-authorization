"""Automated validation of the final policy-labelled scenario dataset."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from src.dataset_generation import (
    generate_dataset,
    load_qualitative_rules,
    render_report,
    validation_summary,
)
from src.models import ContextRisk, Decision, Destination, Role, Sensitivity, Tool
from src.policy import (
    DEFAULT_PILOT_SCENARIOS_PATH,
    DEFAULT_SCENARIOS_PATH,
    load_final_scenarios,
    load_scenarios,
    load_yaml_mapping,
)


def attribute_key(scenario):  # noqa: ANN001, ANN201 - compact test helper
    return (
        scenario.role,
        scenario.tool,
        scenario.sensitivity,
        scenario.destination,
        scenario.context_risk,
    )


def test_final_dataset_has_target_size_required_fields_and_unique_rows() -> None:
    scenarios = load_final_scenarios()
    assert len(scenarios) == 150
    assert len({scenario.scenario_id for scenario in scenarios}) == 150
    assert len({attribute_key(scenario) for scenario in scenarios}) == 150
    assert all(scenario.description.strip() for scenario in scenarios)
    assert all(scenario.rationale.strip() for scenario in scenarios)
    assert all(scenario.policy_rule_ids for scenario in scenarios)
    assert all(scenario.metadata.get("dataset_partition") == "final" for scenario in scenarios)


def test_final_dataset_has_full_stratification_and_meaningful_classes() -> None:
    scenarios = load_final_scenarios()
    assert {scenario.role for scenario in scenarios} == set(Role)
    assert {scenario.tool for scenario in scenarios} == set(Tool)
    assert {scenario.sensitivity for scenario in scenarios} == set(Sensitivity)
    assert {scenario.destination for scenario in scenarios} == set(Destination)
    assert {scenario.context_risk for scenario in scenarios} == set(ContextRisk)
    class_counts = Counter(scenario.ground_truth for scenario in scenarios)
    assert set(class_counts) == set(Decision)
    assert all(class_counts[decision] >= 25 for decision in Decision)


def test_every_label_and_rule_identifier_matches_first_qualitative_rule() -> None:
    rules = load_qualitative_rules()
    for scenario in load_final_scenarios():
        matched = next(rule for rule in rules if rule.matches(scenario))
        assert scenario.ground_truth is matched.decision
        assert scenario.policy_rule_ids == (matched.rule_id,)
        assert scenario.rationale.startswith(f"{matched.rule_id}:")


def test_final_dataset_has_no_pilot_ids_or_attribute_duplicates() -> None:
    final = load_final_scenarios()
    pilot = load_scenarios(DEFAULT_PILOT_SCENARIOS_PATH)
    assert {scenario.scenario_id for scenario in final}.isdisjoint(
        scenario.scenario_id for scenario in pilot
    )
    assert {attribute_key(scenario) for scenario in final}.isdisjoint(
        attribute_key(scenario) for scenario in pilot
    )


def test_generation_is_reproducible_and_matches_committed_dataset() -> None:
    assert generate_dataset() == load_final_scenarios()


def test_dataset_metadata_confirms_no_authorization_algorithm_was_run() -> None:
    document = load_yaml_mapping(DEFAULT_SCENARIOS_PATH)
    assert document["_meta"]["authorization_algorithms_run"] is False
    assert document["_meta"]["ground_truth_source"].endswith("#ground_truth_matrix")
    assert document["_meta"]["pilot_scenarios_excluded"] is True


def test_validation_report_matches_recomputed_counts_and_cross_tabs() -> None:
    scenarios = load_final_scenarios()
    summary = validation_summary(scenarios)
    assert summary["scenario_count"] == 150
    assert summary["role_counts"] == {
        "ADMINISTRATOR": 50,
        "ANALYST": 50,
        "MANAGER": 50,
    }
    assert summary["tool_counts"] == {tool.value: 30 for tool in sorted(Tool, key=lambda item: item.value)}
    assert set(summary["cross_tabs"]) == {
        "ground_truth_by_role",
        "ground_truth_by_tool",
        "ground_truth_by_sensitivity",
        "ground_truth_by_destination",
        "ground_truth_by_context_risk",
    }
    public_report = Path(__file__).resolve().parents[1] / "docs/methodology/dataset_validation.md"
    assert public_report.read_text(encoding="utf-8") == render_report(summary)


def test_generator_has_no_authorization_or_calibration_dependency() -> None:
    import src.dataset_generation as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    forbidden = ("risk_config", "risk_engine", "RiskEngine", "ABACEngine", "T1", "T2")
    assert all(token not in source for token in forbidden)
