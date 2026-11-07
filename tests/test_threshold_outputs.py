"""Integrity tests for committed secondary threshold outputs."""

from __future__ import annotations

import matplotlib.image as mpimg
import numpy as np
import pandas as pd
import pytest

from analysis.evaluate_experiment import DEFAULT_RESULTS_DIR
from analysis.threshold_sensitivity import sensitivity_table, valid_grid_pairs


def test_threshold_csv_contains_primary_reference_and_all_grid_pairs() -> None:
    table = pd.read_csv(DEFAULT_RESULTS_DIR / "threshold_sensitivity.csv")
    assert len(table) == 10
    primary = table[table["is_preregistered_primary"]]
    secondary = table[~table["is_preregistered_primary"]]
    assert len(primary) == 1
    assert (primary.iloc[0]["T1"], primary.iloc[0]["T2"]) == pytest.approx((0.20, 0.50))
    assert set(zip(secondary["T1"], secondary["T2"])) == set(valid_grid_pairs())
    assert set(secondary["configuration_type"]) == {"secondary_sensitivity_grid"}


def test_threshold_metrics_recompute_from_frozen_decisions() -> None:
    decisions = pd.read_csv(DEFAULT_RESULTS_DIR / "decisions.csv")
    committed = pd.read_csv(DEFAULT_RESULTS_DIR / "threshold_sensitivity.csv")
    recomputed = sensitivity_table(decisions)
    for column in (
        "UER_numerator",
        "UER_denominator",
        "UER",
        "LDCR_numerator",
        "LDCR_denominator",
        "LDCR",
        "OER_numerator",
        "OER_denominator",
        "OER",
        "CER_numerator",
        "CER_denominator",
        "CER",
    ):
        assert np.allclose(committed[column], recomputed[column])


def test_primary_reference_matches_preregistered_results() -> None:
    sensitivity = pd.read_csv(DEFAULT_RESULTS_DIR / "threshold_sensitivity.csv")
    primary = sensitivity[sensitivity["is_preregistered_primary"]].iloc[0]
    metrics = pd.read_csv(DEFAULT_RESULTS_DIR / "summary_metrics.csv")
    risk = metrics[metrics["method"] == "risk_adaptive"].set_index("metric")
    for name in ("UER", "LDCR", "OER", "CER"):
        assert primary[name] == pytest.approx(risk.loc[name, "rate"])


def test_publication_figure_exists_and_is_high_resolution() -> None:
    path = DEFAULT_RESULTS_DIR / "threshold_sensitivity.png"
    assert path.is_file()
    image = mpimg.imread(path)
    assert image.shape[0] >= 1200
    assert image.shape[1] >= 1600
