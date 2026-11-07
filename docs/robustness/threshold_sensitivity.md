# Threshold Sensitivity Analysis

## Scope

This is a secondary analysis of the frozen experiment. Component mappings,
component weights, final scenarios, ground-truth labels, and the preregistered
primary thresholds were not changed. The analysis reclassified the risk scores
already recorded in `results/exploratory/decisions.csv`; it did not recompute or retrain the
risk model.

The secondary grid contains all nine combinations of
`T1 ∈ {0.30, 0.40, 0.50}` and `T2 ∈ {0.60, 0.70, 0.80}`. All satisfy `T1 < T2`.
The pilot-selected primary configuration, `T1=0.20` and `T2=0.50`, is retained
as a marked reference and is not part of the secondary grid.

## Recorded measurements

The primary reference produced UER 0.0154, LDCR 0.5185, OER 0.4815, and CER
0.3966.

Across the secondary grid:

- At `T1=0.30`, UER was 0.0769, LDCR was 0.7778, and OER was 0.2222 for all
  three `T2` values.
- At `T1=0.40`, UER was 0.1231, LDCR was 1.0000, and OER was 0.0000 for all
  three `T2` values.
- At `T1=0.50`, UER was 0.2154, LDCR was 1.0000, and OER was 0.0000 for all
  three `T2` values.
- CER ranged from 0.4310 to 0.9828 across the nine secondary pairs.
- For `T1=0.30`, CER was 0.8103 at `T2=0.60` and 0.9828 at both `T2=0.70` and
  `T2=0.80`.
- For `T1=0.40`, CER was 0.6552 at `T2=0.60` and 0.8276 at both `T2=0.70` and
  `T2=0.80`.
- For `T1=0.50`, CER was 0.4310 at `T2=0.60` and 0.6034 at both `T2=0.70` and
  `T2=0.80`.

UER and LDCR depend on the automatic-allow boundary `T1`, so points sharing the
same `T1` coincide in the figure's UER–LDCR projection. The CSV retains all nine
individual `T1`/`T2` rows and their CER values.

No threshold pair was selected, ranked, or designated as a replacement for the
preregistered primary configuration.

## Outputs

- `results/exploratory/threshold_sensitivity.csv` contains one marked primary-reference row
  and nine secondary-grid rows, with numerators, denominators, and rates.
- `results/exploratory/threshold_sensitivity.png` displays UER against LDCR and marks the
  preregistered primary configuration separately.
