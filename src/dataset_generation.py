"""Generate the final synthetic dataset from qualitative policy rules only.

This module intentionally does not import or invoke either authorization
mechanism. It reads only ``ground_truth_matrix.rules`` from the policy YAML.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from src.models import (
    ConfigurationError,
    ContextRisk,
    Decision,
    Destination,
    Role,
    Scenario,
    Sensitivity,
    Tool,
)
from src.policy import (
    DEFAULT_PILOT_SCENARIOS_PATH,
    DEFAULT_POLICY_MATRIX_PATH,
    DEFAULT_SCENARIOS_PATH,
    PolicyRule,
    load_scenarios,
    load_yaml_mapping,
)

DEFAULT_REPORT_PATH = Path(__file__).resolve().parent.parent / "DATASET_VALIDATION_REPORT.md"
TARGET_COUNT = 150

DIMENSION_NAMES = ("role", "tool", "sensitivity", "destination", "context_risk")
TARGETS: Mapping[str, Mapping[str, int]] = {
    "role": {member.value: 50 for member in Role},
    "tool": {member.value: 30 for member in Tool},
    "sensitivity": {member.value: 50 for member in Sensitivity},
    "destination": {member.value: 50 for member in Destination},
    "context_risk": {
        ContextRisk.NORMAL.value: 42,
        ContextRisk.UNUSUAL.value: 36,
        ContextRisk.HIGH_VOLUME.value: 36,
        ContextRisk.ANOMALOUS.value: 36,
    },
}

RESOURCES: Mapping[Sensitivity, tuple[str, ...]] = {
    Sensitivity.INTERNAL: (
        "operations_schedule",
        "product_catalog",
        "employee_directory",
        "workflow_queue",
    ),
    Sensitivity.CONFIDENTIAL: (
        "customer_accounts",
        "contract_records",
        "personnel_cases",
        "support_transcripts",
    ),
    Sensitivity.RESTRICTED: (
        "payment_credentials",
        "privileged_audit_logs",
        "security_incidents",
        "regulated_identity_records",
    ),
}

ACTION_TEXT: Mapping[Tool, str] = {
    Tool.READ_RECORD: "read",
    Tool.UPDATE_RECORD: "update",
    Tool.EXPORT_DATA: "export",
    Tool.SEND_MESSAGE: "send a message containing",
    Tool.DELETE_RECORD: "delete",
}

DESTINATION_TEXT: Mapping[Destination, str] = {
    Destination.INTERNAL: "within the internal environment",
    Destination.CONTROLLED_EXTERNAL: "through a controlled partner channel",
    Destination.EXTERNAL: "to an unmanaged external destination",
}

CONTEXT_TEXT: Mapping[ContextRisk, str] = {
    ContextRisk.NORMAL: "during a routine workflow",
    ContextRisk.UNUSUAL: "under an unusual but plausible workflow condition",
    ContextRisk.HIGH_VOLUME: "as part of a high-volume operation",
    ContextRisk.ANOMALOUS: "under anomalous execution conditions",
}


@dataclass(frozen=True, slots=True)
class Candidate:
    role: Role
    tool: Tool
    sensitivity: Sensitivity
    destination: Destination
    context_risk: ContextRisk
    rule: PolicyRule

    @property
    def key(self) -> tuple[str, ...]:
        return (
            self.role.value,
            self.tool.value,
            self.sensitivity.value,
            self.destination.value,
            self.context_risk.value,
        )


def load_qualitative_rules(
    path: str | Path = DEFAULT_POLICY_MATRIX_PATH,
) -> tuple[PolicyRule, ...]:
    """Load only the independently authored qualitative policy rule section."""
    document = load_yaml_mapping(path)
    section = document.get("ground_truth_matrix")
    if not isinstance(section, Mapping):
        raise ConfigurationError(f"{path}: ground_truth_matrix must be a mapping")
    entries = section.get("rules")
    if not isinstance(entries, list) or not entries:
        raise ConfigurationError(f"{path}: ground_truth_matrix.rules must be non-empty")
    rules = tuple(
        PolicyRule.from_dict(entry, source_order=index)
        for index, entry in enumerate(entries)
    )
    return tuple(sorted(rules, key=lambda rule: (rule.priority, rule.source_order)))


def _plausible(
    tool: Tool,
    destination: Destination,
    context: ContextRisk,
    sensitivity: Sensitivity,
) -> bool:
    """Domain-authored plausibility filter; not a label or score function."""
    if tool is Tool.DELETE_RECORD:
        # Deletion normally targets an internal record. Retain a limited set of
        # non-internal proposals as explicit policy-boundary/adversarial cases.
        return destination is Destination.INTERNAL or (
            context in (ContextRisk.NORMAL, ContextRisk.ANOMALOUS)
            and sensitivity in (Sensitivity.CONFIDENTIAL, Sensitivity.RESTRICTED)
        )
    if tool is Tool.UPDATE_RECORD and destination is Destination.EXTERNAL:
        # External record updates are plausible only as atypical SaaS/integration
        # operations, rather than routine internal updates.
        return context in (ContextRisk.UNUSUAL, ContextRisk.ANOMALOUS)
    return True


def _scenario_key(scenario: Scenario) -> tuple[str, ...]:
    return (
        scenario.role.value,
        scenario.tool.value,
        scenario.sensitivity.value,
        scenario.destination.value,
        scenario.context_risk.value,
    )


def enumerate_candidates(
    rules: Sequence[PolicyRule], pilot_scenarios: Sequence[Scenario]
) -> tuple[Candidate, ...]:
    pilot_keys = {_scenario_key(scenario) for scenario in pilot_scenarios}
    candidates: list[Candidate] = []
    for role, tool, sensitivity, destination, context in product(
        Role, Tool, Sensitivity, Destination, ContextRisk
    ):
        if not _plausible(tool, destination, context, sensitivity):
            continue
        probe = Scenario(
            scenario_id="CANDIDATE",
            role=role,
            tool=tool,
            sensitivity=sensitivity,
            destination=destination,
            context_risk=context,
        )
        matched = next((rule for rule in rules if rule.matches(probe)), None)
        if matched is None:
            raise ConfigurationError(f"no qualitative policy rule matches {probe.to_dict()}")
        candidate = Candidate(role, tool, sensitivity, destination, context, matched)
        if candidate.key not in pilot_keys:
            candidates.append(candidate)
    return tuple(candidates)


def _select_class(
    pool: Sequence[Candidate],
    count: int,
    selected: list[Candidate],
) -> None:
    dimension_counts = {
        name: Counter(getattr(item, name).value for item in selected)
        for name in DIMENSION_NAMES
    }
    rule_counts = Counter(item.rule.rule_id for item in selected)
    remaining = list(pool)
    while len([item for item in selected if item.rule.decision is pool[0].rule.decision]) < count:
        if not remaining:
            raise ConfigurationError("insufficient plausible candidates for class quota")

        def priority(item: Candidate) -> tuple[float, float, tuple[str, ...]]:
            deficit = sum(
                max(
                    TARGETS[name][getattr(item, name).value]
                    - dimension_counts[name][getattr(item, name).value],
                    0,
                )
                / TARGETS[name][getattr(item, name).value]
                for name in DIMENSION_NAMES
            )
            rule_diversity = 1.0 / (1 + rule_counts[item.rule.rule_id])
            return (deficit, rule_diversity, tuple(reversed(item.key)))

        chosen = max(remaining, key=priority)
        remaining.remove(chosen)
        selected.append(chosen)
        for name in DIMENSION_NAMES:
            dimension_counts[name][getattr(chosen, name).value] += 1
        rule_counts[chosen.rule.rule_id] += 1


def select_candidates(
    candidates: Sequence[Candidate], target_count: int = TARGET_COUNT
) -> tuple[Candidate, ...]:
    """Choose a stratified subset with all distinct policy-attribute tuples."""
    by_class = {
        decision: [item for item in candidates if item.rule.decision is decision]
        for decision in Decision
    }
    # Preserve every distinct non-pilot ALLOW tuple; the qualitative policy has
    # relatively few. Split remaining capacity between ESCALATE and DENY while
    # retaining a modestly larger prohibited class for security boundary cases.
    allow_quota = len(by_class[Decision.ALLOW])
    remaining = target_count - allow_quota
    escalate_quota = min(58, remaining // 2)
    deny_quota = remaining - escalate_quota
    quotas = {
        Decision.ALLOW: allow_quota,
        Decision.ESCALATE: escalate_quota,
        Decision.DENY: deny_quota,
    }
    selected: list[Candidate] = []
    for decision in (Decision.ALLOW, Decision.ESCALATE, Decision.DENY):
        pool = sorted(by_class[decision], key=lambda item: item.key)
        _select_class(pool, quotas[decision], selected)
    return tuple(selected)


def materialize(selected: Sequence[Candidate]) -> tuple[Scenario, ...]:
    scenarios: list[Scenario] = []
    for index, item in enumerate(selected, start=1):
        resources = RESOURCES[item.sensitivity]
        resource = resources[(index - 1) % len(resources)]
        description = (
            f"{item.role.value.title()} proposes to {ACTION_TEXT[item.tool]} "
            f"{resource.replace('_', ' ')} {DESTINATION_TEXT[item.destination]} "
            f"{CONTEXT_TEXT[item.context_risk]}."
        )
        rationale = (
            f"{item.rule.rule_id}: {item.rule.description} "
            f"{item.rule.rationale}"
        ).strip()
        scenarios.append(
            Scenario(
                scenario_id=f"F{index:03d}",
                role=item.role,
                tool=item.tool,
                sensitivity=item.sensitivity,
                destination=item.destination,
                context_risk=item.context_risk,
                ground_truth=item.rule.decision,
                description=description,
                rationale=rationale,
                resource=resource,
                policy_rule_ids=(item.rule.rule_id,),
                metadata={"dataset_partition": "final"},
            )
        )
    return tuple(scenarios)


def generate_dataset(
    policy_path: str | Path = DEFAULT_POLICY_MATRIX_PATH,
    pilot_path: str | Path = DEFAULT_PILOT_SCENARIOS_PATH,
) -> tuple[Scenario, ...]:
    rules = load_qualitative_rules(policy_path)
    pilots = load_scenarios(pilot_path)
    return materialize(select_candidates(enumerate_candidates(rules, pilots)))


def _counts(scenarios: Iterable[Scenario], attribute: str) -> Counter[str]:
    return Counter(str(getattr(scenario, attribute)) for scenario in scenarios)


def validation_summary(scenarios: Sequence[Scenario]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "scenario_count": len(scenarios),
        "class_counts": dict(sorted(_counts(scenarios, "ground_truth").items())),
    }
    for name in DIMENSION_NAMES:
        summary[f"{name}_counts"] = dict(sorted(_counts(scenarios, name).items()))
    summary["cross_tabs"] = {
        f"ground_truth_by_{name}": {
            decision.value: dict(
                sorted(
                    Counter(
                        str(getattr(scenario, name))
                        for scenario in scenarios
                        if scenario.ground_truth is decision
                    ).items()
                )
            )
            for decision in Decision
        }
        for name in DIMENSION_NAMES
    }
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Final Dataset Validation Report",
        "",
        f"Scenario count: **{summary['scenario_count']}**",
        "",
        "All labels were assigned by first-match evaluation of the qualitative policy matrix. No authorization algorithm was run.",
        "",
    ]
    sections = (
        ("Class counts", "class_counts"),
        ("Role counts", "role_counts"),
        ("Tool counts", "tool_counts"),
        ("Sensitivity counts", "sensitivity_counts"),
        ("Destination counts", "destination_counts"),
        ("Context counts", "context_risk_counts"),
    )
    for title, key in sections:
        lines.extend([f"## {title}", "", "| Value | Count |", "| --- | ---: |"])
        lines.extend(f"| {value} | {count} |" for value, count in summary[key].items())
        lines.append("")
    lines.extend(["## Cross-tab summaries", ""])
    for title, table in summary["cross_tabs"].items():
        columns = sorted({column for row in table.values() for column in row})
        lines.extend([
            f"### {title.replace('_', ' ').title()}",
            "",
            "| Ground truth | " + " | ".join(columns) + " |",
            "| --- | " + " | ".join("---:" for _ in columns) + " |",
        ])
        for decision, row in table.items():
            lines.append(
                f"| {decision} | " + " | ".join(str(row.get(column, 0)) for column in columns) + " |"
            )
        lines.append("")
    return "\n".join(lines)


def write_outputs(
    scenarios: Sequence[Scenario],
    *,
    dataset_path: str | Path = DEFAULT_SCENARIOS_PATH,
    report_path: str | Path = DEFAULT_REPORT_PATH,
) -> None:
    document = {
        "_meta": {
            "file": "data/scenarios.yaml",
            "schema_version": "1.0.0",
            "status": "final-dataset-authored-not-evaluated",
            "scenario_count": len(scenarios),
            "dataset_partition": "final",
            "ground_truth_source": "data/policy_matrix.yaml#ground_truth_matrix",
            "pilot_scenarios_excluded": True,
            "authorization_algorithms_run": False,
        },
        "scenarios": [scenario.to_dict() for scenario in scenarios],
    }
    Path(dataset_path).write_text(
        yaml.safe_dump(document, sort_keys=False, width=100), encoding="utf-8"
    )
    Path(report_path).write_text(
        render_report(validation_summary(scenarios)), encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate policy-labelled final scenarios")
    parser.add_argument("--write", action="store_true", help="write dataset and validation report")
    args = parser.parse_args(argv)
    scenarios = generate_dataset()
    if args.write:
        write_outputs(scenarios)
    print(yaml.safe_dump(validation_summary(scenarios), sort_keys=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
