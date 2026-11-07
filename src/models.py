"""Strongly typed domain models for the risk-adaptive runtime authorization study.

Design notes
------------
* Standard-library :mod:`dataclasses` are used instead of Pydantic so that the
  runtime dependency footprint stays minimal.  The experiment only needs YAML
  parsing plus the scientific stack used for analysis.
* Enum member names follow the vocabulary fixed by the experiment
  specification exactly (``ALLOW``/``ESCALATE``/``DENY``, etc.).  Parsing is
  deliberately tolerant of case and separators so that hand-authored YAML such
  as ``Analyst`` or ``controlled-external`` does not silently fail, but the
  canonical stored form is always the upper-case enum name.
* ``ContextRisk`` is a *supplied* attribute.  It is never inferred from text,
  and in particular no language model is used anywhere in this codebase to
  derive it.  The authoritative definitions are recorded in
  :data:`CONTEXT_RISK_DEFINITIONS` (verbatim from the experiment specification).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "AuthorizationResult",
    "ConfigurationError",
    "CONTEXT_RISK_DEFINITIONS",
    "ContextRisk",
    "Decision",
    "Destination",
    "Method",
    "PolicyOutcome",
    "RiskAssessment",
    "RiskFactors",
    "Role",
    "Scenario",
    "Sensitivity",
    "Tool",
]


class ConfigurationError(Exception):
    """Raised when required experimental configuration has not been authored.

    Policy rules, risk weights, factor mappings and thresholds are *inputs* to
    the experiment rather than values to be guessed by the implementation.
    Whenever such a value is still unset, the code fails loudly with this error
    instead of substituting a convenient default.
    """


class _CanonicalEnum(StrEnum):
    """``StrEnum`` that accepts loosely formatted input strings."""

    @classmethod
    def _missing_(cls, value: object) -> Any | None:
        if isinstance(value, str):
            canonical = value.strip().upper().replace("-", "_").replace(" ", "_")
            member = cls.__members__.get(canonical)
            if member is not None:
                return member
        return None

    @classmethod
    def parse(cls, value: object) -> "_CanonicalEnum":
        """Return the enum member for ``value`` or raise a descriptive error."""
        try:
            return cls(value)  # type: ignore[arg-type]
        except ValueError as exc:
            allowed = ", ".join(member.value for member in cls)
            raise ValueError(
                f"{cls.__name__} received unsupported value {value!r}; "
                f"allowed values are: {allowed}"
            ) from exc

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class Decision(_CanonicalEnum):
    """Authorization outcome.

    ``Decision`` is intentionally shared by both systems under evaluation:
    the baseline only ever emits ``ALLOW`` or ``DENY``, while the risk-adaptive
    system may also emit ``ESCALATE``.
    """

    ALLOW = "ALLOW"
    ESCALATE = "ESCALATE"
    DENY = "DENY"


class Role(_CanonicalEnum):
    """User role attached to a proposed tool invocation."""

    ANALYST = "ANALYST"
    MANAGER = "MANAGER"
    ADMINISTRATOR = "ADMINISTRATOR"


class Tool(_CanonicalEnum):
    """The five modeled enterprise tool operations."""

    READ_RECORD = "READ_RECORD"
    UPDATE_RECORD = "UPDATE_RECORD"
    EXPORT_DATA = "EXPORT_DATA"
    SEND_MESSAGE = "SEND_MESSAGE"
    DELETE_RECORD = "DELETE_RECORD"


class Sensitivity(_CanonicalEnum):
    """Information sensitivity classification of the addressed resource."""

    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class Destination(_CanonicalEnum):
    """Exposure scope of the proposed operation."""

    INTERNAL = "INTERNAL"
    CONTROLLED_EXTERNAL = "CONTROLLED_EXTERNAL"
    EXTERNAL = "EXTERNAL"


class ContextRisk(_CanonicalEnum):
    """Contextual risk level of the execution context.

    This value is **supplied explicitly in every synthetic scenario**.  It is
    not inferred at runtime by this codebase and must never be produced by a
    language model.  See :data:`CONTEXT_RISK_DEFINITIONS`.
    """

    NORMAL = "NORMAL"
    UNUSUAL = "UNUSUAL"
    HIGH_VOLUME = "HIGH_VOLUME"
    ANOMALOUS = "ANOMALOUS"


class Method(_CanonicalEnum):
    """Identifier for the authorization mechanism that produced a result."""

    RISK_ADAPTIVE = "risk_adaptive"
    ABAC_BINARY = "abac_binary"


CONTEXT_RISK_DEFINITIONS: Mapping[ContextRisk, str] = {
    ContextRisk.NORMAL: (
        "Expected operation pattern with no unusual execution context."
    ),
    ContextRisk.UNUSUAL: (
        "Legitimate-looking operation with an atypical contextual condition, "
        "such as unusual time, uncommon workflow, or unexpected resource "
        "combination."
    ),
    ContextRisk.HIGH_VOLUME: (
        "Bulk or unusually large operation compared with routine single-record "
        "behavior."
    ),
    ContextRisk.ANOMALOUS: (
        "strong contextual deviation such as unexpected external destination, "
        "unusual combination of privilege and action, or behavior inconsistent "
        "with the stated workflow."
    ),
}
# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #


def _validate_non_empty_string(field_name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string, got {value!r}")
    return value


def _validate_unit_interval(field_name: str, value: object) -> float:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must be a number in [0.0, 1.0], got {value!r}"
        ) from exc
    if not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{field_name} must lie in [0.0, 1.0], got {numeric!r}")
    return numeric


def _coerce_enum(field_name: str, enum_type: Any, value: object) -> Any:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as exc:
            raise ValueError(f"{field_name}: {exc}") from exc
    raise ValueError(
        f"{field_name} must be a {enum_type.__name__} or a string naming one, "
        f"got {value!r}"
    )


# --------------------------------------------------------------------------- #
# Scenario
# --------------------------------------------------------------------------- #


SCENARIO_REQUIRED_KEYS: tuple[str, ...] = (
    "scenario_id",
    "role",
    "tool",
    "sensitivity",
    "destination",
    "context_risk",
    "ground_truth",
)


@dataclass(frozen=True, slots=True)
class Scenario:
    """A single synthetic, pre-execution tool-invocation proposal.

    Attributes
    ----------
    scenario_id:
        Stable identifier used to pair results across methods (e.g. ``"S001"``).
    role, tool, sensitivity, destination, context_risk:
        The structured attributes of the proposed action.  ``context_risk`` is
        *supplied* by the dataset author and is never inferred.
    ground_truth:
        Expected authorization label.  ``None`` marks a scenario whose label has
        not yet been assigned (labels are authored via the policy matrix, not
        derived from the risk score).
    description, rationale:
        Human-readable description of the operation and the reason the label was
        assigned.  ``rationale`` is required for auditability of the dataset.
    resource:
        Optional synthetic resource name (e.g. ``"customer_records"``).
    secondary_label:
        Optional independent second-reviewer label used for the inter-rater
        agreement check (Cohen's kappa).
    policy_rule_ids:
        Ordered identifiers of the qualitative policy rules used to derive the
        ground-truth label. The first matching rule determines the label.
    metadata:
        Any additional keys present in the scenario file.  They are preserved
        verbatim so that drafting artifacts are not lost, but no component of
        the authorization pipeline reads them.
    """

    scenario_id: str
    role: Role
    tool: Tool
    sensitivity: Sensitivity
    destination: Destination
    context_risk: ContextRisk
    ground_truth: Decision | None = None
    description: str = ""
    rationale: str = ""
    resource: str | None = None
    secondary_label: Decision | None = None
    policy_rule_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scenario_id",
            _validate_non_empty_string("scenario_id", self.scenario_id),
        )
        object.__setattr__(self, "role", _coerce_enum("role", Role, self.role))
        object.__setattr__(self, "tool", _coerce_enum("tool", Tool, self.tool))
        object.__setattr__(
            self,
            "sensitivity",
            _coerce_enum("sensitivity", Sensitivity, self.sensitivity),
        )
        object.__setattr__(
            self,
            "destination",
            _coerce_enum("destination", Destination, self.destination),
        )
        object.__setattr__(
            self,
            "context_risk",
            _coerce_enum("context_risk", ContextRisk, self.context_risk),
        )
        if self.ground_truth is not None:
            object.__setattr__(
                self,
                "ground_truth",
                _coerce_enum("ground_truth", Decision, self.ground_truth),
            )
        if self.secondary_label is not None:
            object.__setattr__(
                self,
                "secondary_label",
                _coerce_enum("secondary_label", Decision, self.secondary_label),
            )
        if not isinstance(self.policy_rule_ids, (list, tuple)):
            raise ValueError("policy_rule_ids must be a list or tuple")
        policy_rule_ids = tuple(
            _validate_non_empty_string("policy_rule_ids entry", value)
            for value in self.policy_rule_ids
        )
        if len(set(policy_rule_ids)) != len(policy_rule_ids):
            raise ValueError("policy_rule_ids must not contain duplicates")
        object.__setattr__(self, "policy_rule_ids", policy_rule_ids)
        if self.resource is not None:
            object.__setattr__(
                self,
                "resource",
                _validate_non_empty_string("resource", self.resource),
            )
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_labelled(self) -> bool:
        """``True`` when a ground-truth label has been authored."""
        return self.ground_truth is not None

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        require_ground_truth: bool = True,
        strict_unknown_keys: bool = False,
        source: str | None = None,
    ) -> "Scenario":
        """Build a :class:`Scenario` from a parsed YAML/JSON mapping.

        Unknown keys are collected into ``metadata`` unless
        ``strict_unknown_keys`` is set, in which case they raise
        :class:`ValueError`.  The key ``ground_truth`` must be present; its value
        may be ``null`` to mark a scenario that is not labelled yet.
        """
        if not isinstance(data, Mapping):
            raise ValueError(
                f"scenario entry must be a mapping, got {type(data).__name__}"
                + (f" in {source}" if source else "")
            )
        where = f" in {source}" if source else ""
        missing = [key for key in SCENARIO_REQUIRED_KEYS if key not in data]
        if missing and not (
            set(missing) == {"ground_truth"} and not require_ground_truth
        ):
            raise ValueError(
                f"scenario{where} is missing required key(s): "
                f"{', '.join(sorted(missing))}"
            )

        known = set(SCENARIO_REQUIRED_KEYS) | {
            "description",
            "rationale",
            "resource",
            "secondary_label",
            "policy_rule_ids",
            "metadata",
        }
        unknown = sorted(set(data) - known)
        if unknown and strict_unknown_keys:
            raise ValueError(
                f"scenario{where} contains unknown key(s): {', '.join(unknown)}"
            )
        metadata = dict(data.get("metadata") or {})
        for key in unknown:
            metadata.setdefault(key, data[key])

        return cls(
            scenario_id=data["scenario_id"],
            role=data["role"],
            tool=data["tool"],
            sensitivity=data["sensitivity"],
            destination=data["destination"],
            context_risk=data["context_risk"],
            ground_truth=data.get("ground_truth"),
            description=str(data.get("description") or ""),
            rationale=str(data.get("rationale") or ""),
            resource=data.get("resource"),
            secondary_label=data.get("secondary_label"),
            policy_rule_ids=tuple(data.get("policy_rule_ids") or ()),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON/YAML-serialisable representation."""
        payload: dict[str, Any] = {
            "scenario_id": self.scenario_id,
            "role": self.role.value,
            "tool": self.tool.value,
            "sensitivity": self.sensitivity.value,
            "destination": self.destination.value,
            "context_risk": self.context_risk.value,
            "ground_truth": self.ground_truth.value if self.ground_truth else None,
            "description": self.description,
            "rationale": self.rationale,
        }
        if self.resource is not None:
            payload["resource"] = self.resource
        if self.secondary_label is not None:
            payload["secondary_label"] = self.secondary_label.value
        if self.policy_rule_ids:
            payload["policy_rule_ids"] = list(self.policy_rule_ids)
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

# --------------------------------------------------------------------------- #
# Risk components
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RiskFactors:
    """The four normalized risk components of a proposed action.

    Each component is an ordinal level mapped onto ``[0.0, 1.0]`` by an
    explicitly authored mapping.  The mappings themselves are configuration
    inputs (see ``data/policy_matrix.yaml``) and are never hard-coded here.
    """

    sensitivity: float
    action_severity: float
    exposure_scope: float
    contextual_risk: float

    def __post_init__(self) -> None:
        for name in ("sensitivity", "action_severity", "exposure_scope", "contextual_risk"):
            object.__setattr__(self, name, _validate_unit_interval(name, getattr(self, name)))

    def as_dict(self) -> dict[str, float]:
        return {
            "sensitivity": self.sensitivity,
            "action_severity": self.action_severity,
            "exposure_scope": self.exposure_scope,
            "contextual_risk": self.contextual_risk,
        }


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """Auditable record of how a risk score was produced for one scenario."""

    scenario_id: str
    score: float
    factors: RiskFactors
    weights: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "score", _validate_unit_interval("score", self.score)
        )
        object.__setattr__(self, "weights", dict(self.weights))


