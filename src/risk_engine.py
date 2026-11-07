"""Risk-adaptive three-way authorization mechanism.

Implements the mechanism described in manuscript section III:

``R = w_s * S + w_a * A + w_e * E + w_c * C``

``Decision(R) = ALLOW`` if ``R < T1``, ``ESCALATE`` if ``T1 <= R < T2``,
``DENY`` if ``R >= T2``.

The component values, weights and thresholds are all authored inputs.  This
module therefore contains **no numeric constants**: it reads
:class:`~src.policy.RiskModelConfig` and :class:`~src.policy.ThresholdConfig`,
and raises :class:`~src.models.ConfigurationError` if a value it needs has not
been authored yet.

``contextual_risk`` is taken directly from the scenario.  The mechanism never
infers it, and no language model participates in the decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from src.models import (
    ConfigurationError,
    Decision,
    PolicyOutcome,
    RiskAssessment,
    RiskFactors,
    Scenario,
)
from src.policy import COMPONENT_KEYS, PolicyMatrix, RiskModelConfig, ThresholdConfig

__all__ = ["RiskEngine"]

#: The decision rule exactly as specified in the manuscript (section III.E).
DECISION_RULE = "R < T1 -> ALLOW; T1 <= R < T2 -> ESCALATE; R >= T2 -> DENY"


@dataclass(frozen=True, slots=True)
class RiskEngine:
    """Deterministic, configuration-driven risk scorer and decision function."""

    risk_model: RiskModelConfig
    thresholds: ThresholdConfig

    @classmethod
    def from_policy_matrix(cls, matrix: PolicyMatrix) -> "RiskEngine":
        return cls(risk_model=matrix.risk_model, thresholds=matrix.thresholds)

    # -- introspection ---------------------------------------------------- #

    def preflight(self) -> tuple[str, ...]:
        """Return the authoring gaps that block a real mechanism run."""
        return self.risk_model.missing_items() + self.thresholds.missing_items()

    # -- risk scoring ----------------------------------------------------- #

    def factors(self, scenario: Scenario) -> RiskFactors:
        """Map the scenario's ordinal attributes onto normalized factors.

        Each lookup raises :class:`~src.models.ConfigurationError` when the
        corresponding mapping entry has not been authored.
        """
        values = {
            "sensitivity": self.risk_model.factor_value(
                "sensitivity", scenario.sensitivity.value
            ),
            "action_severity": self.risk_model.factor_value(
                "action_severity", scenario.tool.value
            ),
            "exposure_scope": self.risk_model.factor_value(
                "exposure_scope", scenario.destination.value
            ),
            "contextual_risk": self.risk_model.factor_value(
                "contextual_risk", scenario.context_risk.value
            ),
        }
        try:
            return RiskFactors(**values)
        except ValueError as exc:
            raise ConfigurationError(
                f"factor mapping for scenario {scenario.scenario_id} produced an "
                f"out-of-range value: {exc}"
            ) from exc

    def score(self, scenario: Scenario) -> RiskAssessment:
        """Compute the weighted risk score ``R`` for ``scenario``."""
        weights = self.risk_model.locked_weights()
        factors = self.factors(scenario)
        factor_values = factors.as_dict()
        total = sum(
            weights[component] * factor_values[component]
            for component in COMPONENT_KEYS
        )
        try:
            return RiskAssessment(
                scenario_id=scenario.scenario_id,
                score=total,
                factors=factors,
                weights=weights,
            )
        except ValueError as exc:
            raise ConfigurationError(
                f"risk score for scenario {scenario.scenario_id} is outside [0, 1]: "
                f"{exc}; check the authored weights in data/policy_matrix.yaml"
            ) from exc

    # -- decision function ------------------------------------------------ #

    def decide(self, score: float) -> Decision:
        """Apply the three-way threshold rule to a risk score."""
        t1, t2 = self.thresholds.locked_thresholds()
        if score < t1:
            return Decision.ALLOW
        if score < t2:
            return Decision.ESCALATE
        return Decision.DENY

    def authorize(self, scenario: Scenario) -> PolicyOutcome:
        """Score ``scenario`` and return the three-way authorization outcome."""
        assessment = self.score(scenario)
        decision = self.decide(assessment.score)
        t1, t2 = self.thresholds.locked_thresholds()
        return PolicyOutcome(
            decision=decision,
            score=assessment.score,
            explanation=self._explain(assessment, decision, t1, t2),
            details={
                "engine": "risk_adaptive",
                "formula": self.risk_model.formula,
                "factors": assessment.factors.as_dict(),
                "weights": dict(assessment.weights),
                "thresholds": {"T1": t1, "T2": t2},
                "decision_rule": DECISION_RULE,
                "context_risk_supplied": scenario.context_risk.value,
            },
        )

    # -- helpers ---------------------------------------------------------- #

    @staticmethod
    def _explain(
        assessment: RiskAssessment, decision: Decision, t1: float, t2: float
    ) -> str:
        factor_text = ", ".join(
            f"{name}={value:.3f}"
            for name, value in assessment.factors.as_dict().items()
        )
        weight_text = ", ".join(
            f"{name}={value:.3f}" for name, value in assessment.weights.items()
        )
        return (
            f"R={assessment.score:.4f} from [{factor_text}] with weights "
            f"[{weight_text}]; T1={t1:.2f}, T2={t2:.2f} -> {decision.value} "
            f"({DECISION_RULE})"
        )

    def contributions(self, scenario: Scenario) -> Mapping[str, float]:
        """Per-component contributions ``w_i * f_i`` (useful for auditing)."""
        weights = self.risk_model.locked_weights()
        factors = self.factors(scenario).as_dict()
        return {
            component: weights[component] * factors[component]
            for component in COMPONENT_KEYS
        }