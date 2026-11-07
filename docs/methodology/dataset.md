# Final Synthetic Authorization Dataset Design

## Objective and independence

The final dataset contains 150 synthetic pre-execution authorization scenarios
for the IEEE experiment. It was generated independently of both authorization
mechanisms. Ground-truth labels come exclusively from the qualitative rules in
`data/policy_matrix.yaml#ground_truth_matrix`, interpreted according to the
precedence documented in `docs/methodology/policy.md`.

The generation program does not import or call the risk engine or binary ABAC
engine. It does not read the calibration file, component mappings, numerical
scores, risk weights, or authorization thresholds. Neither authorization
algorithm was run while generating or validating the dataset.

## Candidate construction and realism

The generator enumerates structured policy attributes only as an intermediate
candidate pool. It does not retain the full Cartesian product. A domain-authored
plausibility filter removes combinations that would mostly be artificial:

- delete operations normally target internal records; a limited set of
  non-internal deletes is retained as explicit destructive boundary cases;
- unmanaged-external record updates are retained only in unusual or anomalous
  integration contexts;
- reads, exports, and messages retain broader destinations because remote
  access, partner exchange, and disclosure are meaningful authorization cases.

This produces a pool of routine workflows, approval boundaries, hard
prohibitions, contextual anomalies, and fail-closed combinations rather than a
mechanical publication of every possible tuple.

Each candidate is labelled by sorting the qualitative rules by priority and
file order and selecting the first match. The resulting decision, rule
identifier, rule description, and rationale are copied into the scenario
record. There is no numerical decision step.

## Pilot separation

The 24 pilot scenarios are loaded solely to reserve their exact five-attribute
tuples. Any candidate matching a pilot tuple is removed before final selection.
Final identifiers use the separate `F001`–`F150` namespace, while pilots use
`P001`–`P024`. Every final row is marked `dataset_partition: final`.

The final-data loader independently rejects copied pilot identifiers and pilot
partition markers. Automated tests additionally require the pilot and final
sets to be disjoint by both identifier and complete policy-attribute tuple.

## Stratified selection

All distinct, non-pilot `ALLOW` candidates surviving the realism filter were
retained. The policy has relatively few automatic-allow combinations because
automatic permission is limited to routine normal-context workflows; pilot
reservation removes eight additional allow tuples. Creating an apparently
balanced `ALLOW` class would therefore require duplicate attribute scenarios
with merely cosmetic resource changes. That approach was rejected.

The remaining capacity was assigned to 58 `ESCALATE` and 65 `DENY` scenarios.
A deterministic greedy selection reduces deficits against predeclared marginal
targets while increasing first-match rule diversity. The targets are:

- 50 scenarios for each role;
- 30 scenarios for each tool;
- approximately 50 for each sensitivity and destination;
- 42 Normal and 36 each Unusual, High Volume, and Anomalous contexts.

No ground-truth outcome is changed to satisfy a marginal target. Selection is
fully reproducible and contains no random sampling.

## Scenario records

Every scenario contains:

- a stable final-dataset identifier;
- a short natural-language action description and synthetic resource;
- role, tool, sensitivity, destination, and supplied contextual-risk level;
- the qualitative ground-truth decision;
- the complete ground-truth rationale;
- the first-matching qualitative policy rule identifier;
- an explicit final-partition marker.

Exact policy-attribute tuples and scenario identifiers are unique.

## Final composition

The committed dataset contains:

- 27 `ALLOW`, 58 `ESCALATE`, and 65 `DENY` scenarios;
- exactly 50 scenarios for each role;
- exactly 30 scenarios for each tool;
- 49 Confidential, 50 Internal, and 51 Restricted scenarios;
- 49 Controlled External, 51 External, and 50 Internal destinations;
- 42 Normal and 36 each Anomalous, High Volume, and Unusual contexts.

The full class-by-dimension cross-tabs are recorded in
`docs/methodology/dataset_validation.md`.

## Reproducibility and validation

`python -m src.dataset_generation` reconstructs the dataset in memory and
prints its validation summary. The `--write` option writes
`data/scenarios.yaml` and `docs/methodology/dataset_validation.md`.

Automated tests verify size, required fields, tuple uniqueness, identifier
uniqueness, full dimension coverage, meaningful class representation, exact
first-match labels and rule identifiers, pilot separation, reproducible output,
metadata provenance, validation-report consistency, and the absence of risk or
authorization-engine dependencies in the generator.
