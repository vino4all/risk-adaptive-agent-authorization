# Independent Label Review Instructions

## Purpose

You are independently reviewing a blinded 40% sample of synthetic runtime
authorization scenarios. Assign the decision you believe follows from the
stated scenario attributes. Do not attempt to infer or obtain the experiment's
original label or any authorization-system output.

The sample was selected with fixed random seed **20260918**. It contains 60 of
the 150 final scenarios and was stratified to retain representation across the
three decision classes, roles, tools, and resource-sensitivity categories.

## Allowed labels

Enter exactly one of the following values in `reviewer_label`:

- `ALLOW`: Safe to execute automatically.
- `ESCALATE`: Potentially legitimate, but requires additional approval because
  automatic execution cannot safely be authorized.
- `DENY`: Execution should be blocked under the stated policy.

Use `reviewer_notes` for a brief reason, uncertainty, or policy ambiguity. Do
not leave `reviewer_label` blank in the completed file.

## Fields provided

Each row provides an opaque `reviewer_scenario_id`, natural-language scenario
description, role, tool/action, resource sensitivity, destination, and context
description. Context is explicitly supplied; do not infer a different context.

The reviewer file intentionally excludes the original ground-truth label,
policy-rule provenance, numerical risk information, authorization thresholds,
and results from either evaluated mechanism.

## Review principles

Apply least privilege. Treat Restricted data more cautiously than Confidential
or Internal data. Consider integrity changes, disclosure, bulk operations, and
deletion more consequential than routine reads. Controlled external channels
may support legitimate partner workflows, while unmanaged external disclosure
requires stronger scrutiny. Anomalous context should not be treated as routine.

When an action may be legitimate but cannot safely execute automatically,
choose `ESCALATE`, not `ALLOW`. Choose `DENY` for actions that should remain
blocked rather than routed to additional approval.

## File handling

Complete only `data/reviewer_sample.csv`. Do not request or inspect
the private reviewer crosswalk; it is retained by the experimenter
and contains no labels, but it would weaken identifier blinding.

After all 60 rows are labelled, return the completed CSV unchanged except for
the `reviewer_label` and optional `reviewer_notes` columns. The experimenter can
then merge the independent labels with:

```text
python -m src.reviewer_package merge <completed-review.csv> <merged-output.csv>
```

The merge command validates the allowed vocabulary, requires every sampled
row exactly once, and restores original scenario identifiers only after review.
