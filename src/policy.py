"""Policy configuration and dataset loading.

This module owns every *authored* value of the experiment.  Nothing here
guesses, defaults or interpolates a policy rule, a risk weight, a factor mapping
or a threshold:

* values that have not been authored yet are represented as ``None``;
* any attempt to *use* such a value raises
  :class:`~src.models.ConfigurationError` and names the exact YAML path that
  still needs to be filled in.

Two policy matrices coexist in the experiment and both live in
``data/policy_matrix.yaml``:

``ground_truth_matrix``
    The independently specified matrix used to author scenario labels
    (draft section IV.C).  It is deliberately *not* derived from the risk score.
``abac_baseline``
    The deterministic binary attribute-based baseline (draft section IV.D).
"""

from __future__ import annotations

from dataclasses import dataclass, field
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

__all__ = [
    "ABAC_ATTRIBUTES",
    "ABAC_RULES_SOURCES",
    "ABACConfig",
    "COMPONENT_KEYS",
    "DEFAULT_DATA_DIR",
    "DEFAULT_PILOT_SCENARIOS_PATH",
    "DEFAULT_POLICY_MATRIX_PATH",
    "DEFAULT_SCENARIOS_PATH",
    "DIMENSION_ENUMS",
    "LabelMismatch",
    "MetricsConfig",
    "PolicyMatrix",
    "PolicyRule",
    "RISK_ATTRIBUTES",
    "RiskModelConfig",
    "ThresholdConfig",
    "load_policy_matrix",
    "load_final_scenarios",
    "load_scenarios",
    "load_yaml_mapping",
    "project_binary_baseline_rules",
    "validate_ground_truth_against_matrix",
]

#: Risk components of ``R = w_s*S + w_a*A + w_e*E + w_c*C`` (draft section III.D).
COMPONENT_KEYS: tuple[str, ...] = (
    "sensitivity",
    "action_severity",
    "exposure_scope",
    "contextual_risk",
)

#: Attributes considered by the binary ABAC baseline (draft section IV.D).
ABAC_ATTRIBUTES: tuple[str, ...] = ("role", "tool", "sensitivity", "destination")

#: Supported provenances for the baseline rule set (draft section IV.D).
#:
#: ``explicit``
#:     The binary rules are authored directly under ``abac_baseline.rules``.
#: ``ground_truth_projection``
#:     The binary rules are derived deterministically from the independent
#:     ``ground_truth_matrix`` by :func:`project_binary_baseline_rules`: the
#:     baseline is the same security policy evaluated on the four attributes it
#:     can observe, with the ground-truth ``ESCALATE`` state collapsed because a
#:     binary mechanism has no third outcome.
ABAC_RULES_SOURCES: tuple[str, ...] = ("explicit", "ground_truth_projection")

#: Prefix applied to rules produced by :func:`project_binary_baseline_rules`.
ABAC_PROJECTED_RULE_PREFIX = "ABAC-"

#: Decisions a binary mechanism is allowed to emit.
_BINARY_DECISIONS: frozenset[Decision] = frozenset({Decision.ALLOW, Decision.DENY})


#: Attributes a ground-truth or ABAC rule may constrain.
RISK_ATTRIBUTES: tuple[str, ...] = (
    "role",
    "tool",
    "sensitivity",
    "destination",
    "context_risk",
)

DEFAULT_DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
DEFAULT_POLICY_MATRIX_PATH: Path = DEFAULT_DATA_DIR / "policy_matrix.yaml"
DEFAULT_SCENARIOS_PATH: Path = DEFAULT_DATA_DIR / "scenarios.yaml"
DEFAULT_PILOT_SCENARIOS_PATH: Path = DEFAULT_DATA_DIR / "pilot_scenarios.yaml"


# --------------------------------------------------------------------------- #
# Generic YAML helpers
# --------------------------------------------------------------------------- #


def load_yaml_mapping(path: str | Path) -> Mapping[str, Any]:
    """Load a YAML file that must contain a top-level mapping."""
    resolved = Path(path)
    if not resolved.is_file():
        raise ConfigurationError(f"configuration file not found: {resolved}")
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML in {resolved}: {exc}") from exc
    if raw is None:
        raise ConfigurationError(f"{resolved} is empty; a YAML mapping is required")
    if not isinstance(raw, Mapping):
        raise ConfigurationError(
            f"{resolved} must contain a top-level mapping, got {type(raw).__name__}"
        )
    return raw


def _require_section(
    document: Mapping[str, Any], key: str, path: Path
) -> Mapping[str, Any]:
    section = document.get(key)
    if section is None:
        raise ConfigurationError(
            f"{path} is missing the required top-level section '{key}'"
        )
    if not isinstance(section, Mapping):
        raise ConfigurationError(
            f"{path}: section '{key}' must be a mapping, got {type(section).__name__}"
        )
    return section


def _optional_float(value: Any, *, where: str) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"{where} must be a number or null, got {value!r}"
        ) from exc
    return numeric


def _as_sequence(value: Any, *, where: str) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return value
    raise ConfigurationError(f"{where} must be a list, got {type(value).__name__}")


