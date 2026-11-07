# Confirmatory Comparator Design

## Purpose

The primary confirmatory comparator is a context-aware deterministic binary
ABAC mechanism. The original context-blind ABAC outputs remain unchanged under
`results/exploratory/` as historical exploratory measurements and are not the primary
confirmatory comparison.

## Inputs and decision rule

The comparator receives exactly the same five policy attributes supplied to the
risk-adaptive mechanism: role, tool, resource sensitivity, destination, and
context risk. It evaluates the frozen qualitative policy rules in their
authored first-match order without deleting, replacing, or normalizing context.

It is binary-only. Qualitative `ALLOW` maps to `ALLOW`; qualitative `ESCALATE`
maps to the binary-safe `DENY`; qualitative `DENY` maps to `DENY`. This mapping
means an action requiring approval does not execute automatically. Every
true-`ESCALATE` case remains in the dataset and its binary resolution remains
visible in confirmatory escalation analysis.

## Independence from numerical risk

The implementation in `confirmatory/comparator.py` does not import the risk
engine, read component mappings, compute a score, use weights, or inspect T1/T2.
Its policy and binary mapping are declared in
`confirmatory/inputs/context_aware_abac.yaml`. Its rules originate from the
qualitative policy, not the numerical risk formula.

This design controls contextual information availability and keeps only the
unavoidable binary-versus-three-way outcome difference. It is intentionally a
policy-conformance comparator; conclusions must not portray it as representative
of every production ABAC implementation.

## Audit properties

The configuration requires all five attributes, binary outputs, a locked flag,
and a declaration that numerical risk is unused. The confirmatory runner rejects
non-binary output and records explanations and matched rules. The comparator
configuration, policy, scenarios, risk configuration, and analysis plan are all
covered by the confirmatory freeze manifest.

