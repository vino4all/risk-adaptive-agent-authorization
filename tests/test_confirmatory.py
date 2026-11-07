"""Publication-grade confirmatory path and exploratory-preservation tests."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

from confirmatory.analysis import primary_paired_tests, summary_metrics
from confirmatory.comparator import ContextAwareABACEngine
from confirmatory.latency_benchmark import (
    aggregate_scenarios,
    collect_raw_measurements,
    paired_permutation_and_cluster_interval,
)
from confirmatory.provenance import (
    CONFIRMATORY_ROOT,
    FREEZE_V1_MANIFEST_PATH,
    REPOSITORY_ROOT,
    RESEARCH_SOURCE_MANIFEST_PATH,
    sha256_file,
    verify_freeze,
    verify_research_source_manifest,
)
from confirmatory.release import publication_files
from src.models import ContextRisk, Decision, Destination, Role, Scenario, Sensitivity, Tool
from src.policy import load_policy_matrix


PROTECTED_HASHES = {
    "data/policy_matrix.yaml": "4de9edee5652eaac56dc83a36e35be2cd20b89ab79aa7a290c5b2d8b870954c5",
    "data/scenarios.yaml": "d87d651a3dbf5d0dee367e1b7b81a1654173211284176b38d42cf412b7511ad4",
    "data/risk_config.yaml": "e78205f2c111b038ad835af1752061932597330e8adafab0a1a4d06609968f4d",
    "results/exploratory/decisions.csv": "0d92ecc3a48367ce8efe8976384b2a570de586d487747678dd9f7de5cbf909d3",
    "results/exploratory/summary_metrics.csv": "319eef859a5ae006b39af4b3415409500bcfd15e4166ed476a054c503eed1a5b",
    "results/exploratory/escalation_analysis.csv": "fcc2d9314a6491de49c0fd5908e9510a6fe6a3e4bb5f4df1eb8f2eff9628443c",
    "results/exploratory/statistical_tests.csv": "35f9f676e13b36db91e3fa85ef33377ebcdf2210d05bcd0f8d8b0566854bbfc8",
    "results/exploratory/latency_summary.csv": "91aa07f79c34d2ec826e599c7a1efd635d72f1af79d27fd2c461f5f659732bc5",
    "results/exploratory/threshold_sensitivity.csv": "1cd3e01a1ed3e5fbbff6c7b112c51cfb6ab7755725dd667df7b8067f7f419289",
    "results/exploratory/threshold_sensitivity.png": "ca0884e6e4d4ce244d4c289c707ca28c5132eee49118e69124086a9b45e0dfe5",
}


def make_scenario(context: ContextRisk = ContextRisk.NORMAL) -> Scenario:
    return Scenario(
        scenario_id=f"C-{context.value}",
        role=Role.ANALYST,
        tool=Tool.READ_RECORD,
        sensitivity=Sensitivity.INTERNAL,
        destination=Destination.INTERNAL,
        context_risk=context,
        ground_truth=Decision.ALLOW if context is ContextRisk.NORMAL else Decision.ESCALATE,
    )


class FastStub:
    def __init__(self, decision: Decision) -> None:
        self.decision = decision

    def authorize(self, scenario):  # noqa: ANN001
        class Outcome:
            pass

        result = Outcome()
        result.decision = self.decision
        return result


def test_exploratory_inputs_and_results_are_byte_for_byte_preserved() -> None:
    assert {
        relative: sha256_file(REPOSITORY_ROOT / relative)
        for relative in PROTECTED_HASHES
    } == PROTECTED_HASHES


def test_confirmatory_freeze_and_locked_policy_verify() -> None:
    # Public snapshots retain the completed results; execution still requires an empty destination.
    manifest = verify_freeze(require_empty_authorization=False)
    assert manifest["protocol_version"] == "v2"
    assert manifest["status"] == "frozen-before-confirmatory-execution"
    assert manifest["required_inputs"]
    assert FREEZE_V1_MANIFEST_PATH.is_file()
    matrix = load_policy_matrix(CONFIRMATORY_ROOT / "inputs" / "policy_matrix.yaml")
    assert matrix.locked_for_primary_experiment is True


def test_v2_research_source_manifest_verifies_exact_allowlist() -> None:
    manifest = verify_research_source_manifest()
    paths = [entry["path"] for entry in manifest["files"]]
    assert len(paths) == 19
    assert paths == sorted(paths)
    assert "src/__init__.py" in paths
    assert "confirmatory/__init__.py" in paths
    assert sha256_file(RESEARCH_SOURCE_MANIFEST_PATH)


def test_context_aware_comparator_uses_context_and_is_binary_scoreless() -> None:
    matrix = load_policy_matrix(CONFIRMATORY_ROOT / "inputs" / "policy_matrix.yaml")
    engine = ContextAwareABACEngine.from_files(matrix)
    normal = engine.authorize(make_scenario(ContextRisk.NORMAL))
    anomalous = engine.authorize(make_scenario(ContextRisk.ANOMALOUS))
    assert normal.decision is Decision.ALLOW
    assert anomalous.decision is Decision.DENY
    assert normal.score is None and anomalous.score is None
    assert normal.details["observed_attributes"] == [
        "role",
        "tool",
        "sensitivity",
        "destination",
        "context_risk",
    ]
    assert normal.details["numerical_risk_formula_used"] is False


def test_context_aware_comparator_never_emits_escalate_over_full_domain() -> None:
    engine = ContextAwareABACEngine.from_files(
        load_policy_matrix(CONFIRMATORY_ROOT / "inputs" / "policy_matrix.yaml")
    )
    decisions = {
        engine.authorize(
            Scenario(
                scenario_id="DOMAIN",
                role=role,
                tool=tool,
                sensitivity=sensitivity,
                destination=destination,
                context_risk=context,
            )
        ).decision
        for role in Role
        for tool in Tool
        for sensitivity in Sensitivity
        for destination in Destination
        for context in ContextRisk
    }
    assert decisions <= {Decision.ALLOW, Decision.DENY}


def test_confirmatory_statistics_limit_inference_and_apply_holm() -> None:
    decisions = pd.DataFrame(
        {
            "ground_truth": ["DENY", "DENY", "ALLOW", "ALLOW", "ESCALATE", "ESCALATE"],
            "context_abac_decision": ["DENY", "DENY", "ALLOW", "ALLOW", "DENY", "DENY"],
            "risk_adaptive_decision": ["ALLOW", "DENY", "ALLOW", "ESCALATE", "ESCALATE", "DENY"],
        }
    )
    metrics = summary_metrics(decisions)
    tests = primary_paired_tests(decisions)
    assert set(tests["metric"]) == {"UER", "LDCR"}
    assert tests["holm_adjusted_p_value"].notna().all()
    assert (tests["holm_adjusted_p_value"] >= tests["raw_p_value"]).all()
    assert set(metrics.loc[metrics["metric"].isin(["OER", "CER"]), "analysis_role"]) == {
        "descriptive_structural"
    }
    assert metrics["ci_method"].str.contains("empirical scenario-resampling").all()
    assert metrics["generalization_scope"].str.contains("purposive").all()


def test_latency_schedule_is_randomized_and_exactly_counterbalanced() -> None:
    scenarios = [make_scenario(), make_scenario(ContextRisk.ANOMALOUS)]
    raw = pd.DataFrame(
        collect_raw_measurements(
            scenarios,
            FastStub(Decision.DENY),
            FastStub(Decision.ESCALATE),
            repetitions=4,
            seed=9,
        )
    )
    assert len(raw) == 2 * 4 * 2
    for scenario_id in raw["scenario_id"].unique():
        first = raw[(raw["scenario_id"] == scenario_id) & (raw["order_position"] == 1)]
        assert Counter(first["method"]) == {
            "context_aware_binary_abac": 2,
            "risk_adaptive": 2,
        }
    summary = aggregate_scenarios(raw)
    inference = paired_permutation_and_cluster_interval(
        summary, permutations=100, bootstrap_replicates=100, seed=7
    )
    assert len(summary) == 2
    assert inference["normality_pretest_used"] is False
    assert inference["test"] == "two-sided paired sign-flip permutation test"


def test_latency_implementation_has_no_shapiro_based_selection() -> None:
    source = (CONFIRMATORY_ROOT / "latency_benchmark.py").read_text(encoding="utf-8")
    assert "shapiro" not in source.lower()


def test_reviewer_export_contains_only_blinded_sample() -> None:
    export = CONFIRMATORY_ROOT / "reviewer_export"
    assert {path.name for path in export.iterdir()} == {"reviewer_sample.csv"}
    sample = pd.read_csv(export / "reviewer_sample.csv", dtype=str, keep_default_na=False)
    assert len(sample) == 60
    assert (sample["reviewer_label"] == "").all()
    forbidden = {
        "ground_truth",
        "risk_score",
        "T1",
        "T2",
        "ABAC_result",
        "risk_adaptive_result",
    }
    assert forbidden.isdisjoint(sample.columns)


def test_release_allowlist_excludes_secrets_keys_and_caches() -> None:
    relative = {path.relative_to(REPOSITORY_ROOT).as_posix() for path in publication_files()}
    assert ".env" not in relative
    assert not any(path.startswith(".env") for path in relative)
    assert "data/reviewer_sample_key.csv" not in relative
    assert "confirmatory/results/reviewer_disagreements.csv" not in relative
    assert "confirmatory/results/reviewer_robustness/human_majority_labels.csv" not in relative
    assert "confirmatory/results/reviewer_robustness/deny_boundary_analysis.csv" not in relative
    assert not any("__pycache__" in path or path.endswith(".pyc") for path in relative)


def test_new_manifest_code_uses_relative_paths() -> None:
    runner = (CONFIRMATORY_ROOT / "runner.py").read_text(encoding="utf-8")
    benchmark = (CONFIRMATORY_ROOT / "latency_benchmark.py").read_text(encoding="utf-8")
    assert "output_hashes(outputs)" in runner
    assert "output_hashes(paths)" in benchmark
    assert "repository_relative" in runner and "repository_relative" in benchmark


def test_dependency_lock_is_exact_and_contains_tested_core_stack() -> None:
    lines = [
        line.strip()
        for line in (REPOSITORY_ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert all("==" in line for line in lines)
    assert {line.split("==", 1)[0] for line in lines} == {
        "PyYAML",
        "pandas",
        "numpy",
        "matplotlib",
        "scipy",
        "pytest",
    }