# --------------------------------------------------------------------------- #
# Policy rules
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """A single deterministic rule from either authored matrix.

    ``match`` maps an attribute name (see :data:`RISK_ATTRIBUTES`) to the set of
    accepted values, or to ``None`` meaning "any value of this attribute".  Rules
    are evaluated in file order with first-match-wins semantics; ``priority`` is
    available for explicit ordering when a matrix is later reordered.
    """

    rule_id: str
    decision: Decision
    match: Mapping[str, frozenset[str] | None]
    description: str = ""
    rationale: str = ""
    priority: int = 0
    source_order: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not self.rule_id.strip():
            raise ValueError("rule_id must be a non-empty string")
        normalised: dict[str, frozenset[str] | None] = {}
        for attribute, values in dict(self.match).items():
            if attribute not in RISK_ATTRIBUTES:
                raise ValueError(
                    f"rule {self.rule_id}: unknown matching attribute "
                    f"'{attribute}'; allowed attributes are "
                    f"{', '.join(RISK_ATTRIBUTES)}"
                )
            if values is None:
                normalised[attribute] = None
                continue
            canonical = frozenset(
                str(value).strip().upper().replace("-", "_").replace(" ", "_")
                for value in _as_sequence(
                    values, where=f"rule {self.rule_id}.{attribute}"
                )
            )
            if not canonical:
                raise ValueError(
                    f"rule {self.rule_id}: empty value list for '{attribute}'; "
                    "use null to match any value"
                )
            normalised[attribute] = canonical
        object.__setattr__(self, "match", normalised)

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], *, source_order: int = 0
    ) -> "PolicyRule":
        if not isinstance(data, Mapping):
            raise ConfigurationError(
                f"policy rule must be a mapping, got {type(data).__name__}"
            )
        allowed_keys = {
            "rule_id",
            "decision",
            "match",
            "description",
            "rationale",
            "priority",
        }
        unknown = sorted(set(data) - allowed_keys)
        if unknown:
            raise ConfigurationError(
                f"policy rule {data.get('rule_id')!r} contains unknown key(s): "
                f"{', '.join(unknown)}"
            )
        for key in ("rule_id", "decision", "match"):
            if key not in data:
                raise ConfigurationError(
                    f"policy rule {data.get('rule_id')!r} is missing required "
                    f"key '{key}'"
                )
        if data["decision"] is None:
            raise ConfigurationError(
                f"policy rule {data['rule_id']!r} has no decision; author a "
                "decision before the rule can be used"
            )
        try:
            decision = Decision(data["decision"])
        except ValueError as exc:
            raise ConfigurationError(f"policy rule {data['rule_id']!r}: {exc}") from exc
        match = data["match"]
        if not isinstance(match, Mapping):
            raise ConfigurationError(
                f"policy rule {data['rule_id']!r}: 'match' must be a mapping"
            )
        try:
            return cls(
                rule_id=str(data["rule_id"]),
                decision=decision,
                match=match,
                description=str(data.get("description") or ""),
                rationale=str(data.get("rationale") or ""),
                priority=int(data.get("priority") or 0),
                source_order=source_order,
            )
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc

    def matches(self, scenario: Scenario) -> bool:
        """``True`` when every constrained attribute of ``scenario`` is accepted."""
        for attribute, allowed in self.match.items():
            if allowed is None:
                continue
            actual = str(getattr(scenario, attribute)).strip().upper()
            if actual not in allowed:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "decision": self.decision.value,
            "match": {
                attribute: None if values is None else sorted(values)
                for attribute, values in self.match.items()
            },
            "description": self.description,
            "rationale": self.rationale,
            "priority": self.priority,
        }


def _load_rules(rules: Any, *, where: str) -> tuple[PolicyRule, ...]:
    parsed = tuple(
        PolicyRule.from_dict(entry, source_order=index)
        for index, entry in enumerate(_as_sequence(rules, where=where))
    )
    seen: set[str] = set()
    for rule in parsed:
        if rule.rule_id in seen:
            raise ConfigurationError(f"{where}: duplicate rule_id '{rule.rule_id}'")
        seen.add(rule.rule_id)
    return tuple(sorted(parsed, key=lambda rule: (rule.priority, rule.source_order)))
