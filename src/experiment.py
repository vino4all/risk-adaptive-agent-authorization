"""Experiment runner.

In the skeleton phase this program does two things and nothing more:

``--check`` (default)
    Validate the configuration and the scenario file, then print a readiness
    report listing every value that still has to be authored.  It writes no
    results, because no experiment has been run yet.

``--run``
    Evaluate the identical scenario set with both mechanisms, write the results
    and a reproducibility manifest into ``results/<run-id>/``.  This refuses to
    proceed while the configuration is incomplete: an unconfigured run would
    produce numbers that are not experimental results.

Nothing in this module fabricates policy rules, weights, thresholds or results.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.abac import ABACEngine
from src.calibration import verify_calibrated_configuration
from src.evaluator import EvaluationRun, Evaluator
from src.models import ConfigurationError, Method, Scenario
from src.policy import (
    DEFAULT_PILOT_SCENARIOS_PATH,
    DEFAULT_POLICY_MATRIX_PATH,
    DEFAULT_SCENARIOS_PATH,
    PolicyMatrix,
    load_final_scenarios,
    load_policy_matrix,
    load_scenarios,
)
from src.risk_engine import RiskEngine

__all__ = [
    "EXIT_CONFIGURATION_NOT_READY",
    "EXIT_OK",
    "EXIT_RUN_FAILED",
    "ReadinessReport",
    "build_readiness_report",
    "build_parser",
    "main",
    "run_experiment",
    "write_results",
]

EXIT_OK = 0
EXIT_CONFIGURATION_NOT_READY = 2
EXIT_RUN_FAILED = 3

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """What is present in the configuration and what is still missing."""

    policy_matrix_path: Path
    scenarios_path: Path
    scenario_count: int
    labelled_scenario_count: int
    missing_authoring_items: tuple[str, ...]
    dimension_summary: dict[str, int] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def is_ready(self) -> bool:
        return not self.missing_authoring_items

    def render(self) -> str:
        """Human-readable readiness report."""
        lines = [
            "Configuration readiness report",
            "=" * 60,
            f"policy matrix      : {self.policy_matrix_path}",
            f"scenario file      : {self.scenarios_path}",
            f"scenarios loaded   : {self.scenario_count} "
            f"({self.labelled_scenario_count} labelled)",
        ]
        if self.dimension_summary:
            dimensions = ", ".join(
                f"{name}={count}"
                for name, count in sorted(self.dimension_summary.items())
            )
            lines.append(f"dimension values   : {dimensions}")
        for note in self.notes:
            lines.append(f"note               : {note}")
        lines.append("")
        if self.is_ready:
            lines.append(
                "STATUS: ready -- all authored values are present, "
                "the primary experiment can be run."
            )
        else:
            lines.append(
                f"STATUS: not ready -- {len(self.missing_authoring_items)} "
                "item(s) still to author:"
            )
            lines.extend(f"  - {item}" for item in self.missing_authoring_items)
            lines.append("")
            lines.append(
                "No results were produced.  Authoring these values is an "
                "experiment-design decision, so the code does not guess them."
            )
        return "\n".join(lines)


def build_readiness_report(
    matrix: PolicyMatrix,
    scenarios: Sequence[Scenario],
    *,
    scenarios_path: Path,
) -> ReadinessReport:
    """Summarize configuration completeness and dataset state."""
    notes: list[str] = []
    if not scenarios:
        notes.append(
            "the scenario file contains no scenarios yet; the primary dataset "
            "(~150 balanced scenarios) still has to be authored"
        )
    unlabelled = [s.scenario_id for s in scenarios if not s.is_labelled]
    if unlabelled:
        notes.append(
            f"{len(unlabelled)} scenario(s) have no ground-truth label yet: "
            + ", ".join(unlabelled[:5])
            + (" ..." if len(unlabelled) > 5 else "")
        )
    if not matrix.metrics.is_low_risk_defined:
        notes.append(
            "the low-risk designation required by the unnecessary-escalation "
            "rate is not authored yet"
        )
    return ReadinessReport(
        policy_matrix_path=matrix.source_path,
        scenarios_path=Path(scenarios_path),
        scenario_count=len(scenarios),
        labelled_scenario_count=sum(1 for s in scenarios if s.is_labelled),
        missing_authoring_items=matrix.missing_authoring_items(),
        dimension_summary={
            name: len(values) for name, values in matrix.dimensions.items()
        },
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------- #
# Running the comparison
# --------------------------------------------------------------------------- #


def run_experiment(
    matrix: PolicyMatrix,
    scenarios: Sequence[Scenario],
    *,
    scenario_source: str | None = None,
) -> tuple[EvaluationRun, EvaluationRun]:
    """Evaluate one scenario set with both mechanisms (matched-pair design).

    Both mechanisms see the identical scenario objects, so results can be paired
    by ``scenario_id`` during analysis.  Latency is measured inside the evaluator
    and covers authorization only, never tool execution.
    """
    pilot_ids = [
        scenario.scenario_id
        for scenario in scenarios
        if str(scenario.metadata.get("dataset_partition", "")).lower() == "pilot"
    ]
    if pilot_ids:
        raise ConfigurationError(
            "pilot scenarios are calibration-only and cannot enter final "
            "evaluation: " + ", ".join(pilot_ids)
        )
    risk_evaluator = Evaluator(
        policy=RiskEngine.from_policy_matrix(matrix),
        method=Method.RISK_ADAPTIVE,
    )
    abac_evaluator = Evaluator(
        policy=ABACEngine.from_policy_matrix(matrix),
        method=Method.ABAC_BINARY,
    )
    return (
        risk_evaluator.run(scenarios, scenario_source=scenario_source),
        abac_evaluator.run(scenarios, scenario_source=scenario_source),
    )


def write_results(
    runs: Sequence[EvaluationRun],
    matrix: PolicyMatrix,
    *,
    out_dir: str | Path = DEFAULT_RESULTS_DIR,
    run_id: str | None = None,
    readiness: ReadinessReport | None = None,
) -> Path:
    """Persist results and a reproducibility manifest; return the run directory."""
    resolved_run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(out_dir) / resolved_run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = [row for run in runs for row in run.to_records()]
    frame = pd.DataFrame(rows)
    column_order = [
        "scenario_id",
        "run_label",
        "method",
        "decision",
        "ground_truth",
        "correct_for_binary_safe_execution",
        "true_escalate_resolved_as_allow",
        "true_escalate_resolved_as_deny",
        "score",
        "latency_ms",
        "explanation",
    ]
    frame = frame.reindex(columns=column_order)
    frame.to_csv(run_dir / "authorization_results.csv", index=False)

    manifest = {
        "run_id": resolved_run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy_matrix": matrix.to_dict(),
        "runs": [run.to_manifest() for run in runs],
        "readiness": (
            None
            if readiness is None
            else {
                "is_ready": readiness.is_ready,
                "scenario_count": readiness.scenario_count,
                "missing_authoring_items": list(readiness.missing_authoring_items),
                "notes": list(readiness.notes),
            }
        ),
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return run_dir


# --------------------------------------------------------------------------- #
# Command line interface
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.experiment",
        description=(
            "Skeleton experiment runner for three-way (ALLOW/ESCALATE/DENY) "
            "risk-adaptive authorization versus binary ABAC.  By default it only "
            "checks configuration readiness and writes nothing."
        ),
    )
    parser.add_argument("--policy-matrix", default=str(DEFAULT_POLICY_MATRIX_PATH))
    parser.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS_PATH))
    parser.add_argument(
        "--pilot",
        action="store_true",
        help=f"use the pilot dataset ({DEFAULT_PILOT_SCENARIOS_PATH.name}) instead",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="run the evaluation once every authored value is present",
    )
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument("--run-id", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scenarios_path = (
        Path(DEFAULT_PILOT_SCENARIOS_PATH) if args.pilot else Path(args.scenarios)
    )

    try:
        matrix = load_policy_matrix(args.policy_matrix)
        scenarios = (
            load_scenarios(scenarios_path)
            if args.pilot
            else load_final_scenarios(scenarios_path)
        )
    except ConfigurationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIGURATION_NOT_READY

    report = build_readiness_report(matrix, scenarios, scenarios_path=scenarios_path)
    print(report.render())
    print()

    if not args.run:
        return EXIT_OK if report.is_ready else EXIT_CONFIGURATION_NOT_READY

    if args.pilot:
        print(
            "--run refused: pilot scenarios are calibration-only and cannot be "
            "used for final experiment evaluation.",
            file=sys.stderr,
        )
        return EXIT_CONFIGURATION_NOT_READY

    if not report.is_ready:
        print(
            "--run refused: the authored values listed above are required before "
            "the experiment may run.",
            file=sys.stderr,
        )
        return EXIT_CONFIGURATION_NOT_READY
    if not scenarios:
        print(
            "--run refused: the scenario dataset is empty.",
            file=sys.stderr,
        )
        return EXIT_CONFIGURATION_NOT_READY

    try:
        verify_calibrated_configuration(matrix)
        runs = run_experiment(matrix, scenarios, scenario_source=str(scenarios_path))
    except ConfigurationError as exc:
        print(f"run failed: {exc}", file=sys.stderr)
        return EXIT_RUN_FAILED

    run_dir = write_results(
        runs,
        matrix,
        out_dir=args.results_dir,
        run_id=args.run_id,
        readiness=report,
    )
    for run in runs:
        counts = ", ".join(
            f"{decision}={count}"
            for decision, count in run.decision_counts().items()
            if count
        )
        print(f"{run.method.value:<14} {counts}")
    print(f"\nresults written to {run_dir}")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
