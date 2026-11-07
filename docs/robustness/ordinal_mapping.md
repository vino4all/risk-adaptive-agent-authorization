# Post-hoc ordinal-mapping sensitivity analysis

## Motivation and status

Sensitivity, exposure, context, and action are ordinal categories. Their numeric spacings are modeling choices, not measured distances. Peer review requested a check of how those spacings affect the frozen risk-adaptive decisions. This is a **post-hoc, secondary, exploratory, descriptive** analysis of the same 150 purposively constructed synthetic scenarios. The mapping set below was fixed for this analysis before its alternative outcomes were calculated; it was not part of the prospective confirmatory protocol. No new hypothesis tests, confidence intervals, calibration, or selection of a preferred mapping were performed.

The risk score remains `R = 0.25*S + 0.25*A + 0.25*E + 0.25*C`. Its thresholds remain `T1 = 0.20` and `T2 = 0.50`, with `R < T1` yielding ALLOW, `T1 <= R < T2` yielding ESCALATE, and `R >= T2` yielding DENY. Ground truth, reviewer labels, and the context-aware binary ABAC comparator are unchanged. Each alternative changes **one factor only**, which makes its effect interpretable; no combined configurations or optimization grid were used.

## Tested mappings

The order within each mapping follows the category order shown here. All factors not named in a row retain the primary mapping.

| Factor | Category order | Primary | Alternatives |
|---|---|---|---|
| Sensitivity | INTERNAL, CONFIDENTIAL, RESTRICTED | 0.00, 0.50, 1.00 | lower-middle: 0.00, 0.25, 1.00; upper-middle: 0.00, 0.75, 1.00 |
| Exposure | INTERNAL, CONTROLLED_EXTERNAL, EXTERNAL | 0.00, 0.50, 1.00 | lower-middle: 0.00, 0.25, 1.00; upper-middle: 0.00, 0.75, 1.00 |
| Context | NORMAL, UNUSUAL, HIGH_VOLUME, ANOMALOUS | 0.00, 0.33, 0.67, 1.00 | lower-middle: 0.00, 0.20, 0.50, 1.00; upper-middle: 0.00, 0.50, 0.80, 1.00 |
| Action | READ_RECORD, UPDATE_RECORD/SEND_MESSAGE, EXPORT_DATA, DELETE_RECORD | 0.00, 0.50, 0.75, 1.00 | compressed: 0.00, 0.25, 0.50, 1.00; elevated: 0.00, 0.60, 0.85, 1.00 |

## Metrics and results

UER is ALLOW among 65 true-DENY cases. LDCR is ALLOW among 27 true-ALLOW cases. OER is ESCALATE among those 27 true-ALLOW cases. CER is ESCALATE among 58 true-ESCALATE cases. Percentages below are descriptive rates on this fixed benchmark. The ABAC comparator remains at UER `0/65` and LDCR `27/27`; as a binary mechanism it cannot emit ESCALATE. Primary risk-adaptive decision counts are ALLOW `15`, ESCALATE `49`, DENY `86`.

| Configuration | UER | LDCR | OER | CER | ALLOW / ESCALATE / DENY | Changed decisions |
|---|---:|---:|---:|---:|---:|---:|
| Primary | 1/65 (1.5%) | 14/27 (51.9%) | 13/27 (48.1%) | 23/58 (39.7%) | 15 / 49 / 86 | 0 |
| Sensitivity lower-middle | 1/65 (1.5%) | 18/27 (66.7%) | 9/27 (33.3%) | 34/58 (58.6%) | 19 / 57 / 74 | 16 |
| Sensitivity upper-middle | 1/65 (1.5%) | 14/27 (51.9%) | 13/27 (48.1%) | 19/58 (32.8%) | 15 / 44 / 91 | 5 |
| Exposure lower-middle | 2/65 (3.1%) | 16/27 (59.3%) | 11/27 (40.7%) | 30/58 (51.7%) | 18 / 55 / 77 | 12 |
| Exposure upper-middle | 1/65 (1.5%) | 14/27 (51.9%) | 13/27 (48.1%) | 20/58 (34.5%) | 15 / 45 / 90 | 4 |
| Context lower-middle | 1/65 (1.5%) | 14/27 (51.9%) | 13/27 (48.1%) | 26/58 (44.8%) | 15 / 53 / 82 | 4 |
| Context upper-middle | 1/65 (1.5%) | 14/27 (51.9%) | 13/27 (48.1%) | 14/58 (24.1%) | 15 / 37 / 98 | 12 |
| Action compressed | 2/65 (3.1%) | 20/27 (74.1%) | 7/27 (25.9%) | 33/58 (56.9%) | 22 / 56 / 72 | 21 |
| Action elevated | 1/65 (1.5%) | 11/27 (40.7%) | 16/27 (59.3%) | 22/58 (37.9%) | 12 / 50 / 88 | 5 |

