"""Freeze verification and portable confirmatory provenance metadata."""

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
from typing import Any, Iterable, Mapping

from src.models import ConfigurationError
from src.policy import load_policy_matrix, load_yaml_mapping

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
CONFIRMATORY_ROOT = Path(__file__).resolve().parent
FREEZE_V1_MANIFEST_PATH = CONFIRMATORY_ROOT / "freeze_manifest.json"
FREEZE_MANIFEST_PATH = CONFIRMATORY_ROOT / "freeze_manifest_v2.json"
RESEARCH_SOURCE_MANIFEST_PATH = CONFIRMATORY_ROOT / "research_source_manifest_v2.json"
AUTHORIZATION_RESULTS_DIR = CONFIRMATORY_ROOT / "results" / "authorization"
RESEARCH_SOURCE_HASH_ALGORITHM = (
    "sha256(concat(u64be(len(utf8_posix_relative_path)), "
    "utf8_posix_relative_path, raw_sha256_file_digest)) for paths in lexical order"
)
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
EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
}
EXCLUDED_RELATIVE_PREFIXES = (
    "confirmatory/results/",
    "confirmatory/reviewer_returns/",
    "confirmatory/release_bundle/",
)
EXCLUDED_RELATIVE_FILES = {
    ".env",
    "confirmatory/freeze_manifest.json",
}


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _included_source_files(root: Path = REPOSITORY_ROOT) -> Iterable[Path]:
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in EXCLUDED_RELATIVE_FILES:
            continue
        if any(part in EXCLUDED_DIRECTORY_NAMES for part in path.relative_to(root).parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        if any(relative.startswith(prefix) for prefix in EXCLUDED_RELATIVE_PREFIXES):
            continue
        yield path


def source_tree_hash(root: Path = REPOSITORY_ROOT) -> str:
    """Reproduce the historical, repository-wide Freeze v1 hash."""
    digest = hashlib.sha256()
    for path in _included_source_files(root):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        content_hash = bytes.fromhex(sha256_file(path))
        digest.update(content_hash)
    return digest.hexdigest()


def _repository_file(relative: str, root: Path = REPOSITORY_ROOT) -> Path:
    candidate = Path(relative)
    if (
        not relative
        or candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.as_posix() != relative
    ):
        raise ConfigurationError(f"invalid research-source path: {relative!r}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ConfigurationError(
            f"research-source path escapes repository: {relative}"
        ) from exc
    if not resolved.is_file():
        raise ConfigurationError(f"research-source file is missing: {relative}")
    return resolved


def aggregate_research_source_hash(
    relative_paths: Iterable[str], root: Path = REPOSITORY_ROOT
) -> str:
    """Hash an explicit ordered research-source allowlist."""
    paths = list(relative_paths)
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ConfigurationError(
            "research-source paths must be unique and in lexical order"
        )
    digest = hashlib.sha256()
    for relative in paths:
        path_bytes = relative.encode("utf-8")
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        digest.update(bytes.fromhex(sha256_file(_repository_file(relative, root))))
    return digest.hexdigest()


def load_research_source_manifest(
    path: str | Path = RESEARCH_SOURCE_MANIFEST_PATH,
) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.is_file():
        raise ConfigurationError(
            f"research-source manifest is missing: {resolved}"
        )
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigurationError("research-source manifest must be a JSON object")
    return data


def verify_research_source_manifest(
    manifest_path: str | Path = RESEARCH_SOURCE_MANIFEST_PATH,
) -> dict[str, Any]:
    manifest = load_research_source_manifest(manifest_path)
    if manifest.get("allowlist_version") != "research-source-v2.0.0":
        raise ConfigurationError("unsupported research-source allowlist version")
    if manifest.get("hashing_algorithm") != RESEARCH_SOURCE_HASH_ALGORITHM:
        raise ConfigurationError("research-source hashing algorithm differs from v2")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ConfigurationError("research-source manifest has no files")
    paths: list[str] = []
    for entry in files:
        if not isinstance(entry, Mapping):
            raise ConfigurationError("research-source file entry must be an object")
        relative = entry.get("path")
        expected_hash = entry.get("sha256")
        expected_size = entry.get("size_bytes")
        if not isinstance(relative, str):
            raise ConfigurationError("research-source file entry has no valid path")
        resolved = _repository_file(relative)
        actual_hash = sha256_file(resolved)
        actual_size = resolved.stat().st_size
        if expected_hash != actual_hash:
            raise ConfigurationError(
                f"research-source hash mismatch for {relative}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
        if expected_size != actual_size:
            raise ConfigurationError(
                f"research-source size mismatch for {relative}: "
                f"expected {expected_size}, got {actual_size}"
            )
        paths.append(relative)
    aggregate = aggregate_research_source_hash(paths)
    if manifest.get("aggregate_research_source_sha256") != aggregate:
        raise ConfigurationError("aggregate research-source hash mismatch")
    return manifest


def load_freeze_manifest(path: str | Path = FREEZE_MANIFEST_PATH) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.is_file():
        raise ConfigurationError(f"confirmatory freeze manifest is missing: {resolved}")
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigurationError("confirmatory freeze manifest must be a JSON object")
    return data


def verify_freeze(
    path: str | Path = FREEZE_MANIFEST_PATH,
    *,
    verify_source: bool = True,
    require_empty_authorization: bool = False,
) -> dict[str, Any]:
    manifest = load_freeze_manifest(path)
    if manifest.get("protocol_version") != "v2":
        raise ConfigurationError("confirmatory execution requires Freeze v2")
    required = manifest.get("required_inputs")
    if not isinstance(required, Mapping) or not required:
        raise ConfigurationError("freeze manifest has no required_inputs")
    for relative, expected in required.items():
        resolved = REPOSITORY_ROOT / str(relative)
        if not resolved.is_file():
            raise ConfigurationError(f"frozen input is missing: {relative}")
        actual = sha256_file(resolved)
        if actual != expected:
            raise ConfigurationError(
                f"frozen input hash mismatch for {relative}: expected {expected}, got {actual}"
            )
    matrix = load_policy_matrix(CONFIRMATORY_ROOT / "inputs" / "policy_matrix.yaml")
    if not matrix.locked_for_primary_experiment:
        raise ConfigurationError(
            "confirmatory policy requires locked_for_primary_experiment=true"
        )
    comparator = load_yaml_mapping(CONFIRMATORY_ROOT / "inputs" / "context_aware_abac.yaml")
    comparator_meta = comparator.get("_meta")
    if not isinstance(comparator_meta, Mapping) or comparator_meta.get("locked") is not True:
        raise ConfigurationError("confirmatory comparator requires locked=true")
    expected_lock = manifest.get("dependency_lock_sha256")
    actual_lock = sha256_file(REPOSITORY_ROOT / "requirements.lock")
    if not expected_lock or actual_lock != expected_lock:
        raise ConfigurationError(
            f"dependency lock hash mismatch: expected {expected_lock}, got {actual_lock}"
        )
    if verify_source:
        expected_manifest_hash = manifest.get("research_source_manifest_sha256")
        actual_manifest_hash = sha256_file(RESEARCH_SOURCE_MANIFEST_PATH)
        if not expected_manifest_hash or actual_manifest_hash != expected_manifest_hash:
            raise ConfigurationError(
                "research-source manifest hash mismatch; Freeze v2 verification refused"
            )
        source_manifest = verify_research_source_manifest()
        expected_source = manifest.get("aggregate_research_source_sha256")
        actual_source = source_manifest.get("aggregate_research_source_sha256")
        if not expected_source or actual_source != expected_source:
            raise ConfigurationError("Freeze v2 aggregate research-source hash mismatch")
        if manifest.get("research_source_allowlist_version") != source_manifest.get(
            "allowlist_version"
        ):
            raise ConfigurationError("Freeze v2 allowlist version mismatch")
    if require_empty_authorization and AUTHORIZATION_RESULTS_DIR.exists():
        if any(AUTHORIZATION_RESULTS_DIR.iterdir()):
            raise ConfigurationError(
                "confirmatory authorization output directory is not empty"
            )
    return manifest


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def environment_metadata(command_line: list[str] | None = None) -> dict[str, Any]:
    packages: dict[str, str | None] = {}
    for name in PACKAGE_NAMES:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command_line": list(command_line if command_line is not None else sys.argv),
        "source": {
            "git_commit": _git_commit(),
            "freeze_protocol": "v2",
            "research_source_manifest_sha256": sha256_file(
                RESEARCH_SOURCE_MANIFEST_PATH
            ),
            "aggregate_research_source_sha256": verify_research_source_manifest()[
                "aggregate_research_source_sha256"
            ],
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable_name": Path(sys.executable).name,
        },
        "platform": {
            "os": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "cpu": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
        },
        "packages": packages,
    }


def repository_relative(path: str | Path) -> str:
    return Path(path).resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()


def output_hashes(paths: Mapping[str, Path]) -> dict[str, dict[str, str]]:
    return {
        name: {"path": repository_relative(path), "sha256": sha256_file(path)}
        for name, path in paths.items()
    }
