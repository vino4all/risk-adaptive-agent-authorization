# Public release manifest

SHA-256 values refer to the exact bytes in this clean snapshot. Frozen inputs, primary decisions, and latency measurements were moved only where stated and were not recomputed. `.gitattributes` stores files without Git line-ending conversion.

Freeze v2 records the aggregate research-source digest `7bc9b72187b8a24bee6d5409666cb64ca2ab3464a8591059566988d1a3f808bb`. Historical private-repository tags are `confirmatory-freeze-v2` (`93b12ad`) and `confirmatory-results-v1` (`425192e`); do not import their history into the new public repository.

## PROVENANCE

| Artifact | SHA-256 |
|---|---|
| `confirmatory/freeze_manifest_v2.json` | `4b23f50d8a0c9562bba7ea536be1da5524e9fc2ead83f848604d1e5a3c50e4e7` |
| `confirmatory/research_source_manifest_v2.json` | `60b11f69b2aca12364078f425d746a0bae0adc26e74020a5b557373529bc6c22` |
| `requirements.lock` | `961d54767779c96a0fd51aa9c41804170a7945df866f969c4dd43b6a3358a4c1` |

## PRIMARY CONFIRMATORY — authorization

| Artifact | SHA-256 |
|---|---|
| `confirmatory/results/authorization/decisions.csv` | `488224b5953c0540d9b0ead965525a411e8f298609ac74100826ff2c6fbee061` |
| `confirmatory/results/authorization/summary_metrics.csv` | `10d47deeb13bc8bec2903e0bfaca172f6673e73e7eabd460f67f572a29084075` |
| `confirmatory/results/authorization/primary_statistical_tests.csv` | `cf24745315537d0fd85b5860883ef878dba424b2666271f26d6416dcb339e349` |
| `confirmatory/results/authorization/escalation_analysis.csv` | `9dcf2f643db9fe49d327f3a59a8d64969f56930a70f7a47569cbf015d2a237c5` |
| `confirmatory/results/authorization/run_manifest.json` | `89bcb6b7c42639e30b4bd793dd0f0ce58f6e3b40c34817fddf92372972b85fbc` |

## PRIMARY CONFIRMATORY — latency recovery

| Artifact | SHA-256 |
|---|---|
| `confirmatory/results/latency/benchmark_manifest_recovered.json` | `509911021f2c030910d8d2778a95337c65ea18a0d58810692611e9a2258dcd21` |
| `confirmatory/results/latency/raw_repetitions.csv` | `6e557d4ec289a8debf044daac3dd1bf541229f4c01b597efea42e54d2c86cfa9` |
| `confirmatory/results/latency/scenario_summary.csv` | `5ff058366ea929249a875a13eadd3cbd5dfbd4db4612bc8f2529a838852cbfd4` |
| `confirmatory/results/latency/timer_overhead.csv` | `38d77fe7a3972fed31b96169d35d68bd885e3b9a9d69fc4d71b9befad0a52ef7` |
| `confirmatory/results/latency/paired_inference.json` | `6c8c27e67e782b70925c1920c6ec7a30c6af4e9a7392b12007665ab7d9e0062c` |

## SECONDARY EXPLORATORY

| Artifact | SHA-256 |
|---|---|
| `confirmatory/results/ordinal_mapping_sensitivity/ordinal_mapping_results.csv` | `ce0aa9a0cecca1c760cf42fd9a5dd2d915ea267f5b87d2c4cfca83c3dddb2640` |
| `confirmatory/results/ordinal_mapping_sensitivity/ordinal_mapping_decision_changes.csv` | `1f0e3491d8d6179a4c3efc9143badf2f19a487672e3564486e0ba35c18576260` |
| `confirmatory/results/ordinal_mapping_sensitivity/ordinal_mapping_summary.json` | `c49943a51d6ca52b07e5dfe86c0e2a88830f72fdec941f9b674ff6f18cf3c304` |
| `results/exploratory/threshold_sensitivity.csv` | `1cd3e01a1ed3e5fbbff6c7b112c51cfb6ab7755725dd667df7b8067f7f419289` |
| `results/exploratory/threshold_sensitivity.png` | `ca0884e6e4d4ce244d4c289c707ca28c5132eee49118e69124086a9b45e0dfe5` |

## POST-CONFIRMATORY VALIDATION

| Artifact | SHA-256 |
|---|---|
| `confirmatory/results/reviewer_robustness/deidentified_reviewer_labels.csv` | `e2d89662dc6300fef74dd1837fbe6f6fab5ade449323aafbb18da404d88680a0` |
| `confirmatory/results/reviewer_robustness/human_multirater_agreement.json` | `c9e9c51a1c8d11ead73661e71c6fd9a8030a90361eddb8bba7270042b7bd91d0` |
| `confirmatory/results/reviewer_robustness/pairwise_agreement.csv` | `5128e391867e599113f2aa8d2565025f762cee8a9b9926eb50c201fba8147845` |
| `confirmatory/results/reviewer_robustness/policy_vs_human_majority.csv` | `ca6073906fbe990dce1a0a38207d4b838cef5629bac00f7b16ac44897a81b23a` |
| `confirmatory/results/reviewer_robustness/exploratory_majority_metric_sensitivity.csv` | `04f4d6973875adcbf682655490025f48e94eadc752fd0dff35ff6d82c3550ef4` |

The post-confirmatory reviewer CSV is a de-identified reproduction input. Its label values were copied from private validated analysis without changing them; raw returns and private crosswalks are not in this snapshot. Reviewer aggregate JSON omits private input-path/hash metadata while retaining the numerical fields.