The next table reports **absolute** UER and LDCR changes from the primary mapping, and **signed** OER and CER changes. Units are percentage points (pp). Exact unrounded differences are in the CSV and JSON outputs.

| Alternative | \|ΔUER\| | \|ΔLDCR\| | ΔOER | ΔCER |
|---|---:|---:|---:|---:|
| Sensitivity lower-middle | 0.0 | 14.8 | -14.8 | +19.0 |
| Sensitivity upper-middle | 0.0 | 0.0 | 0.0 | -6.9 |
| Exposure lower-middle | 1.5 | 7.4 | -7.4 | +12.1 |
| Exposure upper-middle | 0.0 | 0.0 | 0.0 | -5.2 |
| Context lower-middle | 0.0 | 0.0 | 0.0 | +5.2 |
| Context upper-middle | 0.0 | 0.0 | 0.0 | -15.5 |
| Action compressed | 1.5 | 22.2 | -22.2 | +17.2 |
| Action elevated | 0.0 | 11.1 | +11.1 | -1.7 |

## Decision transitions

Each count compares an alternative to the original primary risk-adaptive decision for the **same scenario**. A scenario can appear once for each alternative that changes it. The accompanying decision-change CSV identifies those scenarios and their old and new scores.

| Alternative | ALLOW→ESCALATE | ALLOW→DENY | ESCALATE→ALLOW | ESCALATE→DENY | DENY→ESCALATE | DENY→ALLOW |
|---|---:|---:|---:|---:|---:|---:|
| Sensitivity lower-middle | 0 | 0 | 4 | 0 | 12 | 0 |
| Sensitivity upper-middle | 0 | 0 | 0 | 5 | 0 | 0 |
| Exposure lower-middle | 0 | 0 | 3 | 0 | 9 | 0 |
| Exposure upper-middle | 0 | 0 | 0 | 4 | 0 | 0 |
| Context lower-middle | 0 | 0 | 0 | 0 | 4 | 0 |
| Context upper-middle | 0 | 0 | 0 | 12 | 0 | 0 |
| Action compressed | 0 | 0 | 7 | 0 | 14 | 0 |
| Action elevated | 3 | 0 | 0 | 2 | 0 | 0 |

## Interpretation

The materiality rule was declared in the analysis code before calculating the alternatives: an absolute change of at least **10 percentage points** in any of UER, LDCR, OER, or CER, or at least **15 of 150** changed decisions. These are practical descriptive thresholds, not statistical cutoffs: 10 points is a noticeable shift on this benchmark, and 15 decisions represent one tenth of its scenarios. A changed study conclusion would require an observed UER advantage over the comparator or an LDCR shortfall below 10 points relative to its 100% completion rate. The latter criterion asks whether the substantial direct-completion cost survives, without re-running confirmatory inference.

**Classification: PARTIALLY ROBUST.** Five alternatives meet at least one materiality threshold: sensitivity lower-middle, exposure lower-middle, context upper-middle, action compressed, and action elevated. The largest absolute changes are 1.5 pp for UER, 22.2 pp for LDCR, 22.2 pp for OER, and 19.0 pp for CER; decision changes range from 4 to 21 across alternatives. Nevertheless, no alternative shows fewer unsafe automatic ALLOWs than the comparator's zero, and LDCR remains 40.7%–74.1%, at least 25.9 points below the comparator's 100%. Thus the observed lack of a UER benefit and the substantial direct-completion shortfall remain across this limited mapping set. This is a descriptive sensitivity statement, not a new confirmatory significance claim.

## Limitations and integrity

This finite set changes one factor at a time and does not cover all reasonable joint encodings. The 150 scenarios are purposive and synthetic; results do not estimate deployment rates or population uncertainty. Fixed policy-derived labels and known independent-reviewer disagreement remain limitations of the original study. The ordinal alternatives were specified after primary outcomes were available, so even this bounded analysis cannot be called prospective. Changes to a decision or score indicate sensitivity to encoding, not that a particular alternate encoding is more valid.

Before and after analysis, SHA-256 hashes of frozen scenarios, risk configuration, policy matrix, ABAC configuration, analysis plan, and all primary authorization output files matched. The script replays all 150 primary scores, decisions, labels, and comparator decisions against the frozen CSV, and checks all four primary risk-adaptive metric counts. The exact hash inventory and full mapping values are in `confirmatory/results/ordinal_mapping_sensitivity/ordinal_mapping_summary.json`. The separate outputs are `ordinal_mapping_results.csv` and `ordinal_mapping_decision_changes.csv` in the same directory. No primary files were overwritten.

“This sensitivity analysis does not modify or replace the prespecified primary mapping or confirmatory results.”