# --------------------------------------------------------------------------- #
# Risk model configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RiskModelConfig:
    """Weights and ordinal mappings of ``R = w_s*S + w_a*A + w_e*E + w_c*C``.

    Every numeric value here is an experiment input that must be authored and
    locked *before* the primary experiment is run.  Unset values are ``None`` and
    are reported by :meth:`missing_items`; using them raises
    :class:`~src.models.ConfigurationError`.
    """

    formula: str
    weights: Mapping[str, float | None]
    factor_mappings: Mapping[str, Mapping[str, float | None]]
    component_dimensions: Mapping[str, str]
    weight_locked: bool = False

    def __post_init__(self) -> None:
        unknown_weights = sorted(set(self.weights) - set(COMPONENT_KEYS))
        missing_weights = [key for key in COMPONENT_KEYS if key not in self.weights]
        if unknown_weights or missing_weights:
            raise ConfigurationError(
                "risk_model.weights must define exactly the components "
                f"{', '.join(COMPONENT_KEYS)} (unknown: {unknown_weights or 'none'}, "
                f"missing: {missing_weights or 'none'})"
            )
        unknown_mappings = sorted(set(self.factor_mappings) - set(COMPONENT_KEYS))
        missing_mappings = [
            key for key in COMPONENT_KEYS if key not in self.factor_mappings
        ]
        if unknown_mappings or missing_mappings:
            raise ConfigurationError(
                "risk_model.factor_mappings must define exactly the components "
                f"{', '.join(COMPONENT_KEYS)} (unknown: "
                f"{unknown_mappings or 'none'}, missing: {missing_mappings or 'none'})"
            )
        unknown_dimensions = sorted(
            set(self.component_dimensions) - set(COMPONENT_KEYS)
        )
        if unknown_dimensions:
            raise ConfigurationError(
                "risk_model.component_sources contains unknown component(s): "
                f"{', '.join(unknown_dimensions)}"
            )
        for component in COMPONENT_KEYS:
            if component not in self.component_dimensions:
                raise ConfigurationError(
                    f"risk_model.component_sources is missing '{component}'"
                )
        object.__setattr__(self, "weights", dict(self.weights))
        object.__setattr__(
            self,
            "factor_mappings",
            {key: dict(value) for key, value in self.factor_mappings.items()},
        )
        object.__setattr__(
            self, "component_dimensions", dict(self.component_dimensions)
        )
        self._validate_set_weights()

    def _validate_set_weights(self) -> None:
        authored = {k: v for k, v in self.weights.items() if v is not None}
        if len(authored) != len(COMPONENT_KEYS):
            return
        negative = sorted(k for k, v in authored.items() if v < 0)
        if negative:
            raise ConfigurationError(
                "risk_model.weights must be non-negative; offending component(s): "
                f"{', '.join(negative)}"
            )
        total = sum(authored.values())
        if abs(total - 1.0) > 1e-9:
            raise ConfigurationError(
                "risk_model.weights must sum to 1.0 as specified in the "
                f"manuscript, but they sum to {total!r}"
            )

    def validate_against_dimensions(
        self, dimensions: Mapping[str, tuple[str, ...]]
    ) -> None:
        """Check that every mapping enumerates exactly its source dimension."""
        for component in COMPONENT_KEYS:
            dimension = self.component_dimensions[component]
            if dimension not in dimensions:
                raise ConfigurationError(
                    f"risk_model.component_sources.{component} refers to unknown "
                    f"dimension '{dimension}'"
                )
            expected = set(dimensions[dimension])
            actual = set(self.factor_mappings[component])
            unexpected = sorted(actual - expected)
            absent = sorted(expected - actual)
            if unexpected or absent:
                raise ConfigurationError(
                    f"risk_model.factor_mappings.{component} must enumerate exactly "
                    f"the '{dimension}' values (unexpected: {unexpected or 'none'}, "
                    f"absent: {absent or 'none'})"
                )

    # -- completeness ----------------------------------------------------- #

    def missing_items(self) -> tuple[str, ...]:
        """Return the YAML paths of every value that still has to be authored."""
        missing: list[str] = []
        for component in COMPONENT_KEYS:
            if self.weights.get(component) is None:
                missing.append(f"risk_model.weights.{component}")
        for component in COMPONENT_KEYS:
            for value, mapped in self.factor_mappings[component].items():
                if mapped is None:
                    missing.append(f"risk_model.factor_mappings.{component}.{value}")
        if not self.weight_locked:
            missing.append("risk_model.weight_locked (set to true once locked)")
        return tuple(missing)

    @property
    def is_complete(self) -> bool:
        return not self.missing_items()

    # -- accessors -------------------------------------------------------- #

    def locked_weights(self) -> dict[str, float]:
        """Return the authored weights, refusing to run with unset values."""
        missing = [key for key in COMPONENT_KEYS if self.weights.get(key) is None]
        if missing:
            raise ConfigurationError(
                "risk weights are not locked yet; author "
                + ", ".join(f"risk_model.weights.{key}" for key in missing)
                + " in data/policy_matrix.yaml (values must sum to 1.0, "
                "draft section III.D)"
            )
        return {key: float(self.weights[key]) for key in COMPONENT_KEYS}

    def locked_mapping(self, component: str) -> dict[str, float]:
        """Return the authored ordinal mapping for one risk component."""
        if component not in COMPONENT_KEYS:
            raise ValueError(f"unknown risk component '{component}'")
        mapping = self.factor_mappings[component]
        missing = sorted(key for key, value in mapping.items() if value is None)
        if missing:
            raise ConfigurationError(
                f"risk_model.factor_mappings.{component} is not authored yet; "
                "missing value(s): " + ", ".join(missing)
            )
        return {key: float(value) for key, value in mapping.items()}

    def factor_value(self, component: str, member: object) -> float:
        """Look up the normalized factor value of an enum member."""
        mapping = self.factor_mappings.get(component)
        if mapping is None:
            raise ConfigurationError(f"unknown risk component '{component}'")
        key = str(member).strip().upper()
        if key not in mapping:
            raise ConfigurationError(
                f"risk_model.factor_mappings.{component} has no entry for '{key}'"
            )
        value = mapping[key]
        if value is None:
            raise ConfigurationError(
                f"risk_model.factor_mappings.{component}.{key} is not authored yet "
                "(the primary experiment must not substitute a default mapping)"
            )
        return float(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "formula": self.formula,
            "weights": dict(self.weights),
            "factor_mappings": {
                key: dict(value) for key, value in self.factor_mappings.items()
            },
            "component_sources": dict(self.component_dimensions),
            "weight_locked": self.weight_locked,
        }
# --------------------------------------------------------------------------- #
# Threshold configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ThresholdConfig:
    """Escalation (``T1``) and denial (``T2``) thresholds of the three-way rule.

    ``T1`` and ``T2`` are preregistered experiment inputs; ``None`` means "not
    yet selected".  ``sensitivity_grid`` records the ranges used by the threshold
    sensitivity analysis.  Those numbers come from the manuscript draft
    (section IV.G) and are explicitly *not* the preregistered primary pair.
    """

    t1: float | None = None
    t2: float | None = None
    preregistered: bool = False
    sensitivity_grid: Mapping[str, tuple[float, ...]] = field(default_factory=dict)
    grid_source: str = ""

    def __post_init__(self) -> None:
        if self.t1 is not None:
            object.__setattr__(self, "t1", self._unit("T1_escalation", self.t1))
        if self.t2 is not None:
            object.__setattr__(self, "t2", self._unit("T2_denial", self.t2))
        if self.t1 is not None and self.t2 is not None and self.t1 >= self.t2:
            raise ConfigurationError(
                "thresholds must satisfy T1 < T2 "
                f"(got T1={self.t1!r}, T2={self.t2!r})"
            )
        object.__setattr__(
            self,
            "sensitivity_grid",
            {
                key: tuple(float(value) for value in values)
                for key, values in dict(self.sensitivity_grid).items()
            },
        )

    @staticmethod
    def _unit(name: str, value: float) -> float:
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ConfigurationError(
                f"thresholds.{name} must lie in [0.0, 1.0], got {numeric!r}"
            )
        return numeric

    def missing_items(self) -> tuple[str, ...]:
        missing: list[str] = []
        if self.t1 is None:
            missing.append("thresholds.T1_escalation")
        if self.t2 is None:
            missing.append("thresholds.T2_denial")
        if not self.preregistered:
            missing.append("thresholds.preregistered (set to true once locked)")
        return tuple(missing)

    @property
    def is_complete(self) -> bool:
        return not self.missing_items()

    def locked_thresholds(self) -> tuple[float, float]:
        """Return ``(T1, T2)`` or fail loudly if they are not preregistered."""
        missing: list[str] = []
        if self.t1 is None:
            missing.append("thresholds.T1_escalation")
        if self.t2 is None:
            missing.append("thresholds.T2_denial")
        if missing:
            raise ConfigurationError(
                "authorization thresholds are not preregistered yet; author "
                + ", ".join(missing)
                + " in data/policy_matrix.yaml (see draft section III.E)"
            )
        assert self.t1 is not None and self.t2 is not None
        return self.t1, self.t2

    def grid_combinations(self) -> tuple[tuple[float, float], ...]:
        """Return the ``T1 < T2`` pairs of the sensitivity grid, in grid order."""
        t1_values = self.sensitivity_grid.get("T1", ())
        t2_values = self.sensitivity_grid.get("T2", ())
        return tuple((t1, t2) for t1 in t1_values for t2 in t2_values if t1 < t2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "T1_escalation": self.t1,
            "T2_denial": self.t2,
            "preregistered": self.preregistered,
            "sensitivity_grid": {
                key: list(values) for key, values in self.sensitivity_grid.items()
            },
            "grid_source": self.grid_source,
        }


