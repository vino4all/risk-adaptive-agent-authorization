"""Context-aware binary ABAC comparator for the confirmatory experiment.

The comparator uses the full qualitative-policy attribute set and never reads
or computes the numerical risk score. Qualitative ESCALATE is mapped to the
binary-safe DENY outcome because this comparator has no approval state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.models import ConfigurationError, Decision, PolicyOutcome, Scenario
from src.policy import PolicyMatrix, load_yaml_mapping

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "inputs" / "context_aware_abac.yaml"
EXPECTED_ATTRIBUTES = (
    "role",
    "tool",
    "sensitivity",
    "destination",
    "context_risk",
)


@dataclass(frozen=True, slots=True)
class ContextAwareABACConfig:
    attributes: tuple[str, ...]
    decision_mapping: Mapping[Decision, Decision]
    default_decision: Decision
    locked: bool
    source_path: Path

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> "ContextAwareABACConfig":
        resolved = Path(path)
        document = load_yaml_mapping(resolved)
        meta = document.get("_meta") or {}
        if not isinstance(meta, Mapping):
            raise ConfigurationError(f"{resolved}: _meta must be a mapping")
        attributes = tuple(document.get("attributes") or ())
        if attributes != EXPECTED_ATTRIBUTES:
            raise ConfigurationError(
                f"{resolved}: comparator must receive exactly {EXPECTED_ATTRIBUTES}"
            )
        if document.get("binary_only") is not True:
            raise ConfigurationError(f"{resolved}: binary_only must be true")
        if meta.get("numerical_risk_formula_used") is not False:
            raise ConfigurationError(
                f"{resolved}: numerical_risk_formula_used must be false"
            )
        raw_mapping = document.get("decision_mapping")
        if not isinstance(raw_mapping, Mapping):
            raise ConfigurationError(f"{resolved}: decision_mapping must be a mapping")
        try:
            mapping = {Decision(key): Decision(value) for key, value in raw_mapping.items()}
            default = Decision(document.get("default_decision"))
        except ValueError as exc:
            raise ConfigurationError(f"{resolved}: invalid decision: {exc}") from exc
        if set(mapping) != set(Decision):
            raise ConfigurationError(f"{resolved}: all qualitative decisions must be mapped")
        if any(value not in {Decision.ALLOW, Decision.DENY} for value in mapping.values()):
            raise ConfigurationError(f"{resolved}: comparator outputs must be ALLOW or DENY")
        if default not in {Decision.ALLOW, Decision.DENY}:
            raise ConfigurationError(f"{resolved}: default decision must be binary")
        return cls(
            attributes=attributes,
            decision_mapping=mapping,
            default_decision=default,
            locked=meta.get("locked") is True,
            source_path=resolved,
        )


@dataclass(frozen=True, slots=True)
class ContextAwareABACEngine:
    """First-match binary policy retaining every qualitative context condition."""

    matrix: PolicyMatrix
    config: ContextAwareABACConfig

    @classmethod
    def from_files(
        cls,
        matrix: PolicyMatrix,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
    ) -> "ContextAwareABACEngine":
        config = ContextAwareABACConfig.load(config_path)
        if not config.locked:
            raise ConfigurationError("confirmatory context-aware ABAC config is not locked")
        return cls(matrix=matrix, config=config)

    def preflight(self) -> tuple[str, ...]:
        missing: list[str] = []
        if not self.config.locked:
            missing.append("context-aware comparator is not locked")
        if not self.matrix.ground_truth_rules:
            missing.append("qualitative policy has no rules")
        return tuple(missing)

    def authorize(self, scenario: Scenario) -> PolicyOutcome:
        for rule in self.matrix.ground_truth_rules:
            if rule.matches(scenario):
                decision = self.config.decision_mapping[rule.decision]
                return PolicyOutcome(
                    decision=decision,
                    score=None,
                    explanation=(
                        f"Context-aware ABAC rule {rule.rule_id} matched all supplied "
                        f"attributes including context_risk={scenario.context_risk.value}; "
                        f"qualitative {rule.decision.value} maps to binary {decision.value}."
                    ),
                    details={
                        "engine": "context_aware_binary_abac",
                        "matched_rule_id": rule.rule_id,
                        "qualitative_decision": rule.decision.value,
                        "observed_attributes": list(self.config.attributes),
                        "numerical_risk_formula_used": False,
                    },
                )
        return PolicyOutcome(
            decision=self.config.default_decision,
            score=None,
            explanation="No qualitative rule matched; locked binary default applied.",
            details={
                "engine": "context_aware_binary_abac",
                "matched_rule_id": None,
                "observed_attributes": list(self.config.attributes),
                "numerical_risk_formula_used": False,
            },
        )

