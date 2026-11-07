"""Recompute de-identified, post-confirmatory reviewer agreement summaries.

This read-only entry point uses the published labels, not private return files.
It does not rerun authorization or replace the frozen policy ground truth.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "confirmatory/results/reviewer_robustness/deidentified_reviewer_labels.csv"
LABELS = ("ALLOW", "ESCALATE", "DENY")
REVIEWERS = ("reviewer_1_label", "reviewer_2_label", "reviewer_3_label")
FIELDS = (
    "reviewer_scenario_id", "frozen_scenario_id", "policy_label",
    *REVIEWERS, "human_majority_label", "majority_strength", "unanimous",
)


def read_labels(path: Path = INPUT) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream, strict=True)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("unexpected public reviewer-label columns")
        rows = list(reader)
    if len(rows) != 60 or any(None in row or None in row.values() for row in rows):
        raise ValueError("expected 60 complete reviewer-label rows")
    if len({row["reviewer_scenario_id"] for row in rows}) != 60:
        raise ValueError("reviewer scenario IDs must be unique")
    if len({row["frozen_scenario_id"] for row in rows}) != 60:
        raise ValueError("frozen scenario IDs must be unique")
    for row in rows:
        if any(row[key] not in LABELS for key in ("policy_label", *REVIEWERS)):
            raise ValueError("unexpected policy or reviewer label")
        counts = Counter(row[key] for key in REVIEWERS)
        strength = max(counts.values())
        expected = next((label for label, count in counts.items() if count == strength), None) if strength >= 2 else "NO_CONSENSUS"
        if row["human_majority_label"] != expected:
            raise ValueError("majority label does not match reviewer votes")
        if row["majority_strength"] != str(strength if strength >= 2 else 0):
            raise ValueError("majority strength does not match reviewer votes")
        if row["unanimous"].lower() != str(strength == 3).lower():
            raise ValueError("unanimous flag does not match reviewer votes")
    return rows


def confusion(left: list[str], right: list[str]) -> list[list[int]]:
    return [[sum(a == source and b == target for a, b in zip(left, right, strict=True))
             for target in LABELS] for source in LABELS]


def cohen_kappa(counts: list[list[int]]) -> float:
    n = sum(map(sum, counts))
    observed = sum(counts[i][i] for i in range(3)) / n
    expected = sum(sum(counts[i]) * sum(counts[j][i] for j in range(3)) for i in range(3)) / n**2
    return (observed - expected) / (1 - expected)


def fleiss_kappa(votes: list[list[str]]) -> float:
    n, raters = len(votes), len(votes[0])
    counts = [[case.count(label) for label in LABELS] for case in votes]
    observed = sum(sum(value * (value - 1) for value in case) / (raters * (raters - 1)) for case in counts) / n
    marginals = [sum(case[j] for case in counts) / (n * raters) for j in range(3)]
    chance = sum(value**2 for value in marginals)
    return (observed - chance) / (1 - chance)


def nominal_alpha(votes: list[list[str]]) -> float:
    n, raters = len(votes), len(votes[0])
    total = n * raters
    observed = sum(sum(a != b for a in case for b in case) for case in votes) / (n * raters * (raters - 1))
    marginals = Counter(label for case in votes for label in case)
    expected = sum(marginals[label] * (total - marginals[label]) for label in LABELS) / (total * (total - 1))
    return 1 - observed / expected


def summarize(rows: list[dict[str, str]]) -> dict:
    votes = [[row[key] for key in REVIEWERS] for row in rows]
    labels = {"Policy": [row["policy_label"] for row in rows]}
    labels.update({f"Reviewer {index}": [row[key] for row in rows] for index, key in enumerate(REVIEWERS, 1)})
    pairs = {}
    for left, right in combinations(labels, 2):
        matrix = confusion(labels[left], labels[right])
        pairs[f"{left} vs {right}"] = {
            "exact_agreement": sum(matrix[i][i] for i in range(3)),
            "cohens_kappa": cohen_kappa(matrix),
            "confusion": matrix,
        }
    strength = Counter(row["majority_strength"] for row in rows)
    consensus = [row for row in rows if row["human_majority_label"] != "NO_CONSENSUS"]
    deny = [row for row in rows if row["policy_label"] == "DENY"]
    return {
        "pairwise": pairs,
        "fleiss_kappa": fleiss_kappa(votes),
        "krippendorff_alpha_nominal": nominal_alpha(votes),
        "unanimous_count": strength["3"],
        "exactly_two_of_three_count": strength["2"],
        "complete_disagreement_count": strength["0"],
        "consensus_count": len(consensus),
        "policy_vs_majority_agreement": sum(row["policy_label"] == row["human_majority_label"] for row in consensus),
        "policy_deny_count": len(deny),
        "policy_deny_vote_distribution": {
            str(count): sum(sum(row[key] == "DENY" for key in REVIEWERS) == count for row in deny)
            for count in (3, 2, 1, 0)
        },
        "policy_deny_majority_distribution": {
            label: sum(row["human_majority_label"] == label for row in deny)
            for label in (*LABELS, "NO_CONSENSUS")
        },
    }


def main() -> None:
    print(json.dumps(summarize(read_labels()), indent=2))


if __name__ == "__main__":
    main()