# --------------------------------------------------------------------------- #
# Metrics configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class MetricsConfig:
    """Authored inputs required to compute the evaluation metrics.

    The manuscript defines the unnecessary-escalation rate over "low-risk
    legitimate actions" (section IV.E.3) without fixing what counts as low risk.
    That designation is therefore an authoring input, recorded here and left
    unset until it is decided.  ``None`` values mean the corresponding metric
    cannot be computed yet -- the analysis reports that fact instead of choosing
    a definition on the reader's behalf.
    """

    low_risk_definition: str | None = None
    low_risk_context_risks: tuple[ContextRisk, ...] | None = None
    low_risk_max_score: float | None = None
    source: str = ""

    def __post_init__(self) -> None:
        if self.low_risk_context_risks is not None:
            object.__setattr__(
                self,
                "low_risk_context_risks",
                tuple(
                    ContextRisk(value) for value in self.low_risk_context_risks
                ),
            )
        if self.low_risk_max_score is not None:
            object.__setattr__(
                self,
                "low_risk_max_score",
                ThresholdConfig._unit("metrics.low_risk_max_score", self.low_risk_max_score),
            )

    @property
    def is_low_risk_defined(self) -> bool:
        return bool(
            self.low_risk_definition
            or self.low_risk_context_risks
            or self.low_risk_max_score is not None
        )

    def missing_items(self) -> tuple[str, ...]:
        if self.is_low_risk_defined:
            return ()
        return (
            "metrics.low_risk_definition (needed by the unnecessary-escalation rate)",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "low_risk_definition": self.low_risk_definition,
            "low_risk_context_risks": (
                None
                if self.low_risk_context_risks is None
                else [value.value for value in self.low_risk_context_risks]
            ),
            "low_risk_max_score": self.low_risk_max_score,
            "source": self.source,
        }


# --------------------------------------------------------------------------- #
# ABAC baseline configuration
# --------------------------------------------------------------------------- #


def project_binary_baseline_rules(
    ground_truth_rules: Sequence[PolicyRule],
    *,
    escalation_collapse: Decision,
    context_assumption: ContextRisk,
    attributes: Sequence[str] = ABAC_ATTRIBUTES,
) -> tuple[PolicyRule, ...]:
    """Derive the binary baseline rule set from the ground-truth policy matrix.

    The binary baseline is defined here as the *same* independently authored
    security policy evaluated on the four attributes a binary mechanism can
    observe (``role``, ``tool``, ``sensitivity``, ``destination``).  The
    projection is a pure function of the ground-truth rules and two authored
    design decisions:

    ``escalation_collapse``
        The binary outcome substituted for the ground-truth ``ESCALATE`` state.
        A binary mechanism has no third outcome, so every escalation rule is
        forced to ``ALLOW`` or ``DENY``.  This is a policy decision and is
        therefore authored in ``data/policy_matrix.yaml`` rather than chosen by
        the code.  Ground-truth ``ESCALATE`` scenarios are *not* removed from
        evaluation: they are still authorized by the baseline and their forced
        resolution is recorded per scenario by :mod:`src.evaluator`.

    ``context_assumption``
        The baseline cannot observe the supplied contextual condition, so it
        evaluates the policy as if that condition held its benign level.  Rules
        that only fire on a *detected* contextual deviation (``UNUSUAL``,
        ``HIGH_VOLUME``, ``ANOMALOUS``) are therefore inapplicable to it and are
        not projected, whereas rules written for the benign level remain
        applicable.

    The projection never consults a scenario label, a risk score, a weight, a
    threshold or a language model, and it is deterministic: the same ground-truth
    matrix and the same two authored values always produce the same binary rule
    set.  Precedence is preserved (hard ``DENY``, then the collapsed escalation
    boundary, then routine ``ALLOW``) so that the baseline resolves conflicts
    exactly as the ground-truth policy does.
    """
    collapse = Decision(escalation_collapse)
    if collapse not in _BINARY_DECISIONS:
        raise ConfigurationError(
            "abac_baseline.escalation_collapse must be ALLOW or DENY for a binary "
            f"baseline, got {collapse.value}"
        )
    assumption = ContextRisk(context_assumption)
    permitted = tuple(str(name) for name in attributes)
    unknown = sorted(set(permitted) - set(ABAC_ATTRIBUTES))
    if unknown:
        raise ConfigurationError(
            "abac_baseline.attributes contains unsupported attribute(s): "
            f"{', '.join(unknown)}"
        )
    permitted_set = set(permitted)

    projected: list[PolicyRule] = []
    for rule in ground_truth_rules:
        match = {
            attribute: (None if values is None else sorted(values))
            for attribute, values in rule.match.items()
            if attribute in permitted_set
        }
        if not match:
            # A catch-all rule, or a rule conditioned on context alone, carries no
            # signal for a mechanism that evaluates the four binary attributes.
            # Unmatched scenarios are covered by ``default_decision``.
            continue
        contextual = rule.match.get("context_risk")
        if contextual is not None and assumption.value not in contextual:
            # The baseline cannot detect the contextual deviation this rule
            # depends on, so the rule is inapplicable to it.
            continue
        if rule.decision is Decision.ESCALATE:
            decision = collapse
            description = (
                f"projected from ground-truth rule {rule.rule_id}; the ground-truth "
                "ESCALATE state does not exist in a binary mechanism and is forced "
                f"to {decision.value}"
            )
        else:
            decision = rule.decision
            description = f"projected from ground-truth rule {rule.rule_id}"
        projected.append(
            PolicyRule(
                rule_id=f"{ABAC_PROJECTED_RULE_PREFIX}{rule.rule_id}",
                decision=decision,
                match=match,
                description=description,
                rationale=rule.rationale,
                priority=rule.priority,
                source_order=rule.source_order,
            )
        )
    return tuple(
        sorted(projected, key=lambda rule: (rule.priority, rule.source_order))
    )


