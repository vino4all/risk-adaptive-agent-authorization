# Risk-Adaptive Agent Authorization

Research artifact for **“Confirmatory Evaluation of Risk-Adaptive Three-Way Runtime Authorization for Tool-Using AI Agents”**, International Conference on Artificial Intelligence, Computer, Data Sciences and Applications (ACDSA 2027), February 2–4, 2027, Rio de Janeiro, Brazil.

## Research question and findings

On 150 frozen, purposively constructed synthetic tool-call scenarios, how do a three-way scalar risk rule and a context-aware binary ABAC comparator differ in unsafe automatic ALLOW, legitimate direct completion, escalation, and authorization-call latency?

| Primary measure | Context-aware ABAC | Risk-adaptive |
|---|---:|---:|
| Unsafe execution rate on policy-DENY cases | 0/65 | 1/65 |
| Legitimate direct completion on policy-ALLOW cases | 27/27 | 14/27 |

These are **frozen synthetic benchmark results**, not real-world deployment rates. The primary paired comparison does not support a safety improvement: risk-adaptive authorization allowed one policy-DENY case and directly completed fewer policy-ALLOW cases. The comparator evaluates the same qualitative policy used to generate benchmark labels; its 0/65 UER and 27/27 LDCR are policy-conformance properties by construction. Both methods receive the same scenario records, but the comparator evaluates role in qualitative rules while the score uses sensitivity, action severity, exposure, and context numerically. Its binary decision also cannot represent escalation. See [comparator design](docs/methodology/comparator.md) and the preserved [primary results](confirmatory/results/authorization/).

## Layout

- `src/`, `analysis/`, `confirmatory/*.py`: authorization, analysis, verification, and public reproduction code.
- `confirmatory/inputs/`: frozen scenarios, policy, risk configuration, comparator, and analysis plan.
- `confirmatory/results/authorization/`: preserved primary decisions and statistics.
- `confirmatory/results/latency/`: preserved in-process authorization-call measurements and recovered manifest; see [recovery note](docs/reproducibility/latency_recovery.md). These timings exclude full agent/tool workflows and human approval time.
- `confirmatory/results/ordinal_mapping_sensitivity/`: **post-hoc exploratory** mapping analysis.
- `confirmatory/results/reviewer_robustness/`: de-identified labels and aggregate post-confirmatory reviewer validation.
- `results/exploratory/`: earlier exploratory outputs, separate from primary confirmation.
- `docs/`, `tests/`: methods, provenance, and verification tests.

## Verify and reproduce

Use Python 3.12 and install `requirements.lock` in a fresh virtual environment:

```sh
python -m venv .venv
python -m pip install -r requirements.lock
python -m pytest -q
python -c "from confirmatory.provenance import verify_freeze; verify_freeze(require_empty_authorization=False); print('Freeze v2 verified')"
python -m analysis.public_reviewer_validation
```

`python -m confirmatory.runner` is a verification-only command but refuses this completed repository because its pre-execution guard requires an empty authorization-results directory. It does not rerun the experiment. An independent authorization replay, if needed, writes only to a new empty directory outside the repository:

```sh
python -m analysis.public_reproduction ../authorization-replay
```

The post-hoc ordinal mapping analysis can likewise write to a separate empty directory with `python -m analysis.ordinal_mapping_sensitivity --output-dir ../ordinal-replay`. Do not run the confirmatory runner with `--execute` or rerun the latency benchmark against the preserved results. Output hashes are in [PUBLIC_RELEASE_MANIFEST.md](PUBLIC_RELEASE_MANIFEST.md).

## Robustness and privacy

Three blinded reviewers labeled a 60-case subset. Human-reviewer Fleiss κ was 0.4657 and nominal Krippendorff α was 0.4687. A two-of-three majority existed for 57/60 cases; the policy-DENY boundary remained contested. These post-confirmatory labels do not replace the frozen policy ground truth. The de-identified public CSV supports independent recalculation of pairwise agreement, multi-rater statistics, majority counts, and DENY-boundary counts. Raw returns, notes, identities, and the private crosswalk are withheld. See [reviewer validation](docs/robustness/reviewer_validation.md).

The [ordinal mapping analysis](docs/robustness/ordinal_mapping.md) is **POST-HOC EXPLORATORY**. [Threshold sensitivity](docs/robustness/threshold_sensitivity.md) is secondary and does not change the selected thresholds.

## Citation and license

Citation metadata for Vinothkumar Arputharaj and Karthik Jambulingam is in [CITATION.cff](CITATION.cff). Code is licensed under MIT in [LICENSE](LICENSE); authored data and results are licensed under CC BY 4.0 in [DATA_LICENSE.md](DATA_LICENSE.md). Vinothkumar Arputharaj holds the rights to the original repository material. No DOI is asserted.
