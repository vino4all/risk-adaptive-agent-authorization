"""Write an independent authorization replay outside the preserved repository."""

from __future__ import annotations

import argparse
from pathlib import Path

from confirmatory.analysis import escalation_resolution, primary_paired_tests, summary_metrics
from confirmatory.provenance import REPOSITORY_ROOT, verify_freeze
from confirmatory.runner import evaluate
from src.models import ConfigurationError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", help="new, empty directory outside this repository")
    args = parser.parse_args()
    destination = Path(args.output_dir).resolve()
    root = REPOSITORY_ROOT.resolve()
    if destination == root or root in destination.parents:
        parser.error("output directory must be outside the repository")
    if destination.exists() and any(destination.iterdir()):
        parser.error("output directory must be empty")
    try:
        verify_freeze(require_empty_authorization=False)
        decisions = evaluate()
    except ConfigurationError as exc:
        parser.error(str(exc))
    destination.mkdir(parents=True, exist_ok=True)
    decisions.to_csv(destination / "decisions.csv", index=False)
    summary_metrics(decisions).to_csv(destination / "summary_metrics.csv", index=False)
    primary_paired_tests(decisions).to_csv(destination / "primary_statistical_tests.csv", index=False)
    escalation_resolution(decisions).to_csv(destination / "escalation_analysis.csv", index=False)
    print(f"Independent replay written to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
