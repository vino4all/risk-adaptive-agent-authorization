"""Separate confirmatory authorization microbenchmark.

The benchmark stores every repetition, counterbalances method order within each
scenario, and bases inference on one median latency per scenario and method.
"""

from __future__ import annotations

import argparse
import gc
import json
import random
import sys
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from confirmatory.comparator import ContextAwareABACEngine
from confirmatory.provenance import (
    CONFIRMATORY_ROOT,
    environment_metadata,
    output_hashes,
    repository_relative,
    verify_freeze,
)
from src.models import ConfigurationError
from src.policy import load_final_scenarios, load_policy_matrix
from src.risk_engine import RiskEngine

INPUT_DIR = CONFIRMATORY_ROOT / "inputs"
DEFAULT_OUTPUT_DIR = CONFIRMATORY_ROOT / "results" / "latency"
BENCHMARK_SEED = 20261018
DEFAULT_WARMUP_ROUNDS = 20
DEFAULT_REPETITIONS = 200
DEFAULT_TIMER_OVERHEAD_SAMPLES = 10_000
DEFAULT_PERMUTATIONS = 100_000
DEFAULT_BOOTSTRAP_REPLICATES = 10_000


def measure_timer_overhead(samples: int) -> list[int]:
    if samples <= 0:
        raise ConfigurationError("timer overhead sample count must be positive")
    values: list[int] = []
    for _ in range(samples):
        start = time.perf_counter_ns()
        end = time.perf_counter_ns()
        values.append(end - start)
    return values


def _warm_up(scenarios, comparator, risk, rounds: int) -> None:  # noqa: ANN001
    if rounds < 1:
        raise ConfigurationError("warm-up rounds must be positive")
    for _ in range(rounds):
        for scenario in scenarios:
            comparator.authorize(scenario)
            risk.authorize(scenario)


def _timed_authorize(engine, scenario) -> tuple[int, str]:  # noqa: ANN001
    start = time.perf_counter_ns()
    outcome = engine.authorize(scenario)
    elapsed = time.perf_counter_ns() - start
    return elapsed, outcome.decision.value


def collect_raw_measurements(
    scenarios,
    comparator,
    risk,
    *,
    repetitions: int = DEFAULT_REPETITIONS,
    seed: int = BENCHMARK_SEED,
) -> list[dict[str, Any]]:  # noqa: ANN001
    """Collect randomized pairs with exactly half of each within-pair order."""
    if repetitions < 2 or repetitions % 2:
        raise ConfigurationError("repetitions must be an even integer of at least 2")
    rng = random.Random(seed)
    tasks: list[tuple[Any, int, str]] = []
    for scenario in scenarios:
        orders = ["context_abac_first"] * (repetitions // 2) + [
            "risk_adaptive_first"
        ] * (repetitions // 2)
        rng.shuffle(orders)
        tasks.extend((scenario, repetition, order) for repetition, order in enumerate(orders, 1))
    rng.shuffle(tasks)

    rows: list[dict[str, Any]] = []
    for block, (scenario, repetition, order) in enumerate(tasks, start=1):
        engines = (
            (("context_aware_binary_abac", comparator), ("risk_adaptive", risk))
            if order == "context_abac_first"
            else (("risk_adaptive", risk), ("context_aware_binary_abac", comparator))
        )
        for order_position, (method, engine) in enumerate(engines, start=1):
            elapsed, decision = _timed_authorize(engine, scenario)
            rows.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "repetition": repetition,
                    "randomized_block": block,
                    "pair_order": order,
                    "order_position": order_position,
                    "method": method,
                    "latency_ns": elapsed,
                    "decision": decision,
                }
            )
    return rows


def aggregate_scenarios(raw: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        raw.groupby(["scenario_id", "method"])["latency_ns"]
        .agg(repetitions="size", median_ns="median", mean_ns="mean", p95_ns=lambda x: np.percentile(x, 95), p99_ns=lambda x: np.percentile(x, 99))
        .reset_index()
    )
    pivot = grouped.pivot(index="scenario_id", columns="method")
    rows: list[dict[str, Any]] = []
    for scenario_id in pivot.index:
        comparator_median = float(pivot.loc[scenario_id, ("median_ns", "context_aware_binary_abac")])
        risk_median = float(pivot.loc[scenario_id, ("median_ns", "risk_adaptive")])
        rows.append(
            {
                "scenario_id": scenario_id,
                "repetitions_per_method": int(pivot.loc[scenario_id, ("repetitions", "context_aware_binary_abac")]),
                "context_abac_median_ns": comparator_median,
                "risk_adaptive_median_ns": risk_median,
                "paired_median_difference_ns": risk_median - comparator_median,
                "context_abac_mean_ns": float(pivot.loc[scenario_id, ("mean_ns", "context_aware_binary_abac")]),
                "risk_adaptive_mean_ns": float(pivot.loc[scenario_id, ("mean_ns", "risk_adaptive")]),
                "context_abac_p95_ns": float(pivot.loc[scenario_id, ("p95_ns", "context_aware_binary_abac")]),
                "risk_adaptive_p95_ns": float(pivot.loc[scenario_id, ("p95_ns", "risk_adaptive")]),
                "context_abac_p99_ns": float(pivot.loc[scenario_id, ("p99_ns", "context_aware_binary_abac")]),
                "risk_adaptive_p99_ns": float(pivot.loc[scenario_id, ("p99_ns", "risk_adaptive")]),
            }
        )
    return pd.DataFrame(rows).sort_values("scenario_id").reset_index(drop=True)


