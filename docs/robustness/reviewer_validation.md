# Post-confirmatory three-reviewer robustness analysis

> This is a post-confirmatory robustness analysis. Human-majority labels do not replace the frozen policy-derived ground truth or the primary confirmatory results.

## Sources and validation

This analysis pairs the 60 blinded validation cases by `reviewer_scenario_id`. The frozen policy label was joined to `confirmatory/inputs/scenarios.yaml` through a withheld private crosswalk; the 150-case primary decision CSV was used only for the optional exploratory subset metrics. The three blinded returns are withheld for reviewer privacy. Aggregate results below use Reviewer 1, Reviewer 2, and Reviewer 3; the original private analysis and inputs are preserved outside the public repository.

Each return has exactly **60 rows and 60 unique IDs**. Every ID set exactly matches the outbound `confirmatory/reviewer_export/reviewer_sample.csv`; every nonresponse scenario field matches its outbound row; every label is nonblank and exactly `ALLOW`, `ESCALATE`, or `DENY`. The key has the same 60 IDs, and its frozen scenario labels match the recorded primary labels. The files contain separate completed judgments; their procedural independence comes from the blinded review workflow, which file contents alone cannot establish.

## 1. Pairwise agreement

Matrices use the row source as reference and the column source as comparison; every matrix totals 60. Exact agreement is the diagonal sum. Cohen's κ uses chance agreement implied by each pair's observed marginals. Per-policy-label agreement divides diagonal cases by the number of reviewed cases carrying that frozen policy label.

| Pair | Exact agreement | Raw agreement | Cohen's κ |
|---|---:|---:|---:|
| Policy vs Reviewer 1 | 32/60 | 53.33% | 0.3301 |
| Policy vs Reviewer 2 | 45/60 | 75.00% | 0.6129 |
| Policy vs Reviewer 3 | 36/60 | 60.00% | 0.3916 |
| Reviewer 1 vs Reviewer 2 | 35/60 | 58.33% | 0.3711 |
| Reviewer 1 vs Reviewer 3 | 38/60 | 63.33% | 0.4451 |
| Reviewer 2 vs Reviewer 3 | 46/60 | 76.67% | 0.6178 |

**Policy vs Reviewer 1** (rows: policy; columns: Reviewer 1):

| Policy label | ALLOW | ESCALATE | DENY | Policy total | Per-policy-label agreement |
|---|---:|---:|---:|---:|---:|
| ALLOW | 11 | 0 | 0 | 11 | 11/11 (100.00%) |
| ESCALATE | 8 | 12 | 3 | 23 | 12/23 (52.17%) |
| DENY | 8 | 9 | 9 | 26 | 9/26 (34.62%) |

**Policy vs Reviewer 2** (rows: policy; columns: Reviewer 2):

| Policy label | ALLOW | ESCALATE | DENY | Policy total | Per-policy-label agreement |
|---|---:|---:|---:|---:|---:|
| ALLOW | 11 | 0 | 0 | 11 | 11/11 (100.00%) |
| ESCALATE | 0 | 22 | 1 | 23 | 22/23 (95.65%) |
| DENY | 1 | 13 | 12 | 26 | 12/26 (46.15%) |

**Policy vs Reviewer 3** (rows: policy; columns: Reviewer 3):

| Policy label | ALLOW | ESCALATE | DENY | Policy total | Per-policy-label agreement |
|---|---:|---:|---:|---:|---:|
| ALLOW | 9 | 2 | 0 | 11 | 9/11 (81.82%) |
| ESCALATE | 3 | 16 | 4 | 23 | 16/23 (69.57%) |
| DENY | 4 | 11 | 11 | 26 | 11/26 (42.31%) |

**Reviewer 1 vs Reviewer 2** (rows: Reviewer 1; columns: Reviewer 2):

| Reviewer 1 label | ALLOW | ESCALATE | DENY |
|---|---:|---:|---:|
| ALLOW | 11 | 15 | 1 |
| ESCALATE | 1 | 16 | 4 |
| DENY | 0 | 4 | 8 |

**Reviewer 1 vs Reviewer 3** (rows: Reviewer 1; columns: Reviewer 3):

