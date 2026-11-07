"""Build a sanitized publication bundle without mutating repository artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Sequence

from confirmatory.provenance import REPOSITORY_ROOT, sha256_file, source_tree_hash
from src.models import ConfigurationError

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    ".venv",
    "venv",
    "build",
    "dist",
    "release_bundle",
    "reviewer_returns",
}
EXCLUDED_FILES = {
    ".env",
    "data/reviewer_sample_key.csv",
    "data/reviewer_sample_manifest.json",
    "confirmatory/results/reviewer_disagreements.csv",
    "SECOND_REVIEWER_ROBUSTNESS.md",
    "confirmatory/results/reviewer_robustness/human_majority_labels.csv",
    "confirmatory/results/reviewer_robustness/deny_boundary_analysis.csv",
    "PAPER_WRITING_PLAN.md",
    "PROJECT_STATUS_SUMMARY.md",
    "REPOSITORY_AUDIT.md",
    "EXPERIMENT_AUDIT.md",
    "INDEPENDENT_REVIEW_READINESS.md",
    "PAPER_READINESS_AUDIT.md",
    "IMPLEMENTATION_REPORT.md",
    "RELEASE_CHECKLIST.md",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def publication_files(root: Path = REPOSITORY_ROOT) -> tuple[Path, ...]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        relative_text = relative.as_posix()
        if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts):
            continue
        if relative_text in EXCLUDED_FILES:
            continue
        if path.name.startswith(".env"):
            continue
        if path.suffix in {".log", ".tmp", ".bak", ".zip"}:
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        files.append(path)
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def _sanitize_exploratory_manifest(destination: Path) -> None:
    path = destination / "results" / "evaluation_manifest.json"
    if not path.is_file():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    outputs = manifest.get("outputs") or {}
    if isinstance(outputs, dict):
        manifest["outputs"] = {
            name: f"results/{Path(str(value)).name}" for name, value in outputs.items()
        }
    manifest["release_copy_note"] = (
        "Absolute local paths were replaced with repository-relative paths in "
        "this release copy; preserved exploratory measurements are unchanged."
    )
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def build_release(destination: str | Path) -> Path:
    target = Path(destination).resolve()
    root = REPOSITORY_ROOT.resolve()
    if target == root or root in target.parents:
        raise ConfigurationError("release destination must be outside the repository")
    if target.exists() and any(target.iterdir()):
        raise ConfigurationError("release destination must be empty")
    target.mkdir(parents=True, exist_ok=True)
    for source in publication_files(root):
        relative = source.relative_to(root)
        output = target / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output)
    _sanitize_exploratory_manifest(target)

    forbidden = [
        path
        for path in target.rglob("*")
        if path.is_file()
        and (
            path.name == ".env"
            or path.suffix in EXCLUDED_SUFFIXES
            or "__pycache__" in path.parts
            or ".pytest_cache" in path.parts
            or path.name == "reviewer_sample_key.csv"
            or path.name == "reviewer_disagreements.csv"
            or path.name in {"human_majority_labels.csv", "deny_boundary_analysis.csv"}
        )
    ]
    if forbidden:
        raise ConfigurationError(
            "release hygiene check failed: "
            + ", ".join(path.relative_to(target).as_posix() for path in forbidden)
        )
    manifest_rows = [
        {
            "path": path.relative_to(target).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in sorted(target.rglob("*"))
        if path.is_file()
    ]
    release_manifest = {
        "source_tree_sha256": source_tree_hash(root),
        "file_count": len(manifest_rows),
        "files": manifest_rows,
        "excluded": [
            ".env and .env.*",
            "reviewer crosswalk and class-count manifest",
            "private reviewer returns",
            "Python/test caches and bytecode",
            "virtual environments and build products",
        ],
    }
    (target / "RELEASE_MANIFEST.json").write_text(
        json.dumps(release_manifest, indent=2) + "\n", encoding="utf-8"
    )
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build sanitized publication bundle")
    parser.add_argument("destination")
    args = parser.parse_args(argv)
    try:
        target = build_release(args.destination)
    except ConfigurationError as exc:
        print(f"release build refused: {exc}", file=sys.stderr)
        return 2
    print(f"release bundle written: {target}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
