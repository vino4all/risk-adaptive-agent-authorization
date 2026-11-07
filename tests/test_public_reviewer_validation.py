"""Published de-identified labels reproduce recorded reviewer summaries."""

from __future__ import annotations

import csv
import json

import pytest

from analysis.public_reviewer_validation import INPUT, read_labels, summarize


def test_public_labels_reproduce_aggregate_results() -> None:
    result = summarize(read_labels())
    recorded = json.loads((INPUT.parent / "human_multirater_agreement.json").read_text(encoding="utf-8"))
    assert result["fleiss_kappa"] == pytest.approx(recorded["fleiss_kappa"])
    assert result["krippendorff_alpha_nominal"] == pytest.approx(recorded["krippendorff_alpha_nominal"])
    assert (result["unanimous_count"], result["exactly_two_of_three_count"], result["complete_disagreement_count"]) == (31, 26, 3)
    assert (result["consensus_count"], result["policy_vs_majority_agreement"]) == (57, 39)
    assert result["policy_deny_count"] == 26
    assert result["policy_deny_vote_distribution"] == recorded["deny_boundary"]["deny_vote_count_distribution"]
    assert result["policy_deny_majority_distribution"] == recorded["deny_boundary"]["human_majority_distribution"]
    with (INPUT.parent / "pairwise_agreement.csv").open(newline="", encoding="utf-8") as stream:
        for pair in csv.DictReader(stream):
            actual = result["pairwise"][f"{pair['reference']} vs {pair['compared']}"]
            assert actual["exact_agreement"] == int(pair["exact_agreement"])
            assert actual["cohens_kappa"] == pytest.approx(float(pair["cohens_kappa"]))


def test_public_labels_reject_changed_majority(tmp_path) -> None:
    rows = list(csv.DictReader(INPUT.open(newline="", encoding="utf-8")))
    rows[0]["human_majority_label"] = "DENY" if rows[0]["human_majority_label"] != "DENY" else "ALLOW"
    target = tmp_path / "invalid.csv"
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows)
    with pytest.raises(ValueError, match="majority label"):
        read_labels(target)
