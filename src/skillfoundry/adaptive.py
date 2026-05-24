"""Adaptive steering schema objects for SkillFoundry build loops."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping

from .schema import (
    JsonValue,
    SchemaModel,
    SchemaValidationError,
    _require_json_mapping,
    _require_non_empty_str,
    _require_non_negative_int,
    _require_str_list,
    utc_now,
)
from .security import PathSecurityError, validate_relative_path


FORBIDDEN_ADAPTIVE_FIELDS = frozenset(
    {
        "conversation",
        "conversation_turns",
        "messages",
        "prompt",
        "prompts",
        "raw_prompt",
        "model_output",
        "model_outputs",
        "raw_model_output",
        "raw_model_outputs",
        "transcript",
        "raw_transcript",
    }
)

ADAPTIVE_ROUTES = frozenset(
    {
        "continue",
        "repair",
        "redesign",
        "review_required",
        "final_verify",
        "closure",
        "failed",
        "spec_revision_required",
    }
)

ADAPTIVE_DECISIONS = frozenset(
    {
        "continue",
        "repair",
        "redesign",
        "require_reviewer",
        "final_verify",
        "close",
        "fail",
        "require_spec_revision",
    }
)


def _require_enum(value: Any, field_name: str, allowed: frozenset[str]) -> None:
    _require_non_empty_str(value, field_name)
    if value not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise SchemaValidationError(f"{field_name} must be one of: {allowed_values}")


def _require_score(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{field_name} must be a finite number in [0.0, 1.0]")
    if not math.isfinite(float(value)) or float(value) < 0.0 or float(value) > 1.0:
        raise SchemaValidationError(f"{field_name} must be a finite number in [0.0, 1.0]")


def _require_ref(value: Any, field_name: str) -> None:
    _require_non_empty_str(value, field_name)
    try:
        validate_relative_path(value)
    except PathSecurityError as exc:
        raise SchemaValidationError(f"{field_name} must be a safe relative artifact ref: {exc}") from exc


def _require_ref_list(value: Any, field_name: str) -> None:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list of refs")
    for index, item in enumerate(value):
        _require_ref(item, f"{field_name}[{index}]")


def _reject_forbidden_keys(value: Any, field_name: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_ADAPTIVE_FIELDS:
                raise SchemaValidationError(f"{field_name} contains forbidden raw field: {key}")
            _reject_forbidden_keys(item, f"{field_name}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_forbidden_keys(item, f"{field_name}[{index}]")


def _require_safe_metadata(value: Any, field_name: str) -> None:
    _require_json_mapping(value, field_name)
    _reject_forbidden_keys(value, field_name)


@dataclass
class CapabilityStateEstimate(SchemaModel):
    job_id: str
    iteration: int
    objective: str
    current_phase: str
    next_best_step: str
    known_good: list[str] = field(default_factory=list)
    known_bad: list[str] = field(default_factory=list)
    known_unknowns: list[str] = field(default_factory=list)
    current_risks: list[str] = field(default_factory=list)
    latest_verification_status: str = "not_run"
    confidence: float = 0.0
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: str = "skillfoundry.capability_state_estimate.v1"

    def validate(self) -> None:
        super().validate()
        for name in ("job_id", "objective", "current_phase", "next_best_step", "latest_verification_status"):
            _require_non_empty_str(getattr(self, name), name)
        _require_non_negative_int(self.iteration, "iteration")
        _require_score(self.confidence, "confidence")
        for name in ("known_good", "known_bad", "known_unknowns", "current_risks"):
            _require_str_list(getattr(self, name), name)
        _require_safe_metadata(self.metadata, "metadata")


@dataclass
class NextStepContract(SchemaModel):
    job_id: str
    iteration: int
    current_state_ref: str
    next_objective: str
    why_now: str
    risk_if_too_large: str
    risk_if_too_small: str
    allowed_scope: list[str]
    visible_refs: list[str]
    expected_outputs: list[str]
    exit_criteria: list[str]
    stop_conditions: list[str]
    estimated_followups: list[str] = field(default_factory=list)
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: str = "skillfoundry.next_step_contract.v1"

    def validate(self) -> None:
        super().validate()
        for name in (
            "job_id",
            "current_state_ref",
            "next_objective",
            "why_now",
            "risk_if_too_large",
            "risk_if_too_small",
        ):
            _require_non_empty_str(getattr(self, name), name)
        _require_non_negative_int(self.iteration, "iteration")
        _require_ref(self.current_state_ref, "current_state_ref")
        for name in ("allowed_scope", "visible_refs", "expected_outputs"):
            _require_ref_list(getattr(self, name), name)
        for name in ("exit_criteria", "stop_conditions", "estimated_followups"):
            _require_str_list(getattr(self, name), name)
        _require_safe_metadata(self.metadata, "metadata")


@dataclass
class ObservationReport(SchemaModel):
    job_id: str
    iteration: int
    contract_ref: str
    produced_artifacts: list[str] = field(default_factory=list)
    changed_refs: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    worker_claims: list[str] = field(default_factory=list)
    verifier_evidence: list[str] = field(default_factory=list)
    new_unknowns: list[str] = field(default_factory=list)
    recommended_next_steps: list[str] = field(default_factory=list)
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: str = "skillfoundry.observation_report.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        _require_non_negative_int(self.iteration, "iteration")
        _require_ref(self.contract_ref, "contract_ref")
        for name in ("produced_artifacts", "changed_refs", "verifier_evidence"):
            _require_ref_list(getattr(self, name), name)
        for name in (
            "commands_run",
            "tests_run",
            "failures",
            "worker_claims",
            "new_unknowns",
            "recommended_next_steps",
        ):
            _require_str_list(getattr(self, name), name)
        _require_safe_metadata(self.metadata, "metadata")


@dataclass
class StateCorrection(SchemaModel):
    job_id: str
    iteration: int
    previous_state_ref: str
    observation_ref: str
    corrected_state_ref: str
    decision: str
    rationale: str
    next_route: str
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: str = "skillfoundry.state_correction.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        _require_non_negative_int(self.iteration, "iteration")
        for name in ("previous_state_ref", "observation_ref", "corrected_state_ref"):
            _require_ref(getattr(self, name), name)
        _require_enum(self.decision, "decision", ADAPTIVE_DECISIONS)
        _require_non_empty_str(self.rationale, "rationale")
        _require_enum(self.next_route, "next_route", ADAPTIVE_ROUTES)
        _require_safe_metadata(self.metadata, "metadata")


@dataclass
class DecisionRecord(SchemaModel):
    decision_id: str
    iteration: int
    context: str
    options: list[str]
    chosen_option: str
    rationale: str
    risk: str
    expected_evidence: list[str]
    fallback: str
    reviewer: str = ""
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: str = "skillfoundry.decision_record.v1"

    def validate(self) -> None:
        super().validate()
        for name in ("decision_id", "context", "chosen_option", "rationale", "risk", "fallback", "created_at"):
            _require_non_empty_str(getattr(self, name), name)
        _require_non_negative_int(self.iteration, "iteration")
        _require_str_list(self.options, "options")
        _require_str_list(self.expected_evidence, "expected_evidence")
        if self.reviewer:
            _require_non_empty_str(self.reviewer, "reviewer")
        _require_safe_metadata(self.metadata, "metadata")


def _decision_list_from_payload(value: Any, field_name: str) -> list[DecisionRecord]:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list")
    return [DecisionRecord.from_dict(item) for item in value]


@dataclass
class DecisionLedger(SchemaModel):
    job_id: str
    decisions: list[DecisionRecord] = field(default_factory=list)
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: str = "skillfoundry.decision_ledger.v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DecisionLedger":
        _reject_forbidden_keys(payload, cls.__name__)
        converted = dict(payload)
        if "decisions" in converted:
            converted["decisions"] = _decision_list_from_payload(converted["decisions"], "decisions")
        return super().from_dict(converted)

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        if not isinstance(self.decisions, list):
            raise SchemaValidationError("decisions must be a list")
        seen: set[str] = set()
        for index, decision in enumerate(self.decisions):
            if not isinstance(decision, DecisionRecord):
                raise SchemaValidationError(f"decisions[{index}] must be a DecisionRecord")
            decision.validate()
            if decision.decision_id in seen:
                raise SchemaValidationError(f"duplicate decision_id: {decision.decision_id}")
            seen.add(decision.decision_id)
        _require_safe_metadata(self.metadata, "metadata")
