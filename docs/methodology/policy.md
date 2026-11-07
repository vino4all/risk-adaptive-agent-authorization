# Policy Ground Truth Design

This document describes the ground-truth authorization policy authored in
`data/policy_matrix.yaml`.  The policy is the source of expected labels for
synthetic scenarios in the IEEE experiment.

## Scope

This layer defines only qualitative ground-truth authorization outcomes:

- `ALLOW`: the operation can execute without additional approval.
- `ESCALATE`: the operation may be legitimate, but needs additional
  authorization or human approval before execution.
- `DENY`: the operation is prohibited under the stated attributes.

The policy layer does not implement risk scoring, threshold selection, the
binary ABAC baseline, or final scenario generation.

## Independence From The Risk Model

The ground-truth policy was authored from explicit security principles and
rule precedence.  It is not generated from numerical risk scores, ordinal factor
mappings, model weights, or threshold cutoffs.  In particular:

- The policy rules do not reference the later risk formula.
- The policy rules do not depend on risk weights.
- The policy rules do not depend on threshold values.
- The policy rules are evaluated directly from scenario attributes:
  `role`, `tool`, `sensitivity`, `destination`, and `context_risk`.

This separation preserves the experiment's methodology: the proposed
risk-adaptive mechanism can later be compared against labels that were not
created by that mechanism.

## Policy Principles

The authored rules use the following qualitative principles.

- Least privilege: Analysts receive routine operational access only. Managers
  receive broader business authority. Administrators receive system authority,
  but not unlimited authority.
- Data sensitivity: Restricted data receives stronger controls than
  Confidential data, and Confidential data receives stronger controls than
  Internal data.
- Role authority: Higher authority may justify an approval workflow, but it
  does not override hard prohibitions.
- Operation side effects: Reads are lower impact than messages, updates,
  exports, and deletes. Updates affect integrity. Exports and messages disclose
  data. Deletes are destructive.
- External disclosure: Unmanaged external disclosure is tightly constrained.
  Controlled external disclosure may be valid for partner workflows but often
  requires approval.
- Bulk operations: High-volume reads or exports require approval unless a
  stricter prohibition applies.
- Contextual anomaly: Anomalous context prohibits high-impact, external, or
  Restricted operations. Residual low-impact internal anomalous cases escalate.
- Destructive actions: Deletes require approval for Internal or Confidential
  data and are prohibited for Restricted data or non-internal destinations.

## Rule Precedence

Rules are evaluated deterministically by ascending `priority`, then file order.
The first matching rule wins.

The precedence model is:

1. Priority `10`: hard `DENY` prohibitions.
2. Priority `20`: `ESCALATE` cases that may be legitimate but require approval.
3. Priority `80`: routine `ALLOW` cases.
4. Priority `99`: fail-closed default `DENY`.

This resolves conflicts deterministically.  A hard prohibition always overrides
a later escalation or allow rule.  An escalation boundary always overrides a
later routine allow rule.

## When Escalation Is Appropriate

`ESCALATE` is used when the action is plausibly legitimate but the policy cannot
safely approve it automatically.  Representative escalation cases include:

- Analyst internal reads of Restricted data.
- Analyst updates or internal exports of Confidential data.
- Manager updates or internal exports of Restricted data.
- Administrator internal exports of Restricted data.
- Controlled external handling of Confidential or Restricted data by authorized
  roles.
- Unmanaged external disclosure of Internal data by Managers or Administrators.
- Confidential non-bulk unmanaged external disclosure by Managers or
  Administrators.
- High-volume reads or exports not otherwise prohibited.
- Unusual sensitive-data, side-effecting, or externally scoped operations.
- Residual anomalous low-impact internal activity.
- Internal deletes of Internal or Confidential data by Managers or
  Administrators.

These cases are intentionally distinct from `DENY`: the policy does not declare
them inherently prohibited, but it also does not permit them to execute without
additional authorization.

## Fail-Closed Behavior

The final rule is `GT-D999`, a catch-all `DENY`.  Any combination not explicitly
allowed or escalated is prohibited until the qualitative policy is extended and
reviewed.  This avoids accidental permission caused by missing rules.

