# Pilot Calibration Method

## Purpose and separation from final evaluation

The risk-adaptive authorization mechanism was calibrated on a separate set of
24 synthetic scenarios in `data/pilot_scenarios.yaml`. The pilot is a design
and calibration partition, not part of the final experiment. Its `P001`–`P024`
identifiers are reserved, every row is marked `dataset_partition: pilot`, and
the final-data loader rejects the pilot file, copied pilot identifiers, and
rows carrying the pilot marker. The experiment runner also refuses to execute
a final evaluation containing marked pilot scenarios.

No final evaluation scenarios were generated or used during calibration.

## Independent ground truth

Pilot labels were assigned by deterministic first-match evaluation of the
qualitative rules in `data/policy_matrix.yaml#ground_truth_matrix`. They were
not derived from a risk score. The calibration implementation cross-checks all
pilot labels against that policy matrix before evaluating any candidate and
fails if a label differs.

The pilot contains eight `ALLOW`, eight `ESCALATE`, and eight `DENY` cases. It
covers all three roles, all five tools, all three sensitivity levels, all three
destinations, and all four contextual-risk levels. Boundary cases include
restricted reads, controlled and unmanaged external disclosure, destructive
actions, fail-closed combinations, high-volume access, unusual context, and
anomalous context.

## Risk representation

The score is:

`R = ws*S + wa*A + we*E + wc*C`

The four component mappings were fixed as ordinal policy judgments before the
candidate search and were not fitted to labels:

| Component | Mapping |
| --- | --- |
| Sensitivity `S` | Internal 0.00; Confidential 0.50; Restricted 1.00 |
| Action `A` | Read 0.00; Update 0.50; Message 0.50; Export 0.75; Delete 1.00 |
| Exposure `E` | Internal 0.00; Controlled external 0.50; External 1.00 |
| Context `C` | Normal 0.00; Unusual 0.33; High volume 0.67; Anomalous 1.00 |

Every component lies in `[0,1]`. All candidate weight vectors are non-negative
and sum to one, so every resulting weighted score also lies in `[0,1]`.

## Predetermined coarse search

The calibration evaluates five interpretable weight vectors, in a declared
stability-preference order:

1. equal: `(0.25, 0.25, 0.25, 0.25)`
2. data/exposure: `(0.30, 0.20, 0.30, 0.20)`
3. context-aware: `(0.25, 0.20, 0.25, 0.30)`
4. data/action: `(0.30, 0.30, 0.20, 0.20)`
5. exposure/context: `(0.20, 0.20, 0.30, 0.30)`

The threshold grid is `T1 ∈ {0.20, 0.30, 0.40}` and
`T2 ∈ {0.50, 0.60, 0.70}`, retaining only `T1 < T2`. This yields 45 candidates.
The low `T1=0.20` option is included because the score intentionally has no role
component: role-based policy prohibitions can otherwise have low numerical
attribute severity. Including this coarse boundary allows the security-first
objective to prevent their automatic execution.

No machine learning, continuous optimization, gradient search, or search over
the final dataset is performed.

## Objective and selection rule

For each candidate, the implementation records the four design concerns:

- unsafe automatic allow: ground truth `ESCALATE` or `DENY`, prediction `ALLOW`;
- correct escalation: ground truth and prediction both `ESCALATE`;
- unnecessary escalation: ground truth `ALLOW`, prediction `ESCALATE`;
- legitimate direct completion: ground truth and prediction both `ALLOW`.

It additionally records prohibited cases not directly denied and legitimate
cases directly denied. The fixed loss is:

`100*unsafe_allow + 20*prohibited_not_denied + 8*missed_escalation + 4*unnecessary_escalation + 10*blocked_legitimate`

Selection is explicitly security-first. Candidates with more unsafe automatic
allows than the minimum are removed. Among the remaining security floor, the
minimum loss is found. Configurations within two loss points are treated as
similar; selection then uses the predetermined stability order, followed by
lower loss, greater distance from a threshold, and lower thresholds. Thus a
tiny numerical difference cannot displace a simpler stable configuration.

## Selected configuration and stability result

The selected configuration is equal weights with `T1=0.20` and `T2=0.50`. On
the 24 pilot scenarios it produced zero unsafe automatic allows, seven of eight
correct escalations, four of eight legitimate direct completions, four
unnecessary escalations, three prohibited cases routed to escalation rather
than direct denial, no legitimate direct denials, and 16 exact three-class
matches.

Two configurations performed identically under all recorded pilot outcomes:
equal weights and data/exposure weights, both at `T1=0.20`, `T2=0.50`. Equal
weights were selected using the declared simplicity/stability preference, not
because of a marginal numerical improvement.

The complete configuration and audit record are persisted in
`data/risk_config.yaml`; the operational copy is in `data/policy_matrix.yaml`.
Running `python -m src.calibration` recomputes the 45 candidates, verifies every
pilot ground-truth label, checks the persisted selection, and prints the
selected and similar configurations.

## Freeze rule

The calibrated weights, mappings, and primary thresholds are locked before
primary evaluation. `primary_evaluation_started` is currently `false`. Once it
is changed to `true` at the start of final evaluation, the risk configuration
must not be recalibrated or modified. Final outputs retain the full policy
configuration in their reproducibility manifest.
