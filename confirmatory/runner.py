"""Fail-closed confirmatory authorization evaluation runner."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from confirmatory.analysis import (
    escalation_resolution,
    primary_paired_tests,
    summary_metrics,
)
from confirmatory.comparator import ContextAwareABACEngine
from confirmatory.provenance import (
    CONFIRMATORY_ROOT,
    environment_metadata,
    output_hashes,
    repository_relative,
    verify_freeze,
)
from src.calibration import verify_calibrated_configuration
from src.models import ConfigurationError, Decision
from src.policy import (
    DEFAULT_PILOT_SCENARIOS_PATH,
    load_final_scenarios,
    load_policy_matrix,
    validate_ground_truth_against_matrix,
)
from src.risk_engine import RiskEngine

INPUT_DIR = CONFIRMATORY_ROOT / "inputs"
DEFAULT_RESULTS_DIR = CONFIRMATORY_ROOT / "results" / "authorization"


def _run_tests() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q"]
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    completed = subprocess.run(
        command,
        cwd=CONFIRMATORY_ROOT.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    record = {
        "command": [Path(sys.executable).name, "-m", "pytest", "-q"],
        "started_at_utc": started,
        "exit_code": completed.returncode,
        "passed": completed.returncode == 0,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }
    if completed.returncode != 0:
        raise ConfigurationError("full test suite failed; confirmatory run refused")
    return record


def evaluate() -> pd.DataFrame:
    matrix = load_policy_matrix(INPUT_DIR / "policy_matrix.yaml")
    if not matrix.locked_for_primary_experiment:
        raise ConfigurationError(
            "confirmatory evaluation requires locked_for_primary_experiment=true"
        )
    verify_calibrated_configuration(
        matrix,
        pilot_path=DEFAULT_PILOT_SCENARIOS_PATH,
        risk_config_path=INPUT_DIR / "risk_config.yaml",
    )
    scenarios = load_final_scenarios(INPUT_DIR / "scenarios.yaml")
    if len(scenarios) != 150:
        raise ConfigurationError("confirmatory evaluation requires 150 frozen scenarios")
    mismatches = validate_ground_truth_against_matrix(scenarios, matrix)
    if mismatches:
        raise ConfigurationError(
            "confirmatory scenario labels differ from frozen qualitative policy: "
            + "; ".join(item.describe() for item in mismatches[:5])
        )
    comparator = ContextAwareABACEngine.from_files(matrix)
    risk = RiskEngine.from_policy_matrix(matrix)
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        comparator_outcome = comparator.authorize(scenario)
        risk_outcome = risk.authorize(scenario)
        if comparator_outcome.decision not in {Decision.ALLOW, Decision.DENY}:
            raise ConfigurationError("confirmatory ABAC emitted a non-binary decision")
        rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "role": scenario.role.value,
                "tool": scenario.tool.value,
                "sensitivity": scenario.sensitivity.value,
                "destination": scenario.destination.value,
                "context_risk": scenario.context_risk.value,
                "ground_truth": scenario.ground_truth.value if scenario.ground_truth else "",
                "context_abac_decision": comparator_outcome.decision.value,
                "risk_adaptive_decision": risk_outcome.decision.value,
                "risk_score": risk_outcome.score,
                "context_abac_explanation": comparator_outcome.explanation,
                "risk_adaptive_explanation": risk_outcome.explanation,
            }
        )
    frame = pd.DataFrame(rows)
    if len(frame) != 150 or frame["scenario_id"].nunique() != 150:
        raise ConfigurationError("confirmatory evaluation did not preserve matched pairs")
    return frame


def run_confirmatory(
    output_dir: str | Path = DEFAULT_RESULTS_DIR,
    *,
    command_line: list[str] | None = None,
) -> dict[str, Path]:
    freeze = verify_freeze(require_empty_authorization=True)
    destination = Path(output_dir)
    if destination.exists() and any(destination.iterdir()):
        raise ConfigurationError(
            f"confirmatory output directory is not empty: {destination}; refusing overwrite"
        )
    test_record = _run_tests()
    decisions = evaluate()
    outputs = {
        "decisions": destination / "decisions.csv",
        "summary_metrics": destination / "summary_metrics.csv",
        "primary_statistical_tests": destination / "primary_statistical_tests.csv",
        "escalation_analysis": destination / "escalation_analysis.csv",
    }
    destination.mkdir(parents=True, exist_ok=True)
    decisions.to_csv(outputs["decisions"], index=False)
    summary_metrics(decisions).to_csv(outputs["summary_metrics"], index=False)
    primary_paired_tests(decisions).to_csv(
        outputs["primary_statistical_tests"], index=False
    )
    escalation_resolution(decisions).to_csv(
        outputs["escalation_analysis"], index=False
    )
    verify_freeze(require_empty_authorization=False)
    manifest_path = destination / "run_manifest.json"
    manifest = {
        "experiment": "confirmatory",
        "earlier_exploratory_run_preregistered": False,
        "primary_comparator": "context_aware_binary_abac",
        "environment": environment_metadata(command_line),
        "input_hashes": freeze["required_inputs"],
        "freeze_protocol_version": freeze["protocol_version"],
        "research_source_allowlist_version": freeze[
            "research_source_allowlist_version"
        ],
        "research_source_manifest_sha256": freeze[
            "research_source_manifest_sha256"
        ],
        "aggregate_research_source_sha256": freeze[
            "aggregate_research_source_sha256"
        ],
        "dependency_lock_sha256": freeze["dependency_lock_sha256"],
        "test_result": test_record,
        "outputs": output_hashes(outputs),
        "latency_measured_here": False,
        "latency_benchmark": "separate confirmatory.latency_benchmark command",
        "generalization_scope": "frozen purposive synthetic benchmark only",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return outputs | {"manifest": manifest_path}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check or run the frozen confirmatory evaluation")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output-dir", default=str(DEFAULT_RESULTS_DIR))
    args = parser.parse_args(argv)
    try:
        verify_freeze(require_empty_authorization=True)
        if not args.execute:
            print("Confirmatory Freeze v2 verified. No evaluation was run.")
            return 0
        paths = run_confirmatory(
            args.output_dir,
            command_line=["python", "-m", "confirmatory.runner", "--execute"],
        )
    except ConfigurationError as exc:
        print(f"confirmatory run refused: {exc}", file=sys.stderr)
        return 2
    for name, path in paths.items():
        print(f"{name}: {repository_relative(path)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