# --------------------------------------------------------------------------- #
# Outcomes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    """Raw decision returned by an authorization mechanism.

    Latency is *not* part of this structure on purpose: the evaluator times the
    policy call itself so that measurement stays independent of the mechanism
    implementation.
    """

    decision: Decision
    score: float | None = None
    explanation: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "decision", _coerce_enum("decision", Decision, self.decision)
        )
        if self.score is not None:
            object.__setattr__(self, "score", _validate_unit_interval("score", self.score))
        if not isinstance(self.details, Mapping):
            raise ValueError("details must be a mapping")
        object.__setattr__(self, "details", dict(self.details))


@dataclass(frozen=True, slots=True)
class AuthorizationResult:
    """Timed authorization outcome for a single scenario and mechanism.

    Field order places optional values last so that ``score`` can default to
    ``None`` (the binary baseline produces no score).  All fields required by the
    experiment specification are present, together with explicit binary-ABAC
    accounting.  For an ABAC result, ``ground_truth`` and
    ``correct_for_binary_safe_execution`` are required; a true-``ESCALATE``
    case records exactly one of its forced ``ALLOW``/``DENY`` resolution flags.
    """

    scenario_id: str
    decision: Decision
    latency_ms: float
    explanation: str
    score: float | None = None
    method: Method | None = None
    ground_truth: Decision | None = None
    correct_for_binary_safe_execution: bool | None = None
    true_escalate_resolved_as_allow: bool = False
    true_escalate_resolved_as_deny: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scenario_id",
            _validate_non_empty_string("scenario_id", self.scenario_id),
        )
        object.__setattr__(
            self, "decision", _coerce_enum("decision", Decision, self.decision)
        )
        if self.method is not None:
            object.__setattr__(
                self, "method", _coerce_enum("method", Method, self.method)
            )
        if self.ground_truth is not None:
            object.__setattr__(
                self,
                "ground_truth",
                _coerce_enum("ground_truth", Decision, self.ground_truth),
            )
        try:
            latency = float(self.latency_ms)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"latency_ms must be a number, got {self.latency_ms!r}"
            ) from exc
        if latency < 0:
            raise ValueError(f"latency_ms must be non-negative, got {latency!r}")
        object.__setattr__(self, "latency_ms", latency)
        if self.score is not None:
            object.__setattr__(self, "score", _validate_unit_interval("score", self.score))
        for field_name in (
            "true_escalate_resolved_as_allow",
            "true_escalate_resolved_as_deny",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")
        if (
            self.correct_for_binary_safe_execution is not None
            and not isinstance(self.correct_for_binary_safe_execution, bool)
        ):
            raise ValueError("correct_for_binary_safe_execution must be a boolean or None")
        if self.true_escalate_resolved_as_allow and self.true_escalate_resolved_as_deny:
            raise ValueError("an ESCALATE case cannot be resolved as both ALLOW and DENY")
        has_resolution = (
            self.true_escalate_resolved_as_allow
            or self.true_escalate_resolved_as_deny
        )
        if has_resolution and self.ground_truth is not Decision.ESCALATE:
            raise ValueError("true-ESCALATE resolution flags require ground_truth=ESCALATE")
        if self.method is Method.ABAC_BINARY:
            if self.decision not in (Decision.ALLOW, Decision.DENY):
                raise ValueError("the binary ABAC result decision must be ALLOW or DENY")
            if self.score is not None:
                raise ValueError("the binary ABAC result must not contain a risk score")
            if self.ground_truth is None:
                raise ValueError("binary ABAC result accounting requires ground_truth")
            if self.correct_for_binary_safe_execution is None:
                raise ValueError(
                    "binary ABAC result accounting requires "
                    "correct_for_binary_safe_execution"
                )
            if self.ground_truth is Decision.ESCALATE:
                expected_allow_flag = self.decision is Decision.ALLOW
                expected_deny_flag = self.decision is Decision.DENY
                if (
                    self.true_escalate_resolved_as_allow is not expected_allow_flag
                    or self.true_escalate_resolved_as_deny is not expected_deny_flag
                ):
                    raise ValueError(
                        "ground_truth=ESCALATE ABAC results must record exactly "
                        "the emitted ALLOW/DENY resolution"
                    )

    def to_row(self) -> dict[str, Any]:
        """Return a flat, CSV-friendly representation for the results directory."""
        return {
            "scenario_id": self.scenario_id,
            "method": self.method.value if self.method else None,
            "decision": self.decision.value,
            "ground_truth": (
                self.ground_truth.value if self.ground_truth is not None else None
            ),
            "correct_for_binary_safe_execution": (
                self.correct_for_binary_safe_execution
            ),
            "true_escalate_resolved_as_allow": (
                self.true_escalate_resolved_as_allow
            ),
            "true_escalate_resolved_as_deny": self.true_escalate_resolved_as_deny,
            "score": self.score,
            "latency_ms": self.latency_ms,
            "explanation": self.explanation,
        }
