"""Scenario evaluation harness.

The evaluator is the only component that measures latency.  It times the call
into an authorization mechanism and never times tool execution, which is the
separation required by the manuscript (section IV.E.4).

Any object exposing ``authorize(scenario) -> PolicyOutcome`` can be evaluated,
so the risk-adaptive mechanism and the binary ABAC baseline are interchangeable
and are always applied to the identical scenario set (matched-pair design).
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from src.latency import Clock, timed
from src.models import (
    AuthorizationResult,
    ConfigurationError,
    Decision,
    Method,
    Scenario,
)

__all__ = ["AuthorizationPolicy", "EvaluationRun", "Evaluator"]


@runtime_checkable
class AuthorizationPolicy(Protocol):
    """Minimal interface required by :class:`Evaluator`."""

    def authorize(self, scenario: Scenario) -> Any:  # pragma: no cover - protocol
        ...

    def preflight(self) -> tuple[str, ...]:  # pragma: no cover - protocol
        ...


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    """The complete result set produced by one mechanism over one scenario set."""

    label: str
    method: Method
    results: tuple[AuthorizationResult, ...]
    scenario_source: str | None = None
    started_at: str = ""
    finished_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", Method(self.method))
        object.__setattr__(self, "results", tuple(self.results))

    @property
    def scenario_ids(self) -> tuple[str, ...]:
        return tuple(result.scenario_id for result in self.results)

    def decision_counts(self) -> dict[str, int]:
        """Count of each decision emitted by this mechanism."""
        counts = {decision.value: 0 for decision in Decision}
        for result in self.results:
            counts[result.decision.value] = counts.get(result.decision.value, 0) + 1
        return counts

    def to_records(self) -> tuple[dict[str, Any], ...]:
        """Flatten the run into CSV-ready rows."""
        return tuple(result.to_row() | {"run_label": self.label} for result in self.results)

    def to_manifest(self) -> dict[str, Any]:
        """Machine-readable description of the run."""
        return {
            "run_label": self.label,
            "method": self.method.value,
            "scenario_source": self.scenario_source,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "scenario_count": len(self.results),
            "decision_counts": self.decision_counts(),
            "mean_latency_ms": (
                sum(result.latency_ms for result in self.results) / len(self.results)
                if self.results
                else None
            ),
        }


@dataclass(slots=True)
class Evaluator:
    """Runs a scenario set through one authorization mechanism, with timings."""

    policy: AuthorizationPolicy
    method: Method
    label: str | None = None
    clock: Clock = time.perf_counter_ns
    _state: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.method = Method(self.method)
        if self.label is None:
            self.label = self.method.value

    # -- introspection ---------------------------------------------------- #

    def preflight(self) -> tuple[str, ...]:
        """Delegate to the mechanism's own readiness check, if it has one."""
        checker = getattr(self.policy, "preflight", None)
        if callable(checker):
            return tuple(checker())
        return ()

    # -- evaluation ------------------------------------------------------- #

    def evaluate(self, scenario: Scenario) -> AuthorizationResult:
        """Authorize one scenario and record its latency."""
        samples: list[float] = []
        with timed(samples, clock=self.clock):
            outcome = self.policy.authorize(scenario)
        binary_correct: bool | None = None
        resolved_as_allow = False
        resolved_as_deny = False
        if self.method is Method.ABAC_BINARY:
            if scenario.ground_truth is None:
                raise ConfigurationError(
                    "binary ABAC result accounting requires an independent "
                    f"ground_truth label for scenario {scenario.scenario_id}"
                )
            if outcome.decision not in (Decision.ALLOW, Decision.DENY):
                raise ConfigurationError(
                    "the binary ABAC baseline produced a non-binary decision "
                    f"({outcome.decision.value}) for scenario {scenario.scenario_id}"
                )
            # Binary-safe execution permits only independently labelled ALLOW
            # cases to execute.  ESCALATE requires approval and therefore has
            # the same safe immediate-execution outcome as DENY: do not execute.
            binary_safe_expected = (
                Decision.ALLOW
                if scenario.ground_truth is Decision.ALLOW
                else Decision.DENY
            )
            binary_correct = outcome.decision is binary_safe_expected
            if scenario.ground_truth is Decision.ESCALATE:
                resolved_as_allow = outcome.decision is Decision.ALLOW
                resolved_as_deny = outcome.decision is Decision.DENY

        return AuthorizationResult(
            scenario_id=scenario.scenario_id,
            decision=outcome.decision,
            latency_ms=samples[0],
            explanation=outcome.explanation,
            score=outcome.score,
            method=self.method,
            ground_truth=scenario.ground_truth,
            correct_for_binary_safe_execution=binary_correct,
            true_escalate_resolved_as_allow=resolved_as_allow,
            true_escalate_resolved_as_deny=resolved_as_deny,
        )

    def evaluate_all(
        self, scenarios: Iterable[Scenario]
    ) -> tuple[AuthorizationResult, ...]:
        return tuple(self.evaluate(scenario) for scenario in scenarios)

    def run(
        self,
        scenarios: Iterable[Scenario],
        *,
        scenario_source: str | None = None,
    ) -> EvaluationRun:
        """Evaluate a whole scenario set and package the results."""
        materialised = tuple(scenarios)
        started_at = _utc_now_iso()
        results = self.evaluate_all(materialised)
        return EvaluationRun(
            label=self.label or self.method.value,
            method=self.method,
            results=results,
            scenario_source=scenario_source,
            started_at=started_at,
            finished_at=_utc_now_iso(),
        )