| Reviewer 1 label | ALLOW | ESCALATE | DENY |
|---|---:|---:|---:|
| ALLOW | 14 | 10 | 3 |
| ESCALATE | 1 | 16 | 4 |
| DENY | 1 | 3 | 8 |

**Reviewer 2 vs Reviewer 3** (rows: Reviewer 2; columns: Reviewer 3):

| Reviewer 2 label | ALLOW | ESCALATE | DENY |
|---|---:|---:|---:|
| ALLOW | 9 | 3 | 0 |
| ESCALATE | 7 | 25 | 3 |
| DENY | 0 | 1 | 12 |

## 2. Agreement among the three human reviewers

The frozen policy is **not** treated as a human rater. Fleiss' κ for Reviewer 1, Reviewer 2, and Reviewer 3 is **0.4657**. Krippendorff's nominal α is **0.4687**. The latter uses complete three-rater data and a finite-sample chance-disagreement correction; its implementation passed analytic perfect-agreement and negative-alpha checks and matched an independent coincidence-matrix calculation. Pairwise κ values were cross-checked against `sklearn.metrics.cohen_kappa_score`.

| Human voting pattern | Cases | Share of 60 |
|---|---:|---:|
| Unanimous, 3 of 3 | 31 | 51.67% |
| Exactly 2 of 3 agree | 26 | 43.33% |
| At least 2 of 3 agree | 57 | 95.00% |
| Complete disagreement, all three labels different | 3 | 5.00% |

Three cases had complete disagreement; all carry frozen policy label `ESCALATE`.

| Label | Frozen policy | Reviewer 1 | Reviewer 2 | Reviewer 3 |
|---|---:|---:|---:|---:|
| ALLOW | 11 | 27 | 12 | 16 |
| ESCALATE | 23 | 21 | 35 | 29 |
| DENY | 26 | 12 | 13 | 15 |

These marginals matter for κ and α interpretation: all three reviewers use `DENY` less often than the frozen policy, while their use of `ALLOW` and `ESCALATE` differs.

## 3. Frozen policy versus human majority

For this **secondary robustness analysis only**, two or three matching human labels define a majority; all three different yields `NO_CONSENSUS`. There are **57** majority cases, including **31** unanimous cases, and **3** no-consensus cases. No label is imputed for a no-consensus case. On the 57 consensus cases, policy and human majority agree **39/57 (68.42%)**, with Cohen's **κ = 0.5296**.

The confusion matrix uses frozen policy rows and human-majority columns **on the 57 consensus cases only**:

| Policy label | Human ALLOW | Human ESCALATE | Human DENY | Consensus cases | Per-policy-label agreement |
|---|---:|---:|---:|---:|---:|
| ALLOW | 11 | 0 | 0 | 11 | 11/11 (100.00%) |
| ESCALATE | 2 | 17 | 1 | 20 | 17/20 (85.00%) |
| DENY | 3 | 12 | 11 | 26 | 11/26 (42.31%) |

the private row-level majority-label file retains each frozen policy label, three human labels, majority result, vote strength, and unanimity flag. It is an analysis artifact and is not a replacement-label file for the confirmatory experiment.

## 4. DENY-boundary analysis

The frozen policy defines 26 `DENY` cases in this 60-case sample. This boundary supplies the denominator for the study's UER, so its independent support matters directly to interpreting a safety rate.

| Human reviewers choosing DENY | Policy-DENY cases | Share of 26 |
|---|---:|---:|
| 3 of 3 | 8 | 30.77% |
| 2 of 3 | 3 | 11.54% |
| 1 of 3 | 2 | 7.69% |
| 0 of 3 | 13 | 50.00% |

| Human majority on policy-DENY cases | Cases | Share of 26 |
|---|---:|---:|
| ALLOW | 3 | 11.54% |
| ESCALATE | 12 | 46.15% |
| DENY | 11 | 42.31% |
| NO_CONSENSUS | 0 | 0.00% |

Thus 15 of 26 policy-DENY cases have a human majority of `ALLOW` or `ESCALATE`; 13 have no human `DENY` vote at all. This is evidence of a contested DENY boundary in the reviewed sample, not adjudication of which decision is correct.

## 5. Exploratory outcome-metric sensitivity on reviewed cases