@dataclass(frozen=True, slots=True)
class ABACConfig:
    """Deterministic binary attribute-based baseline (draft section IV.D).

    The baseline evaluates role, tool, resource sensitivity and destination, and
    emits only ``ALLOW`` or ``DENY``.  ``default_decision`` is the authored
    outcome for scenarios matched by no rule; it must be authored too, because
    choosing a fallback on the experimenter's behalf would be a policy decision.

    ``rules_source`` records where the binary rule set came from:

    * ``"explicit"`` -- authored directly under ``abac_baseline.rules``;
    * ``"ground_truth_projection"`` -- derived by
      :func:`project_binary_baseline_rules` from the independent ground-truth
      matrix, using the authored ``escalation_collapse`` and
      ``context_assumption`` design decisions.

    The baseline has no escalation state by construction: the ground truth may be
    ``ESCALATE``, but ``rules``, ``default_decision`` and every emitted decision
    are restricted to ``ALLOW``/``DENY``.
    """

    rules: tuple[PolicyRule, ...] = ()
    default_decision: Decision | None = None
    binary_only: bool = True
    attributes: tuple[str, ...] = ABAC_ATTRIBUTES
    description: str = ""
    rules_source: str = "explicit"
    escalation_collapse: Decision | None = None
    context_assumption: ContextRisk | None = None

    def __post_init__(self) -> None:
        if not self.binary_only:
            raise ConfigurationError(
                "abac_baseline.binary_only must be true; the baseline supports "
                "ALLOW/DENY only"
            )
        if self.default_decision is not None:
            object.__setattr__(
                self,
                "default_decision",
                Decision(self.default_decision),
            )
        if self.escalation_collapse is not None:
            collapse = Decision(self.escalation_collapse)
            if collapse not in _BINARY_DECISIONS:
                raise ConfigurationError(
                    "abac_baseline.escalation_collapse must be ALLOW or DENY for a "
                    f"binary baseline, got {collapse.value}"
                )
            object.__setattr__(self, "escalation_collapse", collapse)
        if self.context_assumption is not None:
            object.__setattr__(
                self,
                "context_assumption",
                ContextRisk(self.context_assumption),
            )
        if self.rules_source not in ABAC_RULES_SOURCES:
            raise ConfigurationError(
                "abac_baseline.rules_source must be one of "
                f"{', '.join(ABAC_RULES_SOURCES)} (got {self.rules_source!r})"
            )
        unknown = sorted(set(self.attributes) - set(ABAC_ATTRIBUTES))
        if unknown:
            raise ConfigurationError(
                f"abac_baseline.attributes contains unsupported attribute(s): "
                f"{', '.join(unknown)}"
            )
        permitted = set(self.attributes)
        for rule in self.rules:
            outside = sorted(set(rule.match) - permitted)
            if outside:
                raise ConfigurationError(
                    f"abac_baseline rule {rule.rule_id!r} matches on "
                    f"{', '.join(outside)}, which the binary baseline does not "
                    f"evaluate (it evaluates {', '.join(self.attributes)})"
                )
        if self.binary_only:
            non_binary = sorted(
                {
                    rule.decision.value
                    for rule in self.rules
                    if rule.decision is not Decision.ALLOW
                    and rule.decision is not Decision.DENY
                }
            )
            if non_binary:
                raise ConfigurationError(
                    "abac_baseline.binary_only is true but rule(s) use the "
                    f"non-binary decision(s): {', '.join(non_binary)}"
                )
            if (
                self.default_decision is not None
                and self.default_decision is not Decision.ALLOW
                and self.default_decision is not Decision.DENY
            ):
                raise ConfigurationError(
                    "abac_baseline.default_decision must be ALLOW or DENY for a "
                    f"binary baseline, got {self.default_decision.value}"
                )

    def missing_items(self) -> tuple[str, ...]:
        missing: list[str] = []
        if not self.rules:
            if self.rules_source == "ground_truth_projection":
                missing.append(
                    "abac_baseline.rules (the projection produced no binary rule; "
                    "check ground_truth_matrix.rules)"
                )
            else:
                missing.append("abac_baseline.rules (no baseline rule authored yet)")
        if self.default_decision is None:
            missing.append("abac_baseline.default_decision")
        if self.rules_source == "ground_truth_projection":
            if self.escalation_collapse is None:
                missing.append("abac_baseline.escalation_collapse")
            if self.context_assumption is None:
                missing.append("abac_baseline.context_assumption")
        return tuple(missing)

    @property
    def is_complete(self) -> bool:
        return not self.missing_items()

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "binary_only": self.binary_only,
            "attributes": list(self.attributes),
            "rules_source": self.rules_source,
            "escalation_collapse": (
                self.escalation_collapse.value if self.escalation_collapse else None
            ),
            "context_assumption": (
                self.context_assumption.value if self.context_assumption else None
            ),
            "default_decision": (
                self.default_decision.value if self.default_decision else None
            ),
            "rules": [rule.to_dict() for rule in self.rules],
        }


