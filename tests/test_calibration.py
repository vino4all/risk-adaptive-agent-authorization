"""Pilot-calibration reproducibility and final-dataset separation tests."""

from __future__ import annotations

from itertools import product
from pathlib import Path

import pytest
import yaml

from src.calibration import (
    COMPONENT_MAPPINGS,
    DEFAULT_RISK_CONFIG_PATH,
    calibrate,
    verify_calibrated_configuration,
    verify_persisted_config,
)
from src.experiment import run_experiment
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
    DEFAULT_PILOT_SCENARIOS_PATH,
    load_final_scenarios,
    load_policy_matrix,
    load_scenarios,
    load_yaml_mapping,
)
from src.risk_engine import RiskEngine


def test_persisted_weights_sum_to_one_and_thresholds_are_ordered() -> None:
    document = load_yaml_mapping(DEFAULT_RISK_CONFIG_PATH)
    selected = document["selected_configuration"]
    assert sum(selected["weights"].values()) == pytest.approx(1.0)
    assert selected["T1"] < selected["T2"]


def test_component_mappings_are_normalized() -> None:
    assert all(
        0.0 <= value <= 1.0
        for mapping in COMPONENT_MAPPINGS.values()
        for value in mapping.values()
    )


def test_calibration_reproduces_persisted_selection_and_reports_tie() -> None:
    pilots = load_scenarios(DEFAULT_PILOT_SCENARIOS_PATH)
    result = calibrate(pilots, load_policy_matrix())
    verify_persisted_config(result)
    assert result.pilot_count == 24
    assert len(result.candidates) == 45
    assert result.selected.weight_name == "equal"
    assert result.selected.unsafe_automatic_allow == 0
    assert result.selected.t1 == pytest.approx(0.20)
    assert result.selected.t2 == pytest.approx(0.50)
    assert {item.weight_name for item in result.similar} == {
        "equal",
        "data_exposure",
    }


def test_operational_policy_matches_frozen_calibration() -> None:
    result = verify_calibrated_configuration(load_policy_matrix())
    assert result.selected.weights == load_policy_matrix().risk_model.locked_weights()


def test_pilot_file_cannot_be_loaded_as_final_dataset() -> None:
    with pytest.raises(ConfigurationError, match="calibration-only"):
        load_final_scenarios(DEFAULT_PILOT_SCENARIOS_PATH)


def test_copied_pilot_id_cannot_enter_final_dataset(tmp_path: Path) -> None:
    pilot = load_scenarios(DEFAULT_PILOT_SCENARIOS_PATH)[0].to_dict()
    pilot["metadata"] = {}
    path = tmp_path / "final.yaml"
    path.write_text(
        yaml.safe_dump({"scenarios": [pilot]}, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(ConfigurationError, match="P001"):
        load_final_scenarios(path)


def test_renamed_pilot_attribute_tuple_cannot_enter_final_dataset(tmp_path: Path) -> None:
    pilot = load_scenarios(DEFAULT_PILOT_SCENARIOS_PATH)[0].to_dict()
    pilot["scenario_id"] = "F999"
    pilot["metadata"] = {"dataset_partition": "final"}
    path = tmp_path / "final.yaml"
    path.write_text(
        yaml.safe_dump({"scenarios": [pilot]}, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(ConfigurationError, match="F999"):
        load_final_scenarios(path)


def test_experiment_runner_rejects_marked_pilot_scenarios() -> None:
    pilots = load_scenarios(DEFAULT_PILOT_SCENARIOS_PATH)
    with pytest.raises(ConfigurationError, match="calibration-only"):
        run_experiment(load_policy_matrix(), pilots)


def test_calibrated_score_stays_in_unit_interval_for_full_attribute_domain() -> None:
    engine = RiskEngine.from_policy_matrix(load_policy_matrix())
    for index, (role, tool, sensitivity, destination, context) in enumerate(
        product(Role, Tool, Sensitivity, Destination, ContextRisk), start=1
    ):
        scenario = Scenario(
            scenario_id=f"DOMAIN-{index:03d}",
            role=role,
            tool=tool,
            sensitivity=sensitivity,
            destination=destination,
            context_risk=context,
            ground_truth=Decision.ALLOW,
        )
        assert 0.0 <= engine.score(scenario).score <= 1.0