**EXPLORATORY, descriptive subset analysis only.** The frozen primary decisions of the risk-adaptive method and context-aware binary ABAC are reused without re-execution or alteration. UER is predicted `ALLOW` among reference `DENY`; LDCR is predicted `ALLOW` among reference `ALLOW`; OER is predicted `ESCALATE` among reference `ALLOW`; CER is predicted `ESCALATE` among reference `ESCALATE`. The two consensus-subset rows per method use exactly the **same 57 cases**, so their differences reflect changed reference labels. The all-60 frozen-policy rows show the original reviewed-sample composition. The binary ABAC comparator cannot emit `ESCALATE`, so its OER and CER zeros are structural.

| Reference and sample | Method | UER | LDCR | OER | CER |
|---|---|---:|---:|---:|---:|
| Frozen policy, all 60 | Risk-adaptive | 1/26 (3.85%) | 5/11 (45.45%) | 6/11 (54.55%) | 11/23 (47.83%) |
| Frozen policy, all 60 | Context-aware ABAC | 0/26 (0%) | 11/11 (100%) | 0/11 (0%) | 0/23 (0%) |
| Frozen policy, same 57 consensus cases | Risk-adaptive | 1/26 (3.85%) | 5/11 (45.45%) | 6/11 (54.55%) | 10/20 (50.00%) |
| Frozen policy, same 57 consensus cases | Context-aware ABAC | 0/26 (0%) | 11/11 (100%) | 0/11 (0%) | 0/20 (0%) |
| Human majority, same 57 consensus cases | Risk-adaptive | 0/12 (0%) | 5/16 (31.25%) | 9/16 (56.25%) | 15/29 (51.72%) |
| Human majority, same 57 consensus cases | Context-aware ABAC | 0/12 (0%) | 11/16 (68.75%) | 0/16 (0%) | 0/29 (0%) |

Under the human-majority reference, the risk-adaptive UER numerator becomes zero, while the denominator changes from 26 policy-DENY cases to 12 human-majority DENY cases. Both methods are 0/12 for UER under that reference. The human-majority ALLOW and ESCALATE denominators also change. These descriptive shifts illustrate reference-label sensitivity; they do not change the full 150-case confirmatory estimates and do not support new confirmatory hypothesis tests.

## 6. Interpretation and limits

**A. Reviewer disagreement is not isolated to one reviewer.** Policy-DENY agreement is 9/26 for Reviewer 1, 12/26 for Reviewer 2, and 11/26 for Reviewer 3. The human pairwise agreement rates range from 58.33% to 76.67%, so the reviewers also disagree with each other; no single reviewer can be treated as an adjudicator.

**B. DENY ambiguity persists across reviewers.** Half of the policy-DENY cases receive zero human DENY votes, and a human DENY majority occurs in 11/26. The main difference often concerns `DENY` versus `ESCALATE`, though three policy-DENY cases receive a human ALLOW majority. These are substantial counts relative to the 26-case safety denominator.

**C. The three-reviewer evidence materially strengthens concern about independent validity of the policy-defined DENY boundary.** This judgment is based on the 15/26 policy-DENY cases without a human DENY majority, the 13/26 with no DENY vote, and the changed exploratory reference denominators. It does not establish that the frozen policy is wrong, that human majority is correct, or that deployment safety outcomes would follow either reference. The 60 cases are a stratified subset of a purposive synthetic benchmark, not a probability sample of operational requests. Human-majority construction is post-confirmatory and can conceal real disagreement; row-level labels remain in private evidence. The camera-ready manuscript and its conclusions were not edited automatically.

## Integrity and outputs

Before and after output creation, SHA-256 hashes of all three reviewer files, the outbound package, reviewer key, frozen scenarios, policy matrix, risk configuration, ABAC configuration, analysis plan, and every primary authorization-output file were identical. Freeze v2 verification passed. The private source-hash inventory remains in the archival evidence. Public aggregate outputs are `human_multirater_agreement.json`, `pairwise_agreement.csv`, `policy_vs_human_majority.csv`, and `exploratory_majority_metric_sensitivity.csv`. The nine-column `deidentified_reviewer_labels.csv` is the public reproducibility input; private raw returns and crosswalks remain withheld. No labels were adjudicated or written back, and no primary results were overwritten.