# --------------------------------------------------------------------------- #
# Policy matrix aggregate
# --------------------------------------------------------------------------- #


DIMENSION_ENUMS: Mapping[str, Any] = {
    "role": Role,
    "tool": Tool,
    "sensitivity": Sensitivity,
    "destination": Destination,
    "context_risk": ContextRisk,
}


@dataclass(frozen=True, slots=True)
class PolicyMatrix:
    """Everything authored in ``data/policy_matrix.yaml``."""

    source_path: Path
    risk_model: RiskModelConfig
    thresholds: ThresholdConfig
    abac: ABACConfig
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    dimensions: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    ground_truth_rules: tuple[PolicyRule, ...] = ()
    schema_version: str = ""
    status: str = "unknown"
    locked_for_primary_experiment: bool = False
    notes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_path", Path(self.source_path))
        object.__setattr__(self, "dimensions", dict(self.dimensions))
        object.__setattr__(self, "notes", dict(self.notes))

    # -- ground-truth labels --------------------------------------------- #

    def ground_truth_for(self, scenario: Scenario) -> Decision | None:
        """First matching ground-truth rule outcome, or ``None`` if unmatched."""
        for rule in self.ground_truth_rules:
            if rule.matches(scenario):
                return rule.decision
        return None

    # -- readiness -------------------------------------------------------- #

    def missing_authoring_items(self) -> tuple[str, ...]:
        """All configuration that must be authored before the primary experiment."""
        missing: list[str] = list(self.risk_model.missing_items())
        missing.extend(self.thresholds.missing_items())
        missing.extend(self.abac.missing_items())
        if not self.ground_truth_rules:
            missing.append("ground_truth_matrix.rules (no label rule authored yet)")
        return tuple(missing)

    @property
    def is_ready_for_primary_experiment(self) -> bool:
        return not self.missing_authoring_items()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "schema_version": self.schema_version,
            "status": self.status,
            "locked_for_primary_experiment": self.locked_for_primary_experiment,
            "dimensions": {key: list(values) for key, values in self.dimensions.items()},
            "ground_truth_rules": [rule.to_dict() for rule in self.ground_truth_rules],
            "risk_model": self.risk_model.to_dict(),
            "thresholds": self.thresholds.to_dict(),
            "abac_baseline": self.abac.to_dict(),
            "metrics": self.metrics.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class LabelMismatch:
    """A scenario whose label disagrees with the authored ground-truth matrix."""

    scenario_id: str
    declared: Decision
    from_matrix: Decision | None
    reason: str

    def describe(self) -> str:
        expected = self.from_matrix.value if self.from_matrix else "<no rule matched>"
        return (
            f"{self.scenario_id}: declared {self.declared.value} but matrix yields "
            f"{expected} ({self.reason})"
        )


# --------------------------------------------------------------------------- #
# Loading and validation
# --------------------------------------------------------------------------- #


def _load_dimensions(
    document: Mapping[str, Any], path: Path
) -> dict[str, tuple[str, ...]]:
    """Read the dimension block and check it against the code-level enums."""
    section = _require_section(document, "dimensions", path)
    dimensions: dict[str, tuple[str, ...]] = {}
    for name, enum_type in DIMENSION_ENUMS.items():
        declared = section.get(name)
        if declared is None:
            raise ConfigurationError(f"{path}: dimensions.{name} is not declared")
        values = tuple(
            str(value).strip().upper().replace("-", "_").replace(" ", "_")
            for value in _as_sequence(declared, where=f"dimensions.{name}")
        )
        expected = tuple(member.value for member in enum_type)
        if set(values) != set(expected):
            raise ConfigurationError(
                f"{path}: dimensions.{name} must enumerate exactly "
                f"{', '.join(expected)} (got {', '.join(values) or 'nothing'})"
            )
        dimensions[name] = expected
    return dimensions


def _load_risk_model(document: Mapping[str, Any], path: Path) -> RiskModelConfig:
    """Build the risk-model configuration from the ``risk_model`` section."""
    section = _require_section(document, "risk_model", path)
    weights_raw = section.get("weights")
    if not isinstance(weights_raw, Mapping):
        raise ConfigurationError(f"{path}: risk_model.weights must be a mapping")
    mappings_raw = section.get("factor_mappings")
    if not isinstance(mappings_raw, Mapping):
        raise ConfigurationError(
            f"{path}: risk_model.factor_mappings must be a mapping"
        )
    sources_raw = section.get("component_sources") or {
        component: component for component in COMPONENT_KEYS
    }
    if not isinstance(sources_raw, Mapping):
        raise ConfigurationError(
            f"{path}: risk_model.component_sources must be a mapping"
        )
    factor_mappings: dict[str, dict[str, float | None]] = {}
    for component in COMPONENT_KEYS:
        entries = mappings_raw.get(component)
        if not isinstance(entries, Mapping):
            raise ConfigurationError(
                f"{path}: risk_model.factor_mappings.{component} must be a mapping"
            )
        factor_mappings[component] = {
            str(key).strip().upper().replace("-", "_").replace(" ", "_"): _optional_float(
                value, where=f"risk_model.factor_mappings.{component}.{key}"
            )
            for key, value in entries.items()
        }
    return RiskModelConfig(
        formula=str(section.get("formula") or ""),
        weights={
            str(key): _optional_float(value, where=f"risk_model.weights.{key}")
            for key, value in weights_raw.items()
        },
        factor_mappings=factor_mappings,
        component_dimensions={
            str(key): str(value) for key, value in sources_raw.items()
        },
        weight_locked=bool(section.get("weight_locked") or False),
    )


