"""Front Desk schema objects for requirements clarification artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping, Self

from .schema import (
    JsonValue,
    SchemaModel,
    SchemaValidationError,
    _reject_unknown_fields,
    _require_bool,
    _require_hash_mapping,
    _require_json_mapping,
    _require_non_empty_str,
    _require_non_negative_int,
    _require_positive_int,
    _require_sha256,
    _require_str_list,
    utc_now,
)
from .security import PathSecurityError, validate_relative_path


CONVERSATION_ROLES = frozenset({"user", "assistant", "system", "tool"})
QUESTION_PRIORITIES = frozenset({"must", "should", "could"})
QUESTION_ANSWER_TYPES = frozenset({"free_text", "enum", "file", "example", "boolean", "number"})
ELICITATION_READINESS = frozenset({"needs_clarification", "ready_for_audit"})
ACCEPTANCE_TEST_METHODS = frozenset({"static", "fixture", "llm_judge", "human_review", "manual_check"})
ACCEPTANCE_EVIDENCE_KINDS = frozenset(
    {"file", "command", "qa_report", "verifier_check", "human_note", "model_judge"}
)
ACCEPTANCE_PRIORITIES = frozenset({"must", "should", "could"})
DATA_SENSITIVITY_LEVELS = frozenset({"public", "internal", "confidential", "restricted"})
ACCEPTANCE_COVERAGE_STATUSES = frozenset({"planned", "covered", "manual_only", "uncovered"})
FEASIBILITY_DECISIONS = frozenset({"feasible", "needs_clarification", "infeasible", "human_review_required"})
AUDIT_DECISIONS = frozenset({"approved", "needs_more_clarification", "infeasible", "human_review_required"})
ROUTING_RECOMMENDATIONS = frozenset(
    {"reuse_existing", "prompt_only", "rag", "script_required", "codex_worker", "human_review"}
)
CORE_NEED_READINESS = frozenset({"needs_core_need_input", "core_need_ready", "human_review_required", "rejected"})
FRONTDESK_PHASES = frozenset(
    {"core_need_discovery", "solution_planning", "user_review", "freeze", "complete", "failed"}
)
SOLUTION_PLAN_STATUSES = frozenset({"draft", "awaiting_user_review", "revision_requested", "approved"})
PLAN_REVIEW_DECISIONS = frozenset({"approve", "request_revision", "reject", "human_review"})
FRONTDESK_STAGES = frozenset(
    {
        "front_desk",
        "new_conversation",
        "discover_core_need",
        "elicit",
        "validate_elicitation_output",
        "plan_solution",
        "audit",
        "validate_audit_output",
        "deterministic_readiness_gate",
        "ask_user",
        "await_user_plan_review",
        "revise_plan",
        "freeze_approved_plan",
        "freeze_spec",
        "freeze_manifest_written",
        "route_to_build",
        "human_review",
        "complete",
        "failed",
    }
)
FRONTDESK_READINESS = frozenset(
    {
        "new_conversation",
        "needs_core_need_input",
        "core_need_ready",
        "needs_clarification",
        "ready_for_audit",
        "plan_draft_ready",
        "awaiting_plan_review",
        "plan_revision_requested",
        "plan_approved",
        "approved",
        "infeasible",
        "human_review_required",
        "frozen",
        "rejected",
        "failed",
    }
)
PRODUCT_SEMANTIC_COVERAGE_STATUSES = frozenset({"not_started", "passed", "failed"})
FRONTDESK_NEXT_ACTIONS = frozenset(
    {
        "none",
        "discover_core_need",
        "elicit",
        "validate_elicitation_output",
        "plan_solution",
        "audit",
        "validate_audit_output",
        "deterministic_readiness_gate",
        "ask_user",
        "await_user_plan_review",
        "revise_plan",
        "freeze_approved_plan",
        "freeze_spec",
        "freeze_manifest_written",
        "route_to_build",
        "human_review",
        "reject",
        "fail_closed",
    }
)
FORBIDDEN_STATE_FIELDS = frozenset(
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
    }
)


def _require_string(value: Any, field_name: str) -> None:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")


def _require_optional_non_empty_str(value: Any, field_name: str) -> None:
    if value is not None:
        _require_non_empty_str(value, field_name)


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


def _require_positive_number(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{field_name} must be a positive finite number")
    if not math.isfinite(float(value)) or float(value) <= 0.0:
        raise SchemaValidationError(f"{field_name} must be a positive finite number")


def _require_ref(value: Any, field_name: str) -> None:
    _require_non_empty_str(value, field_name)
    try:
        validate_relative_path(value)
    except PathSecurityError as exc:
        raise SchemaValidationError(f"{field_name} must be a safe relative artifact ref: {exc}") from exc


def _require_optional_ref(value: Any, field_name: str) -> None:
    if value is not None:
        _require_ref(value, field_name)


def _require_ref_list(value: Any, field_name: str) -> None:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list of refs")
    for index, item in enumerate(value):
        _require_ref(item, f"{field_name}[{index}]")


def _require_json_object_list(value: Any, field_name: str) -> None:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list of JSON objects")
    for index, item in enumerate(value):
        if isinstance(item, AcceptanceCriterion):
            item.validate()
        else:
            _require_json_mapping(item, f"{field_name}[{index}]")


def _require_task_execution_boundary(value: Any, field_name: str) -> None:
    _require_json_mapping(value, field_name)
    required = {
        "allowed_write_paths",
        "blocked_paths",
        "required_artifacts",
        "timeout_seconds",
        "attempt_limit",
    }
    missing = sorted(required - set(value))
    if missing:
        raise SchemaValidationError(f"{field_name} missing required field(s): {', '.join(missing)}")
    _require_str_list(value["allowed_write_paths"], f"{field_name}.allowed_write_paths")
    _require_str_list(value["blocked_paths"], f"{field_name}.blocked_paths")
    _require_ref_list(value["required_artifacts"], f"{field_name}.required_artifacts")
    if "locked_input_hashes" in value:
        _require_hash_mapping(value["locked_input_hashes"], f"{field_name}.locked_input_hashes")
    _require_positive_int(value["timeout_seconds"], f"{field_name}.timeout_seconds")
    _require_positive_int(value["attempt_limit"], f"{field_name}.attempt_limit")


def _question_list_from_payload(value: Any, field_name: str) -> list["StructuredQuestion"]:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list")
    return [StructuredQuestion.from_dict(item) for item in value]


def _criteria_list_from_payload(value: Any, field_name: str) -> list["AcceptanceCriterion"]:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field_name} must be a list")
    return [AcceptanceCriterion.from_dict(item) for item in value]


@dataclass
class ConversationTurn(SchemaModel):
    turn_id: str
    role: str
    content: str
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    schema_version: str = "skillfoundry.conversation_turn.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.turn_id, "turn_id")
        _require_enum(self.role, "role", CONVERSATION_ROLES)
        _require_non_empty_str(self.content, "content")
        _require_non_empty_str(self.created_at, "created_at")
        _require_json_mapping(self.metadata, "metadata")


@dataclass
class ProductSemanticLock(SchemaModel):
    """Structured, governed product intent extracted from Front Desk turns."""

    job_id: str
    semantic_summary: str
    requirement_clauses: list[str]
    product_identity_terms: list[str] = field(default_factory=list)
    domain_terms: list[str] = field(default_factory=list)
    implementation_requirements: list[str] = field(default_factory=list)
    delivery_requirements: list[str] = field(default_factory=list)
    must_not: list[str] = field(default_factory=list)
    source_ref: str = "frontdesk/conversation.jsonl"
    source_turn_ids: list[str] = field(default_factory=list)
    source_char_count: int = 0
    sanitized_char_count: int = 0
    redaction_applied: bool = False
    truncated: bool = False
    compression_strategy: str = "requirement_preserving_distillation"
    omission_warnings: list[str] = field(default_factory=list)
    source_trace: list[dict[str, JsonValue]] = field(default_factory=list)
    schema_version: str = "skillfoundry.product_semantic_lock.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        _require_non_empty_str(self.semantic_summary, "semantic_summary")
        _require_str_list(self.requirement_clauses, "requirement_clauses")
        _require_str_list(self.product_identity_terms, "product_identity_terms")
        _require_str_list(self.domain_terms, "domain_terms")
        _require_str_list(self.implementation_requirements, "implementation_requirements")
        _require_str_list(self.delivery_requirements, "delivery_requirements")
        _require_str_list(self.must_not, "must_not")
        _require_non_empty_str(self.source_ref, "source_ref")
        _require_str_list(self.source_turn_ids, "source_turn_ids")
        _require_non_negative_int(self.source_char_count, "source_char_count")
        _require_non_negative_int(self.sanitized_char_count, "sanitized_char_count")
        _require_bool(self.redaction_applied, "redaction_applied")
        _require_bool(self.truncated, "truncated")
        _require_non_empty_str(self.compression_strategy, "compression_strategy")
        _require_str_list(self.omission_warnings, "omission_warnings")
        if not isinstance(self.source_trace, list):
            raise SchemaValidationError("source_trace must be a list")
        for index, item in enumerate(self.source_trace):
            _require_json_mapping(item, f"source_trace[{index}]")


@dataclass
class ProductSemanticCoverageReport(SchemaModel):
    """Coverage check proving the semantic lock preserved key request signals."""

    job_id: str
    status: str
    semantic_lock_ref: str = "frontdesk/product_semantic_lock.json"
    source_ref: str = "frontdesk/conversation.jsonl"
    required_terms: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    missing_terms: list[str] = field(default_factory=list)
    source_turn_ids: list[str] = field(default_factory=list)
    source_char_count: int = 0
    semantic_summary_char_count: int = 0
    truncated: bool = False
    coverage_ratio: float = 1.0
    checks: list[dict[str, JsonValue]] = field(default_factory=list)
    source_sha256: str | None = None
    semantic_lock_sha256: str | None = None
    schema_version: str = "skillfoundry.product_semantic_coverage.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        _require_enum(self.status, "status", PRODUCT_SEMANTIC_COVERAGE_STATUSES)
        _require_non_empty_str(self.semantic_lock_ref, "semantic_lock_ref")
        _require_non_empty_str(self.source_ref, "source_ref")
        _require_str_list(self.required_terms, "required_terms")
        _require_str_list(self.matched_terms, "matched_terms")
        _require_str_list(self.missing_terms, "missing_terms")
        _require_str_list(self.source_turn_ids, "source_turn_ids")
        _require_non_negative_int(self.source_char_count, "source_char_count")
        _require_non_negative_int(self.semantic_summary_char_count, "semantic_summary_char_count")
        _require_bool(self.truncated, "truncated")
        _require_score(self.coverage_ratio, "coverage_ratio")
        if not isinstance(self.checks, list):
            raise SchemaValidationError("checks must be a list")
        for index, item in enumerate(self.checks):
            _require_json_mapping(item, f"checks[{index}]")
        if self.source_sha256 is not None:
            _require_sha256(self.source_sha256, "source_sha256")
        if self.semantic_lock_sha256 is not None:
            _require_sha256(self.semantic_lock_sha256, "semantic_lock_sha256")


@dataclass
class StructuredQuestion(SchemaModel):
    question_id: str
    text: str
    missing_field_path: str
    reason: str
    priority: str = "must"
    answer_type: str = "free_text"
    blocks_build: bool = True
    options: list[str] = field(default_factory=list)
    schema_version: str = "skillfoundry.structured_question.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.question_id, "question_id")
        _require_non_empty_str(self.text, "text")
        _require_non_empty_str(self.missing_field_path, "missing_field_path")
        _require_non_empty_str(self.reason, "reason")
        _require_enum(self.priority, "priority", QUESTION_PRIORITIES)
        _require_enum(self.answer_type, "answer_type", QUESTION_ANSWER_TYPES)
        _require_bool(self.blocks_build, "blocks_build")
        _require_str_list(self.options, "options")


@dataclass
class ElicitationReport(SchemaModel):
    readiness_guess: str = "needs_clarification"
    current_understanding: str = ""
    known_fields: dict[str, JsonValue] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    next_questions: list[StructuredQuestion] = field(default_factory=list)
    draft_skill_spec: dict[str, JsonValue] = field(default_factory=dict)
    draft_acceptance_criteria: list[dict[str, JsonValue]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    conversation_ref: str = "frontdesk/conversation.jsonl"
    round_index: int = 1
    schema_version: str = "skillfoundry.elicitation_report.v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("ElicitationReport payload must be a JSON object")
        _reject_unknown_fields(cls, payload)
        data = dict(payload)
        if "next_questions" in data:
            data["next_questions"] = _question_list_from_payload(data["next_questions"], "next_questions")
        instance = cls(**data)
        instance.validate()
        return instance

    def validate(self) -> None:
        super().validate()
        _require_enum(self.readiness_guess, "readiness_guess", ELICITATION_READINESS)
        _require_string(self.current_understanding, "current_understanding")
        _require_json_mapping(self.known_fields, "known_fields")
        _require_str_list(self.missing_fields, "missing_fields")
        _require_str_list(self.risk_flags, "risk_flags")
        if not isinstance(self.next_questions, list):
            raise SchemaValidationError("next_questions must be a list")
        for index, question in enumerate(self.next_questions):
            if not isinstance(question, StructuredQuestion):
                raise SchemaValidationError(f"next_questions[{index}] must be a StructuredQuestion")
            question.validate()
        _require_json_mapping(self.draft_skill_spec, "draft_skill_spec")
        _require_json_object_list(self.draft_acceptance_criteria, "draft_acceptance_criteria")
        _require_str_list(self.assumptions, "assumptions")
        _require_ref(self.conversation_ref, "conversation_ref")
        _require_positive_int(self.round_index, "round_index")


@dataclass
class CoreNeedBrief(SchemaModel):
    problem_statement: str
    target_user: str
    usage_moment: str
    desired_outcome: str
    success_signal: str
    current_workaround: str = ""
    non_goals: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    source_turn_ids: list[str] = field(default_factory=list)
    schema_version: str = "skillfoundry.core_need_brief.v1"

    def validate(self) -> None:
        super().validate()
        for field_name in (
            "problem_statement",
            "target_user",
            "usage_moment",
            "desired_outcome",
            "success_signal",
        ):
            _require_non_empty_str(getattr(self, field_name), field_name)
        _require_string(self.current_workaround, "current_workaround")
        _require_str_list(self.non_goals, "non_goals")
        _require_str_list(self.assumptions, "assumptions")
        _require_str_list(self.risk_flags, "risk_flags")
        _require_score(self.confidence_score, "confidence_score")
        _require_str_list(self.source_turn_ids, "source_turn_ids")


@dataclass
class CoreNeedQuestion(SchemaModel):
    question_id: str
    text: str
    reason: str
    priority: str = "must"
    answer_type: str = "free_text"
    options: list[str] = field(default_factory=list)
    blocks_core_need: bool = True
    schema_version: str = "skillfoundry.core_need_question.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.question_id, "question_id")
        _require_non_empty_str(self.text, "text")
        _require_non_empty_str(self.reason, "reason")
        _require_enum(self.priority, "priority", QUESTION_PRIORITIES)
        _require_enum(self.answer_type, "answer_type", QUESTION_ANSWER_TYPES)
        _require_str_list(self.options, "options")
        _require_bool(self.blocks_core_need, "blocks_core_need")


@dataclass
class CoreNeedDiscoveryReport(SchemaModel):
    readiness: str = "needs_core_need_input"
    current_understanding: str = ""
    core_need_brief: CoreNeedBrief | None = None
    next_questions: list[CoreNeedQuestion] = field(default_factory=list)
    decision_ledger_ref: str | None = None
    summary_ref: str | None = None
    round_index: int = 1
    schema_version: str = "skillfoundry.core_need_discovery_report.v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("CoreNeedDiscoveryReport payload must be a JSON object")
        _reject_unknown_fields(cls, payload)
        data = dict(payload)
        if isinstance(data.get("core_need_brief"), Mapping):
            data["core_need_brief"] = CoreNeedBrief.from_dict(data["core_need_brief"])
        if "next_questions" in data:
            if not isinstance(data["next_questions"], list):
                raise SchemaValidationError("next_questions must be a list")
            data["next_questions"] = [CoreNeedQuestion.from_dict(item) for item in data["next_questions"]]
        instance = cls(**data)
        instance.validate()
        return instance

    def validate(self) -> None:
        super().validate()
        _require_enum(self.readiness, "readiness", CORE_NEED_READINESS)
        _require_string(self.current_understanding, "current_understanding")
        if self.core_need_brief is not None:
            if not isinstance(self.core_need_brief, CoreNeedBrief):
                raise SchemaValidationError("core_need_brief must be a CoreNeedBrief")
            self.core_need_brief.validate()
        if not isinstance(self.next_questions, list):
            raise SchemaValidationError("next_questions must be a list")
        for index, question in enumerate(self.next_questions):
            if not isinstance(question, CoreNeedQuestion):
                raise SchemaValidationError(f"next_questions[{index}] must be a CoreNeedQuestion")
            question.validate()
        _require_optional_ref(self.decision_ledger_ref, "decision_ledger_ref")
        _require_optional_ref(self.summary_ref, "summary_ref")
        _require_positive_int(self.round_index, "round_index")
        if self.readiness == "core_need_ready" and self.core_need_brief is None:
            raise SchemaValidationError("core_need_ready requires core_need_brief")


@dataclass
class SolutionPlan(SchemaModel):
    plan_id: str
    core_need_brief_ref: str
    summary: str
    proposed_skill_name: str
    target_user: str
    user_problem: str
    desired_outcome: str
    approach: str
    implementation_outline: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    acceptance_summary: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    open_confirmation_items: list[str] = field(default_factory=list)
    status: str = "draft"
    draft_skill_spec_ref: str | None = "frontdesk/draft_skill_spec.yaml"
    acceptance_criteria_ref: str | None = "frontdesk/acceptance_criteria.yaml"
    markdown_ref: str | None = "frontdesk/solution_plan.md"
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "skillfoundry.solution_plan.v1"

    def validate(self) -> None:
        super().validate()
        for field_name in (
            "plan_id",
            "summary",
            "proposed_skill_name",
            "target_user",
            "user_problem",
            "desired_outcome",
            "approach",
            "created_at",
        ):
            _require_non_empty_str(getattr(self, field_name), field_name)
        _require_ref(self.core_need_brief_ref, "core_need_brief_ref")
        _require_str_list(self.implementation_outline, "implementation_outline")
        _require_str_list(self.key_decisions, "key_decisions")
        _require_str_list(self.acceptance_summary, "acceptance_summary")
        _require_str_list(self.risks, "risks")
        _require_str_list(self.open_confirmation_items, "open_confirmation_items")
        _require_enum(self.status, "status", SOLUTION_PLAN_STATUSES)
        _require_optional_ref(self.draft_skill_spec_ref, "draft_skill_spec_ref")
        _require_optional_ref(self.acceptance_criteria_ref, "acceptance_criteria_ref")
        _require_optional_ref(self.markdown_ref, "markdown_ref")


@dataclass
class PlanReviewRecord(SchemaModel):
    review_id: str
    solution_plan_ref: str
    decision: str
    reviewer_id: str
    reviewer_role: str
    reason: str
    requested_changes: list[str] = field(default_factory=list)
    source_hash: str | None = None
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "skillfoundry.plan_review_record.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.review_id, "review_id")
        _require_ref(self.solution_plan_ref, "solution_plan_ref")
        _require_enum(self.decision, "decision", PLAN_REVIEW_DECISIONS)
        _require_non_empty_str(self.reviewer_id, "reviewer_id")
        _require_non_empty_str(self.reviewer_role, "reviewer_role")
        _require_non_empty_str(self.reason, "reason")
        _require_str_list(self.requested_changes, "requested_changes")
        if self.source_hash is not None:
            _require_sha256(self.source_hash, "source_hash")
        _require_non_empty_str(self.created_at, "created_at")


@dataclass
class AcceptanceCriterion(SchemaModel):
    id: str
    description: str
    source_requirement: str = ""
    source_turn_ids: list[str] = field(default_factory=list)
    requirement_id: str = "REQ-001"
    test_method: str = "static"
    pass_condition: str = ""
    failure_examples: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    evidence_kind: str = "verifier_check"
    priority: str = "must"
    risk_tags: list[str] = field(default_factory=list)
    data_sensitivity: str = "public"
    coverage_status: str = "planned"
    verifier_check_id: str | None = None
    fixture_ref: str | None = None
    manual_authority: str | None = None
    unverifiable_reason: str | None = None
    schema_version: str = "skillfoundry.acceptance_criterion.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.id, "id")
        _require_non_empty_str(self.description, "description")
        _require_string(self.source_requirement, "source_requirement")
        _require_str_list(self.source_turn_ids, "source_turn_ids")
        _require_non_empty_str(self.requirement_id, "requirement_id")
        _require_enum(self.test_method, "test_method", ACCEPTANCE_TEST_METHODS)
        _require_string(self.pass_condition, "pass_condition")
        _require_str_list(self.failure_examples, "failure_examples")
        _require_str_list(self.required_evidence, "required_evidence")
        _require_enum(self.evidence_kind, "evidence_kind", ACCEPTANCE_EVIDENCE_KINDS)
        _require_enum(self.priority, "priority", ACCEPTANCE_PRIORITIES)
        _require_str_list(self.risk_tags, "risk_tags")
        _require_enum(self.data_sensitivity, "data_sensitivity", DATA_SENSITIVITY_LEVELS)
        _require_enum(self.coverage_status, "coverage_status", ACCEPTANCE_COVERAGE_STATUSES)
        _require_optional_non_empty_str(self.verifier_check_id, "verifier_check_id")
        _require_optional_ref(self.fixture_ref, "fixture_ref")
        _require_optional_non_empty_str(self.manual_authority, "manual_authority")
        _require_optional_non_empty_str(self.unverifiable_reason, "unverifiable_reason")


@dataclass
class AcceptanceCriteriaSet(SchemaModel):
    criteria: list[AcceptanceCriterion] = field(default_factory=list)
    criteria_set_id: str = "frontdesk-acceptance-criteria"
    job_id: str | None = None
    schema_version: str = "skillfoundry.acceptance_criteria_set.v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("AcceptanceCriteriaSet payload must be a JSON object")
        _reject_unknown_fields(cls, payload)
        data = dict(payload)
        if "criteria" in data:
            data["criteria"] = _criteria_list_from_payload(data["criteria"], "criteria")
        instance = cls(**data)
        instance.validate()
        return instance

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.criteria_set_id, "criteria_set_id")
        _require_optional_non_empty_str(self.job_id, "job_id")
        if not isinstance(self.criteria, list):
            raise SchemaValidationError("criteria must be a list")
        seen: set[str] = set()
        for index, criterion in enumerate(self.criteria):
            if not isinstance(criterion, AcceptanceCriterion):
                raise SchemaValidationError(f"criteria[{index}] must be an AcceptanceCriterion")
            criterion.validate()
            if criterion.id in seen:
                raise SchemaValidationError(f"duplicate acceptance criterion id: {criterion.id}")
            seen.add(criterion.id)


@dataclass
class FeasibilityReport(SchemaModel):
    decision: str = "needs_clarification"
    feasibility_score: float = 0.0
    risk_score: float = 0.0
    routing_recommendation: str = "human_review"
    required_capabilities: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    human_review_reasons: list[str] = field(default_factory=list)
    report_ref: str | None = None
    schema_version: str = "skillfoundry.feasibility_report.v1"

    def validate(self) -> None:
        super().validate()
        _require_enum(self.decision, "decision", FEASIBILITY_DECISIONS)
        _require_score(self.feasibility_score, "feasibility_score")
        _require_score(self.risk_score, "risk_score")
        _require_enum(self.routing_recommendation, "routing_recommendation", ROUTING_RECOMMENDATIONS)
        _require_str_list(self.required_capabilities, "required_capabilities")
        _require_str_list(self.missing_capabilities, "missing_capabilities")
        _require_str_list(self.constraints, "constraints")
        _require_str_list(self.risks, "risks")
        _require_str_list(self.assumptions, "assumptions")
        _require_str_list(self.human_review_reasons, "human_review_reasons")
        _require_optional_ref(self.report_ref, "report_ref")


@dataclass
class SpecAuditReport(SchemaModel):
    decision: str = "needs_more_clarification"
    clarity_score: float = 0.0
    feasibility_score: float = 0.0
    testability_score: float = 0.0
    risk_score: float = 0.0
    missing_requirements: list[str] = field(default_factory=list)
    unsafe_assumptions: list[str] = field(default_factory=list)
    required_followup_questions: list[StructuredQuestion] = field(default_factory=list)
    spec_patch_suggestions: list[str] = field(default_factory=list)
    routing_recommendation: str = "human_review"
    approval_rationale: str = ""
    elicitation_report_ref: str | None = None
    feasibility_report_ref: str | None = None
    schema_version: str = "skillfoundry.spec_audit_report.v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("SpecAuditReport payload must be a JSON object")
        _reject_unknown_fields(cls, payload)
        data = dict(payload)
        if "required_followup_questions" in data:
            data["required_followup_questions"] = _question_list_from_payload(
                data["required_followup_questions"], "required_followup_questions"
            )
        instance = cls(**data)
        instance.validate()
        return instance

    def validate(self) -> None:
        super().validate()
        _require_enum(self.decision, "decision", AUDIT_DECISIONS)
        _require_score(self.clarity_score, "clarity_score")
        _require_score(self.feasibility_score, "feasibility_score")
        _require_score(self.testability_score, "testability_score")
        _require_score(self.risk_score, "risk_score")
        _require_str_list(self.missing_requirements, "missing_requirements")
        _require_str_list(self.unsafe_assumptions, "unsafe_assumptions")
        if not isinstance(self.required_followup_questions, list):
            raise SchemaValidationError("required_followup_questions must be a list")
        for index, question in enumerate(self.required_followup_questions):
            if not isinstance(question, StructuredQuestion):
                raise SchemaValidationError(f"required_followup_questions[{index}] must be a StructuredQuestion")
            question.validate()
        _require_str_list(self.spec_patch_suggestions, "spec_patch_suggestions")
        _require_enum(self.routing_recommendation, "routing_recommendation", ROUTING_RECOMMENDATIONS)
        _require_string(self.approval_rationale, "approval_rationale")
        _require_optional_ref(self.elicitation_report_ref, "elicitation_report_ref")
        _require_optional_ref(self.feasibility_report_ref, "feasibility_report_ref")


@dataclass
class TaskContract(SchemaModel):
    """Canonical Front Desk task contract handed to build workers by ref."""

    job_id: str
    round_index: int
    semantic_lock_ref: str
    semantic_lock_hash: str
    semantic_summary: str
    requirement_clauses: list[str]
    skill_spec_ref: str
    acceptance_criteria_ref: str
    verification_spec_ref: str
    worker_input_ref: str
    build_contract_ref: str
    execution_boundary: dict[str, JsonValue]
    product_identity_terms: list[str] = field(default_factory=list)
    domain_terms: list[str] = field(default_factory=list)
    implementation_requirements: list[str] = field(default_factory=list)
    delivery_requirements: list[str] = field(default_factory=list)
    must_not: list[str] = field(default_factory=list)
    semantic_lock_available: bool = True
    semantic_lock_truncated: bool = False
    omission_warnings: list[str] = field(default_factory=list)
    source_turn_ids: list[str] = field(default_factory=list)
    source_char_count: int = 0
    sanitized_char_count: int = 0
    redaction_applied: bool = False
    source_trace: list[dict[str, JsonValue]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "skillfoundry.frontdesk_task_contract.v1"

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        _require_positive_int(self.round_index, "round_index")
        _require_ref(self.semantic_lock_ref, "semantic_lock_ref")
        _require_sha256(self.semantic_lock_hash, "semantic_lock_hash")
        _require_non_empty_str(self.semantic_summary, "semantic_summary")
        _require_str_list(self.requirement_clauses, "requirement_clauses")
        if not self.requirement_clauses:
            raise SchemaValidationError("requirement_clauses must not be empty")
        for field_name in (
            "skill_spec_ref",
            "acceptance_criteria_ref",
            "verification_spec_ref",
            "worker_input_ref",
            "build_contract_ref",
        ):
            _require_ref(getattr(self, field_name), field_name)
        _require_task_execution_boundary(self.execution_boundary, "execution_boundary")
        _require_str_list(self.product_identity_terms, "product_identity_terms")
        _require_str_list(self.domain_terms, "domain_terms")
        _require_str_list(self.implementation_requirements, "implementation_requirements")
        _require_str_list(self.delivery_requirements, "delivery_requirements")
        _require_str_list(self.must_not, "must_not")
        _require_bool(self.semantic_lock_available, "semantic_lock_available")
        _require_bool(self.semantic_lock_truncated, "semantic_lock_truncated")
        _require_str_list(self.omission_warnings, "omission_warnings")
        _require_str_list(self.source_turn_ids, "source_turn_ids")
        _require_non_negative_int(self.source_char_count, "source_char_count")
        _require_non_negative_int(self.sanitized_char_count, "sanitized_char_count")
        _require_bool(self.redaction_applied, "redaction_applied")
        _require_json_object_list(self.source_trace, "source_trace")
        _require_non_empty_str(self.created_at, "created_at")


@dataclass
class FreezeManifest(SchemaModel):
    conversation_summary_hash: str
    conversation_turn_range: list[int]
    elicitation_report_ref: str
    spec_audit_report_ref: str
    skill_spec_ref: str
    acceptance_criteria_ref: str
    verification_spec_ref: str
    worker_input_ref: str
    build_contract_ref: str
    task_contract_ref: str | None = None
    artifact_hashes: dict[str, str] = field(default_factory=dict)
    freeze_gate_result_ref: str | None = None
    created_at: str = field(default_factory=utc_now)
    schema_version: str = "skillfoundry.freeze_manifest.v1"

    def validate(self) -> None:
        super().validate()
        _require_sha256(self.conversation_summary_hash, "conversation_summary_hash")
        if (
            not isinstance(self.conversation_turn_range, list)
            or len(self.conversation_turn_range) != 2
            or any(isinstance(item, bool) or not isinstance(item, int) for item in self.conversation_turn_range)
        ):
            raise SchemaValidationError("conversation_turn_range must be a two-item integer list")
        start, end = self.conversation_turn_range
        if start <= 0 or end < start:
            raise SchemaValidationError("conversation_turn_range must be a positive inclusive range")
        for field_name in (
            "elicitation_report_ref",
            "spec_audit_report_ref",
            "skill_spec_ref",
            "acceptance_criteria_ref",
            "verification_spec_ref",
            "worker_input_ref",
            "build_contract_ref",
        ):
            _require_ref(getattr(self, field_name), field_name)
        _require_optional_ref(self.task_contract_ref, "task_contract_ref")
        _require_hash_mapping(self.artifact_hashes, "artifact_hashes")
        for artifact_ref in self.artifact_hashes:
            _require_ref(artifact_ref, f"artifact_hashes key {artifact_ref}")
        _require_optional_ref(self.freeze_gate_result_ref, "freeze_gate_result_ref")
        _require_non_empty_str(self.created_at, "created_at")


@dataclass
class FrontDeskState(SchemaModel):
    job_id: str
    stage: str = "front_desk"
    frontdesk_phase: str = "core_need_discovery"
    clarification_round: int = 0
    core_need_round: int = 0
    plan_revision_count: int = 0
    readiness: str = "new_conversation"
    latest_core_need_report_ref: str | None = None
    core_need_brief_ref: str | None = None
    decision_ledger_ref: str | None = None
    solution_plan_ref: str | None = None
    solution_plan_markdown_ref: str | None = None
    latest_plan_review_ref: str | None = None
    latest_elicitation_report_ref: str | None = None
    latest_audit_report_ref: str | None = None
    skill_spec_ref: str | None = None
    acceptance_criteria_ref: str | None = None
    verification_spec_ref: str | None = None
    next_action: str = "elicit"
    human_review_required: bool = False
    frontdesk_budget_ref: str | None = "frontdesk/budget.json"
    risk_report_ref: str | None = "frontdesk/risk_report.json"
    freeze_gate_result_ref: str | None = None
    freeze_manifest_ref: str | None = None
    acceptance_coverage_plan_ref: str | None = None
    schema_version: str = "skillfoundry.frontdesk_state.v1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Self:
        if not isinstance(payload, Mapping):
            raise SchemaValidationError("FrontDeskState payload must be a JSON object")
        forbidden = sorted(set(payload) & FORBIDDEN_STATE_FIELDS)
        if forbidden:
            raise SchemaValidationError(
                "FrontDeskState stores artifact refs only; raw field(s) are not allowed: "
                + ", ".join(forbidden)
            )
        return super().from_dict(payload)

    def validate(self) -> None:
        super().validate()
        _require_non_empty_str(self.job_id, "job_id")
        _require_enum(self.stage, "stage", FRONTDESK_STAGES)
        _require_enum(self.frontdesk_phase, "frontdesk_phase", FRONTDESK_PHASES)
        _require_non_negative_int(self.clarification_round, "clarification_round")
        _require_non_negative_int(self.core_need_round, "core_need_round")
        _require_non_negative_int(self.plan_revision_count, "plan_revision_count")
        _require_enum(self.readiness, "readiness", FRONTDESK_READINESS)
        for field_name in (
            "latest_core_need_report_ref",
            "core_need_brief_ref",
            "decision_ledger_ref",
            "solution_plan_ref",
            "solution_plan_markdown_ref",
            "latest_plan_review_ref",
            "latest_elicitation_report_ref",
            "latest_audit_report_ref",
            "skill_spec_ref",
            "acceptance_criteria_ref",
            "verification_spec_ref",
            "frontdesk_budget_ref",
            "risk_report_ref",
            "freeze_gate_result_ref",
            "freeze_manifest_ref",
            "acceptance_coverage_plan_ref",
        ):
            _require_optional_ref(getattr(self, field_name), field_name)
        _require_enum(self.next_action, "next_action", FRONTDESK_NEXT_ACTIONS)
        _require_bool(self.human_review_required, "human_review_required")


@dataclass
class FrontDeskConfig(SchemaModel):
    max_clarification_rounds: int = 10
    max_core_need_rounds: int = 5
    max_plan_revision_rounds: int = 3
    max_questions_per_core_need_round: int = 1
    max_open_confirmation_items: int = 3
    max_total_frontdesk_rounds: int = 12
    min_clarity_score: float = 0.75
    min_feasibility_score: float = 0.70
    min_testability_score: float = 0.75
    max_followup_questions_per_round: int = 1
    max_frontdesk_model_calls: int = 40
    max_parse_repair_attempts: int = 2
    provider_timeout_seconds: int = 60
    max_output_tokens_per_call: int = 4096
    max_total_tokens: int | None = None
    max_provider_cost_usd: float = 5.0
    risk_policy_ref: str | None = None
    schema_version: str = "skillfoundry.frontdesk_config.v1"

    def validate(self) -> None:
        super().validate()
        for field_name in (
            "max_clarification_rounds",
            "max_core_need_rounds",
            "max_plan_revision_rounds",
            "max_questions_per_core_need_round",
            "max_open_confirmation_items",
            "max_total_frontdesk_rounds",
            "max_followup_questions_per_round",
            "max_frontdesk_model_calls",
            "max_parse_repair_attempts",
            "provider_timeout_seconds",
            "max_output_tokens_per_call",
        ):
            _require_positive_int(getattr(self, field_name), field_name)
        if self.max_total_tokens is not None:
            _require_positive_int(self.max_total_tokens, "max_total_tokens")
        _require_score(self.min_clarity_score, "min_clarity_score")
        _require_score(self.min_feasibility_score, "min_feasibility_score")
        _require_score(self.min_testability_score, "min_testability_score")
        _require_positive_number(self.max_provider_cost_usd, "max_provider_cost_usd")
        _require_optional_ref(self.risk_policy_ref, "risk_policy_ref")
