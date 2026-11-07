"""Recover provenance after latency outputs completed but manifest creation failed.

This utility only reads existing outputs and frozen provenance. It never imports
or executes authorization, timing, or statistical-analysis code.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "confirmatory" / "results" / "latency"
FREEZE_PATH = ROOT / "confirmatory" / "freeze_manifest_v2.json"
SOURCE_MANIFEST_PATH = ROOT / "confirmatory" / "research_source_manifest_v2.json"
DEPENDENCY_LOCK_PATH = ROOT / "requirements.lock"
RECOVERED_MANIFEST_PATH = OUTPUT_DIR / "benchmark_manifest_recovered.json"
OUTPUTS = (
    "raw_repetitions.csv",
    "scenario_summary.csv",
    "timer_overhead.csv",
    "paired_inference.json",
)
VALIDATED_OUTPUT_HASHES = {
    "raw_repetitions.csv": "6e557d4ec289a8debf044daac3dd1bf541229f4c01b597efea42e54d2c86cfa9",
    "scenario_summary.csv": "5ff058366ea929249a875a13eadd3cbd5dfbd4db4612bc8f2529a838852cbfd4",
    "timer_overhead.csv": "38d77fe7a3972fed31b96169d35d68bd885e3b9a9d69fc4d71b9befad0a52ef7",
    "paired_inference.json": "6c8c27e67e782b70925c1920c6ec7a30c6af4e9a7392b12007665ab7d9e0062c",
}
PACKAGE_NAMES = (
    "PyYAML",
    "pandas",
    "numpy",
    "matplotlib",
    "scipy",
    "statsmodels",
    "pytest",
    "google-genai",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def git_commit_at_recovery() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in PACKAGE_NAMES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def build_recovery_manifest() -> dict[str, Any]:
    if RECOVERED_MANIFEST_PATH.exists():
        raise FileExistsError(f"refusing to overwrite {RECOVERED_MANIFEST_PATH}")

    missing = [name for name in OUTPUTS if not (OUTPUT_DIR / name).is_file()]
    if missing:
        raise FileNotFoundError(f"expected completed latency outputs are missing: {missing}")

    output_hashes: dict[str, dict[str, str]] = {}
    for name in OUTPUTS:
        path = OUTPUT_DIR / name
        digest = sha256_file(path)
        if digest != VALIDATED_OUTPUT_HASHES[name]:
            raise ValueError(
                f"validated output changed before recovery: {name} "
                f"(expected {VALIDATED_OUTPUT_HASHES[name]}, got {digest})"
            )
        output_hashes[name] = {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": digest,
        }

    freeze = read_json(FREEZE_PATH)
    source_manifest = read_json(SOURCE_MANIFEST_PATH)
    freeze_protocol = freeze.get("protocol_version")
    source_manifest_hash = sha256_file(SOURCE_MANIFEST_PATH)
    aggregate_source_hash = freeze.get("aggregate_research_source_sha256")
    dependency_lock_hash = sha256_file(DEPENDENCY_LOCK_PATH)
    if freeze_protocol != "v2":
        raise ValueError(f"expected Freeze v2, found {freeze_protocol!r}")
    if source_manifest_hash != freeze.get("research_source_manifest_sha256"):
        raise ValueError("research-source manifest hash does not match Freeze v2")
    if aggregate_source_hash != source_manifest.get("aggregate_research_source_sha256"):
        raise ValueError("aggregate research-source hash does not match Freeze v2")
    if dependency_lock_hash != freeze.get("dependency_lock_sha256"):
        raise ValueError("dependency lock hash does not match Freeze v2")

    script_hash = sha256_file(Path(__file__).resolve())
    return {
        "status": "recovered-after-manifest-generation-failure",
        "experiment": "confirmatory latency microbenchmark",
        "original_benchmark_command": [
            "python",
            "-m",
            "confirmatory.latency_benchmark",
            "--execute",
        ],
        "original_failure": {
            "type": "KeyError: source_tree_sha256",
            "failure_point": (
                "confirmatory/latency_benchmark.py, run_benchmark, while "
                "constructing benchmark_manifest.json"
            ),
        },
        "completion_statements": {
            "measurements_and_paired_inference_completed_before_failure": True,
            "latency_benchmark_was_not_rerun": True,
            "measurements_modified": False,
            "inference_recomputed": False,
            "benchmark_rerun": False,
        },
        "original_benchmark_timestamp_utc": None,
        "original_benchmark_timestamp_availability": "unavailable; not persisted",
        "recovery_timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "freeze_protocol_version": freeze_protocol,
        "provenance": {
            "git_commit": freeze.get("git_commit"),
            "git_commit_at_recovery": git_commit_at_recovery(),
            "research_source_manifest_sha256": source_manifest_hash,
            "aggregate_research_source_sha256": aggregate_source_hash,
            "dependency_lock_sha256": dependency_lock_hash,
        },
        "environment_at_recovery": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "os": platform.platform(),
            "os_system": platform.system(),
            "os_release": platform.release(),
            "machine": platform.machine(),
            "cpu": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
            "package_versions": package_versions(),
        },
        "benchmark_parameters": {
            "warmup_rounds": 20,
            "repetitions_per_scenario_per_method": 200,
            "timer_overhead_samples": 10000,
            "permutations": 100000,
            "bootstrap_replicates": 10000,
            "random_seed": 20261018,
            "timer": "time.perf_counter_ns",
            "timer_overhead_subtracted": False,
        },
        "outputs": output_hashes,
        "recovery_script": {
            "path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
            "sha256": script_hash,
        },
    }


def main() -> int:
    manifest = build_recovery_manifest()
    RECOVERED_MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(RECOVERED_MANIFEST_PATH.relative_to(ROOT).as_posix())
    print(f"sha256: {sha256_file(RECOVERED_MANIFEST_PATH)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())