def _load_thresholds(document: Mapping[str, Any], path: Path) -> ThresholdConfig:
    """Build the threshold configuration, including the sensitivity grid."""
    section = _require_section(document, "thresholds", path)
    grid_raw = section.get("sensitivity_grid") or {}
    if not isinstance(grid_raw, Mapping):
        raise ConfigurationError(
            f"{path}: thresholds.sensitivity_grid must be a mapping"
        )
    grid = {
        str(key): tuple(
            float(value)
            for value in _as_sequence(
                values, where=f"thresholds.sensitivity_grid.{key}"
            )
        )
        for key, values in grid_raw.items()
    }
    return ThresholdConfig(
        t1=_optional_float(
            section.get("T1_escalation"), where="thresholds.T1_escalation"
        ),
        t2=_optional_float(section.get("T2_denial"), where="thresholds.T2_denial"),
        preregistered=bool(section.get("preregistered") or False),
        sensitivity_grid=grid,
        grid_source=str(section.get("grid_source") or ""),
    )


def _load_abac(
    document: Mapping[str, Any],
    path: Path,
    *,
    ground_truth_rules: Sequence[PolicyRule],
) -> ABACConfig:
    """Build the deterministic binary baseline configuration.

    ``ground_truth_rules`` is required because ``rules_source:
    ground_truth_projection`` derives the binary rule set from the independent
    ground-truth matrix.  The two design decisions that drive the projection
    (``escalation_collapse`` and ``context_assumption``) must be authored
    explicitly; the loader never substitutes a default for them.
    """
    section = _require_section(document, "abac_baseline", path)
    attributes = tuple(section.get("attributes") or ABAC_ATTRIBUTES)
    rules_source = str(section.get("rules_source") or "explicit")
    if rules_source not in ABAC_RULES_SOURCES:
        raise ConfigurationError(
            f"{path}: abac_baseline.rules_source must be one of "
            f"{', '.join(ABAC_RULES_SOURCES)} (got {rules_source!r})"
        )
    raw_default = section.get("default_decision")
    try:
        default_decision = Decision(raw_default) if raw_default is not None else None
    except ValueError as exc:
        raise ConfigurationError(
            f"{path}: abac_baseline.default_decision: {exc}"
        ) from exc
    raw_collapse = section.get("escalation_collapse")
    try:
        escalation_collapse = (
            Decision(raw_collapse) if raw_collapse is not None else None
        )
    except ValueError as exc:
        raise ConfigurationError(
            f"{path}: abac_baseline.escalation_collapse: {exc}"
        ) from exc
    raw_assumption = section.get("context_assumption")
    try:
        context_assumption = (
            ContextRisk(raw_assumption) if raw_assumption is not None else None
        )
    except ValueError as exc:
        raise ConfigurationError(
            f"{path}: abac_baseline.context_assumption: {exc}"
        ) from exc

    authored_rules = _load_rules(
        section.get("rules"), where=f"{path}: abac_baseline.rules"
    )

    if rules_source == "ground_truth_projection":
        if escalation_collapse is None:
            raise ConfigurationError(
                f"{path}: abac_baseline.escalation_collapse must be authored "
                "(ALLOW or DENY) when abac_baseline.rules_source is "
                "'ground_truth_projection'; a binary mechanism cannot represent "
                "the ground-truth ESCALATE state"
            )
        if context_assumption is None:
            raise ConfigurationError(
                f"{path}: abac_baseline.context_assumption must be authored when "
                "abac_baseline.rules_source is 'ground_truth_projection'; the "
                "baseline cannot observe context and must state the level it "
                "assumes"
            )
        combined = (
            project_binary_baseline_rules(
                ground_truth_rules,
                escalation_collapse=escalation_collapse,
                context_assumption=context_assumption,
                attributes=attributes,
            )
            + authored_rules
        )
        seen: set[str] = set()
        for rule in combined:
            if rule.rule_id in seen:
                raise ConfigurationError(
                    f"{path}: abac_baseline.rules: duplicate rule_id "
                    f"'{rule.rule_id}' after projection"
                )
            seen.add(rule.rule_id)
        rules = tuple(sorted(combined, key=lambda rule: (rule.priority, rule.source_order)))
    else:
        rules = authored_rules

    return ABACConfig(
        rules=rules,
        default_decision=default_decision,
        binary_only=bool(section.get("binary_only", True)),
        attributes=attributes,
        description=str(section.get("description") or ""),
        rules_source=rules_source,
        escalation_collapse=escalation_collapse,
        context_assumption=context_assumption,
    )


def _load_metrics(document: Mapping[str, Any], path: Path) -> MetricsConfig:
    """Build the metrics configuration (currently: the low-risk designation)."""
    raw = document.get("metrics") or {}
    if not isinstance(raw, Mapping):
        raise ConfigurationError(f"{path}: 'metrics' must be a mapping")
    risks = raw.get("low_risk_context_risks")
    parsed_risks: tuple[ContextRisk, ...] | None
    if risks is None:
        parsed_risks = None
    else:
        try:
            parsed_risks = tuple(
                ContextRisk(value)
                for value in _as_sequence(
                    risks, where="metrics.low_risk_context_risks"
                )
            )
        except ValueError as exc:
            raise ConfigurationError(f"{path}: metrics.low_risk_context_risks: {exc}") from exc
    return MetricsConfig(
        low_risk_definition=(
            str(raw["low_risk_definition"])
            if raw.get("low_risk_definition")
            else None
        ),
        low_risk_context_risks=parsed_risks,
        low_risk_max_score=_optional_float(
            raw.get("low_risk_max_score"), where="metrics.low_risk_max_score"
        ),
        source=str(raw.get("source") or ""),
    )