def paired_permutation_and_cluster_interval(
    scenario_summary: pd.DataFrame,
    *,
    permutations: int = DEFAULT_PERMUTATIONS,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    seed: int = BENCHMARK_SEED,
) -> dict[str, Any]:
    differences = scenario_summary["paired_median_difference_ns"].to_numpy(dtype=float)
    if len(differences) == 0:
        raise ConfigurationError("latency inference requires scenario summaries")
    rng = np.random.default_rng(seed)
    observed = float(np.mean(differences))
    extreme = 0
    batch_size = 10_000
    remaining = permutations
    while remaining:
        current = min(batch_size, remaining)
        signs = rng.choice((-1.0, 1.0), size=(current, len(differences)))
        permuted = np.mean(signs * differences, axis=1)
        extreme += int(np.sum(np.abs(permuted) >= abs(observed)))
        remaining -= current
    p_value = (extreme + 1) / (permutations + 1)
    indices = rng.integers(
        0,
        len(differences),
        size=(bootstrap_replicates, len(differences)),
    )
    bootstrap = np.mean(differences[indices], axis=1)
    lower, upper = np.percentile(bootstrap, [2.5, 97.5])
    return {
        "analysis_unit": "scenario-level median latency",
        "effect": "mean paired difference of scenario medians (risk minus comparator)",
        "effect_ns": observed,
        "ci_lower_ns": float(lower),
        "ci_upper_ns": float(upper),
        "ci_method": "95% scenario-cluster percentile bootstrap",
        "test": "two-sided paired sign-flip permutation test",
        "permutations": permutations,
        "p_value": p_value,
        "seed": seed,
        "normality_pretest_used": False,
    }


def run_benchmark(
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    warmup_rounds: int = DEFAULT_WARMUP_ROUNDS,
    repetitions: int = DEFAULT_REPETITIONS,
    timer_overhead_samples: int = DEFAULT_TIMER_OVERHEAD_SAMPLES,
    permutations: int = DEFAULT_PERMUTATIONS,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    command_line: list[str] | None = None,
) -> dict[str, Path]:
    freeze = verify_freeze()
    destination = Path(output_dir)
    if destination.exists() and any(destination.iterdir()):
        raise ConfigurationError(f"latency output directory is not empty: {destination}")
    matrix = load_policy_matrix(INPUT_DIR / "policy_matrix.yaml")
    scenarios = load_final_scenarios(INPUT_DIR / "scenarios.yaml")
    comparator = ContextAwareABACEngine.from_files(matrix)
    risk = RiskEngine.from_policy_matrix(matrix)
    _warm_up(scenarios, comparator, risk, warmup_rounds)

    gc_was_enabled = gc.isenabled()
    try:
        gc.disable()
        overhead = measure_timer_overhead(timer_overhead_samples)
        raw_rows = collect_raw_measurements(
            scenarios,
            comparator,
            risk,
            repetitions=repetitions,
            seed=BENCHMARK_SEED,
        )
    finally:
        if gc_was_enabled:
            gc.enable()

    raw = pd.DataFrame(raw_rows)
    scenario_summary = aggregate_scenarios(raw)
    inference = paired_permutation_and_cluster_interval(
        scenario_summary,
        permutations=permutations,
        bootstrap_replicates=bootstrap_replicates,
    )
    destination.mkdir(parents=True, exist_ok=True)
    paths = {
        "raw_repetitions": destination / "raw_repetitions.csv",
        "timer_overhead": destination / "timer_overhead.csv",
        "scenario_summary": destination / "scenario_summary.csv",
        "paired_inference": destination / "paired_inference.json",
    }
    raw.to_csv(paths["raw_repetitions"], index=False)
    pd.DataFrame({"timer_overhead_ns": overhead}).to_csv(
        paths["timer_overhead"], index=False
    )
    scenario_summary.to_csv(paths["scenario_summary"], index=False)
    paths["paired_inference"].write_text(
        json.dumps(inference, indent=2) + "\n", encoding="utf-8"
    )
    verify_freeze()
    manifest_path = destination / "benchmark_manifest.json"
    manifest = {
        "experiment": "confirmatory latency microbenchmark",
        "environment": environment_metadata(command_line),
        "input_hashes": freeze["required_inputs"],
        "source_tree_sha256": freeze["source_tree_sha256"],
        "benchmark": {
            "warmup_rounds": warmup_rounds,
            "repetitions_per_scenario_per_method": repetitions,
            "randomized_task_schedule": True,
            "counterbalanced_within_pair_order": True,
            "timer": "time.perf_counter_ns",
            "timer_overhead_samples": timer_overhead_samples,
            "timer_overhead_subtracted": False,
            "gc_policy": "disabled during timer-overhead and timed repetitions; prior state restored afterward",
            "seed": BENCHMARK_SEED,
            "analysis_unit": "scenario-level median of raw repetitions",
            "normality_pretest_used": False,
        },
        "outputs": output_hashes(paths),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return paths | {"manifest": manifest_path}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Confirmatory authorization latency microbenchmark")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--warmup-rounds", type=int, default=DEFAULT_WARMUP_ROUNDS)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    args = parser.parse_args(argv)
    try:
        verify_freeze()
        if not args.execute:
            print("Confirmatory freeze verified. No latency benchmark was run.")
            return 0
        paths = run_benchmark(
            args.output_dir,
            warmup_rounds=args.warmup_rounds,
            repetitions=args.repetitions,
            command_line=["python", "-m", "confirmatory.latency_benchmark", "--execute"],
        )
    except ConfigurationError as exc:
        print(f"latency benchmark refused: {exc}", file=sys.stderr)
        return 2
    for name, path in paths.items():
        print(f"{name}: {repository_relative(path)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
