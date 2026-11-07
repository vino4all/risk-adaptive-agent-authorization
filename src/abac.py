"""Deterministic binary attribute-based access-control baseline.

The baseline is the primary comparison condition of the experiment (manuscript
section IV.D).  It evaluates the same scenarios as the risk-adaptive mechanism
but is restricted to a binary outcome: ``ALLOW`` or ``DENY``.

The engine is intentionally strict:

* rules come from ``abac_baseline.rules`` in ``data/policy_matrix.yaml``;
* the no-match fallback must be authored as well;
* a rule that resolves to ``ESCALATE`` is always rejected.

``allow_unconfigured`` exists only so that the skeleton can be smoke-tested
before the matrix is authored.  Results produced in that mode are explicitly
labelled as non-experimental and must never be reported.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.models import ConfigurationError, Decision, PolicyOutcome, Scenario
from src.policy import ABACConfig, PolicyMatrix

__all__ = ["ABACEngine"]

_BINARY_DECISIONS = frozenset({Decision.ALLOW, Decision.DENY})

_UNCONFIGURED_NOTE = (
    "UNCONFIGURED EXPLORATION MODE: the ABAC baseline has no authored rules; "
    "this outcome is not a valid experimental result"
)


@dataclass(frozen=True, slots=True)
class ABACEngine:
    """First-match-wins rule evaluation restricted to binary decisions."""

    config: ABACConfig
    allow_unconfigured: bool = False

    @classmethod
    def from_policy_matrix(
        cls, matrix: PolicyMatrix, *, allow_unconfigured: bool = False
    ) -> "ABACEngine":
        return cls(config=matrix.abac, allow_unconfigured=allow_unconfigured)

    # -- introspection ---------------------------------------------------- #

    def preflight(self) -> tuple[str, ...]:
        """Return the authoring gaps that block a real baseline run."""
        return self.config.missing_items()

    # -- evaluation ------------------------------------------------------- #

    def authorize(self, scenario: Scenario) -> PolicyOutcome:
        """Return the binary decision for ``scenario``."""
        missing = self.preflight()
        if missing and not self.allow_unconfigured:
            raise ConfigurationError(
                "the ABAC baseline is not configured yet; author "
                + "; ".join(missing)
                + " in data/policy_matrix.yaml"
            )

        for rule in self.config.rules:
            if rule.matches(scenario):
                return self._outcome(
                    decision=rule.decision,
                    scenario=scenario,
                    explanation=(
                        f"ABAC rule {rule.rule_id} matched "
                        f"(role={scenario.role.value}, tool={scenario.tool.value}, "
                        f"sensitivity={scenario.sensitivity.value}, "
                        f"destination={scenario.destination.value}) -> "
                        f"{rule.decision.value}. {rule.description or rule.rationale}"
                    ),
                    rule_id=rule.rule_id,
                    configured=True,
                )

        fallback = self.config.default_decision
        if fallback is None:
            if not self.allow_unconfigured:
                raise ConfigurationError(
                    "no ABAC rule matched and abac_baseline.default_decision is "
                    "not authored; the fallback outcome is a policy decision and "
                    "must be specified in data/policy_matrix.yaml"
                )
            return self._outcome(
                decision=Decision.DENY,
                scenario=scenario,
                explanation=(
                    f"no ABAC rule matched; {_UNCONFIGURED_NOTE} "
                    "(placeholding fail-closed DENY)"
                ),
                rule_id=None,
                configured=False,
            )

        return self._outcome(
            decision=fallback,
            scenario=scenario,
            explanation=(
                f"no ABAC rule matched; authored default_decision applied -> "
                f"{fallback.value}"
            ),
            rule_id=None,
            configured=True,
        )

    # -- helpers ---------------------------------------------------------- #

    def _outcome(
        self,
        *,
        decision: Decision,
        scenario: Scenario,
        explanation: str,
        rule_id: str | None,
        configured: bool,
    ) -> PolicyOutcome:
        if decision not in _BINARY_DECISIONS:
            raise ConfigurationError(
                "the binary ABAC baseline produced a non-binary decision "
                f"({decision.value}); the baseline supports ALLOW/DENY only"
            )
        return PolicyOutcome(
            decision=decision,
            score=None,
            explanation=f"{explanation} [{_UNCONFIGURED_NOTE}]" if not configured else explanation,
            details={
                "engine": "abac_binary",
                "matched_rule_id": rule_id,
                "configured": configured,
                "context_risk_supplied": scenario.context_risk.value,
            },
        )