def load_policy_matrix(
    path: str | Path = DEFAULT_POLICY_MATRIX_PATH,
) -> PolicyMatrix:
    """Load and validate ``data/policy_matrix.yaml``.

    Structural problems raise :class:`~src.models.ConfigurationError`.  Values
    that have simply not been authored yet (weights, mappings, thresholds, rules)
    are *not* an error here: they are reported through
    :meth:`PolicyMatrix.missing_authoring_items` so that the preflight check can
    list exactly what is outstanding.
    """
    resolved = Path(path)
    document = load_yaml_mapping(resolved)
    meta = document.get("_meta") or {}
    if not isinstance(meta, Mapping):
        raise ConfigurationError(f"{resolved}: '_meta' must be a mapping")

    dimensions = _load_dimensions(document, resolved)
    risk_model = _load_risk_model(document, resolved)
    risk_model.validate_against_dimensions(dimensions)
    ground_truth = _require_section(document, "ground_truth_matrix", resolved)
    ground_truth_rules = _load_rules(
        ground_truth.get("rules"),
        where=f"{resolved}: ground_truth_matrix.rules",
    )

    return PolicyMatrix(
        source_path=resolved,
        risk_model=risk_model,
        thresholds=_load_thresholds(document, resolved),
        abac=_load_abac(
            document, resolved, ground_truth_rules=ground_truth_rules
        ),
        metrics=_load_metrics(document, resolved),
        dimensions=dimensions,
        ground_truth_rules=ground_truth_rules,
        schema_version=str(meta.get("schema_version") or ""),
        status=str(meta.get("status") or "unknown"),
        locked_for_primary_experiment=bool(
            meta.get("locked_for_primary_experiment") or False
        ),
        notes=dict(meta),
    )
def load_scenarios(
    path: str | Path = DEFAULT_SCENARIOS_PATH,
    *,
    require_ground_truth: bool = True,
    strict_unknown_keys: bool = False,
) -> tuple[Scenario, ...]:
    """Load a scenario dataset file.

    Both ``data/scenarios.yaml`` and ``data/pilot_scenarios.yaml`` use the same
    layout: a top-level mapping with a ``scenarios`` list.  Each entry is parsed
    by :meth:`~src.models.Scenario.from_dict`.  Duplicate ``scenario_id`` values
    are rejected because scenario identifiers pair the two authorization methods.
    """
    resolved = Path(path)
    document = load_yaml_mapping(resolved)
    entries = document.get("scenarios")
    if entries is None:
        raise ConfigurationError(
            f"{resolved} has no 'scenarios' key; the dataset is expected to be a "
            "mapping with a top-level 'scenarios' list"
        )
    scenarios: list[Scenario] = []
    seen: set[str] = set()
    for index, entry in enumerate(_as_sequence(entries, where=f"{resolved}: scenarios")):
        try:
            scenario = Scenario.from_dict(
                entry,
                require_ground_truth=require_ground_truth,
                strict_unknown_keys=strict_unknown_keys,
                source=f"{resolved} entry #{index + 1}",
            )
        except ValueError as exc:
            raise ConfigurationError(f"{resolved}: {exc}") from exc
        if scenario.scenario_id in seen:
            raise ConfigurationError(
                f"{resolved}: duplicate scenario_id '{scenario.scenario_id}'"
            )
        seen.add(scenario.scenario_id)
        scenarios.append(scenario)
    return tuple(scenarios)


def load_final_scenarios(
    path: str | Path = DEFAULT_SCENARIOS_PATH,
    *,
    pilot_path: str | Path = DEFAULT_PILOT_SCENARIOS_PATH,
) -> tuple[Scenario, ...]:
    """Load primary-evaluation scenarios while enforcing pilot separation.

    The explicit path check prevents accidentally passing the pilot file as the
    final dataset. ID and metadata checks also prevent copied pilot rows from
    entering a differently named final file.
    """
    resolved = Path(path).resolve()
    resolved_pilot = Path(pilot_path).resolve()
    if resolved == resolved_pilot:
        raise ConfigurationError(
            "pilot_scenarios.yaml is calibration-only and cannot be loaded as "
            "the final experiment dataset"
        )
    scenarios = load_scenarios(resolved)
    pilots = load_scenarios(resolved_pilot)
    pilot_ids = {scenario.scenario_id for scenario in pilots}
    pilot_attribute_keys = {
        (
            scenario.role,
            scenario.tool,
            scenario.sensitivity,
            scenario.destination,
            scenario.context_risk,
        )
        for scenario in pilots
    }
    overlapping = sorted(
        scenario.scenario_id for scenario in scenarios if scenario.scenario_id in pilot_ids
    )
    marked_pilot = sorted(
        scenario.scenario_id
        for scenario in scenarios
        if str(scenario.metadata.get("dataset_partition", "")).lower() == "pilot"
    )
    duplicated_pilot_attributes = sorted(
        scenario.scenario_id
        for scenario in scenarios
        if (
            scenario.role,
            scenario.tool,
            scenario.sensitivity,
            scenario.destination,
            scenario.context_risk,
        )
        in pilot_attribute_keys
    )
    if overlapping or marked_pilot or duplicated_pilot_attributes:
        offending = sorted(
            set(overlapping) | set(marked_pilot) | set(duplicated_pilot_attributes)
        )
        raise ConfigurationError(
            "final experiment dataset contains calibration-only pilot "
            "scenario ID(s) or attribute tuple(s): " + ", ".join(offending)
        )
    return scenarios


def validate_ground_truth_against_matrix(
    scenarios: Iterable[Scenario], matrix: PolicyMatrix
) -> tuple[LabelMismatch, ...]:
    """Cross-check declared labels against the authored ground-truth matrix.

    The manuscript requires labels to originate from the policy matrix rather
    than from the risk score (section IV.C).  When the matrix has no rules yet
    this function reports nothing, because there is nothing to check against; use
    :meth:`PolicyMatrix.missing_authoring_items` for that instead.
    """
    if not matrix.ground_truth_rules:
        return ()
    mismatches: list[LabelMismatch] = []
    for scenario in scenarios:
        if scenario.ground_truth is None:
            continue
        from_matrix = matrix.ground_truth_for(scenario)
        if from_matrix is None:
            mismatches.append(
                LabelMismatch(
                    scenario_id=scenario.scenario_id,
                    declared=scenario.ground_truth,
                    from_matrix=None,
                    reason="no ground-truth rule matches this scenario",
                )
            )
        elif from_matrix is not scenario.ground_truth:
            mismatches.append(
                LabelMismatch(
                    scenario_id=scenario.scenario_id,
                    declared=scenario.ground_truth,
                    from_matrix=from_matrix,
                    reason="declared label differs from the matrix outcome",
                )
            )
    return tuple(mismatches)
