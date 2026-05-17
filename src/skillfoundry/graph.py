"""WP2 LangGraph skeleton with refs-only state.

This module intentionally contains deterministic stub nodes. It owns workflow
routing and checkpointable state shape only; worker, verifier, registry, model,
runtime, and ContextForge behavior are later work packages.
"""

from __future__ import annotations

from enum import StrEnum
import re
from typing import Any, Mapping, TypedDict

from langgraph.graph import END, START, StateGraph

from .schema import SchemaValidationError, ensure_json_compatible, sha256_json


MAX_INLINE_STRING_BYTES = 1024

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class StateValidationError(ValueError):
    """Raised when LangGraph state violates the WP2 refs-only contract."""


class Route(StrEnum):
    """Top-level routing decisions supported by the WP2 skeleton."""

    BUILD_NEW = "build_new"
    REUSE_EXISTING = "reuse_existing"
    REJECT_UNSAFE = "reject_unsafe"
    ASK_CLARIFYING_QUESTION = "ask_clarifying_question"


class Stage(StrEnum):
    """Workflow stage names stored in lightweight graph state."""

    INTAKE = "intake"
    CLARIFY = "clarify"
    SPEC_GENERATE = "spec_generate"
    ROUTE = "route"
    PREPARE_WORKSPACE = "prepare_workspace"
    BUILD = "build"
    VERIFY = "verify"
    REPAIR_OR_REGISTER = "repair_or_register"
    REPAIR = "repair"
    REUSE_EXISTING = "reuse_existing"
    SAFE_STOP = "safe_stop"
    HUMAN_REVIEW = "human_review"
    EMIT_REPORT = "emit_report"


class WorkflowStatus(StrEnum):
    """Compact workflow statuses for checkpoint and resume decisions."""

    RUNNING = "running"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"
    REUSED = "reused"
    BUILT = "built"
    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"
    REPAIR_PLANNED = "repair_planned"
    REGISTERED = "registered"
    REPORT_EMITTED = "report_emitted"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    FAIL_CLOSED = "fail_closed"


class NextAction(StrEnum):
    """Internal compact actions used by conditional edges."""

    ROUTE = "route"
    BUILD_NEW = "build_new"
    REUSE_EXISTING = "reuse_existing"
    REJECT_UNSAFE = "reject_unsafe"
    ASK_CLARIFYING_QUESTION = "ask_clarifying_question"
    SPEC_GENERATE = "spec_generate"
    PREPARE_WORKSPACE = "prepare_workspace"
    BUILD = "build"
    VERIFY = "verify"
    REPAIR = "repair"
    REGISTER = "register"
    HUMAN_REVIEW = "human_review"
    EMIT_REPORT = "emit_report"
    STOP = "stop"


class SkillFoundryState(TypedDict, total=False):
    """Refs-only LangGraph state contract for WP2."""

    job_id: str
    stage: str
    status: str
    route: str
    attempt_count: int
    attempt_limit: int
    failure_class: str | None
    refs: dict[str, str]
    hashes: dict[str, str]
    next_action: str | None
    human_review_required: bool

    # Small deterministic stub controls and counters used by WP2 tests.
    verification_passed: bool
    fail_verify_until_attempt: int
    build_count: int
    repair_count: int
    reuse_existing_ref: str
    unsafe_detected: bool
    clarification_required: bool


_ALLOWED_STATE_KEYS = frozenset(SkillFoundryState.__annotations__)

_FORBIDDEN_STATE_KEYS = frozenset(
    {
        "full_skill_package",
        "large_prompt",
        "package_content",
        "prompt_text",
        "raw_logs",
        "raw_prompt",
        "raw_replay_bundle",
        "raw_tool_logs",
        "raw_transcript",
        "raw_verification_logs",
        "raw_worker_transcript",
        "replay_bundle",
        "skill_package",
        "tool_logs",
        "transcript",
        "verification_logs",
        "worker_transcript",
    }
)


def validate_graph_state(
    state: Mapping[str, Any],
    *,
    max_inline_string_bytes: int = MAX_INLINE_STRING_BYTES,
) -> None:
    """Validate that graph state is JSON-safe, small, and refs-only.

    The validator is deliberately stricter than a generic JSON validator:
    top-level keys must be part of the WP2 state contract, known raw artifact
    keys are rejected at any depth, refs must be small string references, and
    hashes must be lowercase SHA-256 hex digests.
    """

    if not isinstance(state, Mapping):
        raise StateValidationError("graph state must be a mapping")

    _reject_forbidden_keys_and_large_strings(state, "$", max_inline_string_bytes)

    unknown = sorted(set(state) - _ALLOWED_STATE_KEYS)
    if unknown:
        raise StateValidationError(f"state contains unsupported key(s): {', '.join(unknown)}")

    try:
        ensure_json_compatible(dict(state))
    except SchemaValidationError as exc:
        raise StateValidationError(str(exc)) from exc

    if "job_id" in state:
        _require_small_non_empty_string(state["job_id"], "job_id", max_inline_string_bytes)

    if "stage" in state:
        _coerce_stage(state["stage"])
    if "status" in state:
        _coerce_status(state["status"])
    if "route" in state:
        _coerce_route(state["route"])

    for key in ("attempt_count", "build_count", "repair_count", "fail_verify_until_attempt"):
        if key in state:
            _require_non_negative_int(state[key], key)
    if "attempt_limit" in state:
        _require_positive_int(state["attempt_limit"], "attempt_limit")

    if "failure_class" in state and state["failure_class"] is not None:
        _require_small_non_empty_string(state["failure_class"], "failure_class", max_inline_string_bytes)
    if "next_action" in state and state["next_action"] is not None:
        _coerce_next_action(state["next_action"])

    for key in ("human_review_required", "verification_passed", "unsafe_detected", "clarification_required"):
        if key in state and not isinstance(state[key], bool):
            raise StateValidationError(f"{key} must be a boolean")

    if "reuse_existing_ref" in state:
        _require_small_non_empty_string(state["reuse_existing_ref"], "reuse_existing_ref", max_inline_string_bytes)

    if "refs" in state:
        _validate_string_mapping(state["refs"], "refs", max_inline_string_bytes, require_sha256=False)
    if "hashes" in state:
        _validate_string_mapping(state["hashes"], "hashes", max_inline_string_bytes, require_sha256=True)


def build_skillfoundry_graph() -> StateGraph:
    """Build the uncompiled WP2 LangGraph workflow."""

    graph = StateGraph(SkillFoundryState)
    graph.add_node(Stage.INTAKE.value, intake_node)
    graph.add_node(Stage.CLARIFY.value, clarify_node)
    graph.add_node(Stage.SPEC_GENERATE.value, spec_generate_node)
    graph.add_node(Stage.ROUTE.value, route_node)
    graph.add_node(Stage.PREPARE_WORKSPACE.value, prepare_workspace_node)
    graph.add_node(Stage.BUILD.value, build_node)
    graph.add_node(Stage.VERIFY.value, verify_node)
    graph.add_node(Stage.REPAIR_OR_REGISTER.value, repair_or_register_node)
    graph.add_node(Stage.REPAIR.value, repair_node)
    graph.add_node(Stage.REUSE_EXISTING.value, reuse_existing_node)
    graph.add_node(Stage.SAFE_STOP.value, safe_stop_node)
    graph.add_node(Stage.HUMAN_REVIEW.value, human_review_node)
    graph.add_node(Stage.EMIT_REPORT.value, emit_report_node)

    graph.add_edge(START, Stage.INTAKE.value)
    graph.add_edge(Stage.INTAKE.value, Stage.CLARIFY.value)
    graph.add_conditional_edges(
        Stage.CLARIFY.value,
        _after_clarify,
        {
            Stage.SPEC_GENERATE.value: Stage.SPEC_GENERATE.value,
            Stage.HUMAN_REVIEW.value: Stage.HUMAN_REVIEW.value,
        },
    )
    graph.add_edge(Stage.SPEC_GENERATE.value, Stage.ROUTE.value)
    graph.add_conditional_edges(
        Stage.ROUTE.value,
        _after_route,
        {
            Route.BUILD_NEW.value: Stage.PREPARE_WORKSPACE.value,
            Route.REUSE_EXISTING.value: Stage.REUSE_EXISTING.value,
            Route.REJECT_UNSAFE.value: Stage.SAFE_STOP.value,
            Route.ASK_CLARIFYING_QUESTION.value: Stage.HUMAN_REVIEW.value,
        },
    )
    graph.add_edge(Stage.PREPARE_WORKSPACE.value, Stage.BUILD.value)
    graph.add_edge(Stage.BUILD.value, Stage.VERIFY.value)
    graph.add_edge(Stage.VERIFY.value, Stage.REPAIR_OR_REGISTER.value)
    graph.add_conditional_edges(
        Stage.REPAIR_OR_REGISTER.value,
        _after_repair_or_register,
        {
            Stage.EMIT_REPORT.value: Stage.EMIT_REPORT.value,
            Stage.REPAIR.value: Stage.REPAIR.value,
            Stage.HUMAN_REVIEW.value: Stage.HUMAN_REVIEW.value,
        },
    )
    graph.add_edge(Stage.REPAIR.value, Stage.BUILD.value)
    graph.add_edge(Stage.REUSE_EXISTING.value, Stage.EMIT_REPORT.value)
    graph.add_edge(Stage.SAFE_STOP.value, END)
    graph.add_edge(Stage.HUMAN_REVIEW.value, END)
    graph.add_edge(Stage.EMIT_REPORT.value, END)
    return graph


def compile_skillfoundry_graph(
    *,
    checkpointer: Any | None = None,
    interrupt_before: list[str] | str | None = None,
    interrupt_after: list[str] | str | None = None,
    debug: bool = False,
) -> Any:
    """Compile the WP2 graph, forwarding checkpoint and interrupt options."""

    return build_skillfoundry_graph().compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
        interrupt_after=interrupt_after,
        debug=debug,
    )


def intake_node(state: SkillFoundryState) -> SkillFoundryState:
    _validate_input_state(state)
    job_id = state.get("job_id")
    if not job_id:
        raise StateValidationError("job_id is required")

    refs = _merge_refs(state, job_workspace=f"runs/{job_id}")
    update: SkillFoundryState = {
        "stage": Stage.INTAKE.value,
        "status": WorkflowStatus.RUNNING.value,
        "attempt_count": int(state.get("attempt_count", 0)),
        "attempt_limit": int(state.get("attempt_limit", 1)),
        "refs": refs,
        "hashes": dict(state.get("hashes", {})),
        "human_review_required": bool(state.get("human_review_required", False)),
        "build_count": int(state.get("build_count", 0)),
        "repair_count": int(state.get("repair_count", 0)),
        "next_action": NextAction.SPEC_GENERATE.value,
    }
    return _validated_update(state, update)


def clarify_node(state: SkillFoundryState) -> SkillFoundryState:
    update: SkillFoundryState = {
        "stage": Stage.CLARIFY.value,
        "status": WorkflowStatus.NEEDS_CLARIFICATION.value
        if state.get("route") == Route.ASK_CLARIFYING_QUESTION.value
        else WorkflowStatus.RUNNING.value,
        "human_review_required": state.get("route") == Route.ASK_CLARIFYING_QUESTION.value,
        "next_action": NextAction.HUMAN_REVIEW.value
        if state.get("route") == Route.ASK_CLARIFYING_QUESTION.value
        else NextAction.SPEC_GENERATE.value,
    }
    if state.get("route") == Route.ASK_CLARIFYING_QUESTION.value:
        update["refs"] = _merge_refs(state, clarification_request="human_review/clarification_request.json")
    return _validated_update(state, update)


def spec_generate_node(state: SkillFoundryState) -> SkillFoundryState:
    job_id = _job_id(state)
    refs = _merge_refs(
        state,
        skill_spec="skill_spec.yaml",
        verification_spec="verification_spec.yaml",
    )
    hashes = _merge_hashes(
        state,
        skill_spec_hash=_stub_hash(job_id, "skill_spec.yaml"),
        verification_spec_hash=_stub_hash(job_id, "verification_spec.yaml"),
    )
    update: SkillFoundryState = {
        "stage": Stage.SPEC_GENERATE.value,
        "status": WorkflowStatus.RUNNING.value,
        "refs": refs,
        "hashes": hashes,
        "next_action": NextAction.ROUTE.value,
    }
    return _validated_update(state, update)


def route_node(state: SkillFoundryState) -> SkillFoundryState:
    route = _determine_route(state)
    update: SkillFoundryState = {
        "stage": Stage.ROUTE.value,
        "status": WorkflowStatus.RUNNING.value,
        "route": route.value,
        "next_action": route.value,
    }
    return _validated_update(state, update)


def prepare_workspace_node(state: SkillFoundryState) -> SkillFoundryState:
    job_id = _job_id(state)
    refs = _merge_refs(
        state,
        build_contract="build_contract.yaml",
        worker_input="worker_input.md",
        artifact_manifest="artifact_manifest.json",
    )
    hashes = _merge_hashes(
        state,
        build_contract_hash=_stub_hash(job_id, "build_contract.yaml"),
        worker_input_hash=_stub_hash(job_id, "worker_input.md"),
        artifact_manifest_hash=_stub_hash(job_id, "artifact_manifest.json"),
    )
    update: SkillFoundryState = {
        "stage": Stage.PREPARE_WORKSPACE.value,
        "status": WorkflowStatus.RUNNING.value,
        "refs": refs,
        "hashes": hashes,
        "next_action": NextAction.BUILD.value,
    }
    return _validated_update(state, update)


def build_node(state: SkillFoundryState) -> SkillFoundryState:
    job_id = _job_id(state)
    attempt_number = int(state.get("attempt_count", 0)) + 1
    attempt_id = f"{attempt_number:03d}"
    attempt_dir = f"attempts/{attempt_id}"
    refs = _merge_refs(
        state,
        current_attempt=attempt_dir,
        current_package="package",
        current_skill="package/SKILL.md",
        execution_report=f"{attempt_dir}/execution_report.json",
        output_diff=f"{attempt_dir}/output_diff.patch",
        worker_transcript_ref=f"{attempt_dir}/worker_transcript.log",
        **{f"attempt_{attempt_id}_execution_report": f"{attempt_dir}/execution_report.json"},
    )
    hashes = _merge_hashes(
        state,
        package_hash=_stub_hash(job_id, f"package-attempt-{attempt_id}"),
        workspace_hash_after=_stub_hash(job_id, f"workspace-after-{attempt_id}"),
    )
    update: SkillFoundryState = {
        "stage": Stage.BUILD.value,
        "status": WorkflowStatus.BUILT.value,
        "attempt_count": attempt_number,
        "build_count": int(state.get("build_count", 0)) + 1,
        "refs": refs,
        "hashes": hashes,
        "next_action": NextAction.VERIFY.value,
    }
    return _validated_update(state, update)


def verify_node(state: SkillFoundryState) -> SkillFoundryState:
    job_id = _job_id(state)
    attempt_id = f"{int(state.get('attempt_count', 0)):03d}"
    passed = _verification_passed(state)
    refs = _merge_refs(state, verification_result=f"verifier/verification_result_attempt_{attempt_id}.json")
    hashes = _merge_hashes(
        state,
        verification_result_hash=_stub_hash(job_id, f"verification-result-{attempt_id}-{passed}"),
    )
    update: SkillFoundryState = {
        "stage": Stage.VERIFY.value,
        "status": WorkflowStatus.VERIFIED.value if passed else WorkflowStatus.VERIFICATION_FAILED.value,
        "failure_class": None if passed else "stub_verification_failure",
        "refs": refs,
        "hashes": hashes,
        "next_action": NextAction.REGISTER.value if passed else NextAction.REPAIR.value,
    }
    return _validated_update(state, update)


def repair_or_register_node(state: SkillFoundryState) -> SkillFoundryState:
    job_id = _job_id(state)
    if state.get("status") == WorkflowStatus.VERIFIED.value:
        refs = _merge_refs(state, registry_decision="registry/decision.json", registry_entry="registry/entry.json")
        hashes = _merge_hashes(state, registry_decision_hash=_stub_hash(job_id, "registry-decision"))
        update: SkillFoundryState = {
            "stage": Stage.REPAIR_OR_REGISTER.value,
            "status": WorkflowStatus.REGISTERED.value,
            "refs": refs,
            "hashes": hashes,
            "human_review_required": False,
            "next_action": NextAction.EMIT_REPORT.value,
        }
        return _validated_update(state, update)

    if int(state.get("attempt_count", 0)) < int(state.get("attempt_limit", 1)):
        update = {
            "stage": Stage.REPAIR_OR_REGISTER.value,
            "status": WorkflowStatus.REPAIR_PLANNED.value,
            "human_review_required": False,
            "next_action": NextAction.REPAIR.value,
        }
        return _validated_update(state, update)

    update = {
        "stage": Stage.REPAIR_OR_REGISTER.value,
        "status": WorkflowStatus.FAIL_CLOSED.value,
        "human_review_required": True,
        "next_action": NextAction.HUMAN_REVIEW.value,
    }
    return _validated_update(state, update)


def repair_node(state: SkillFoundryState) -> SkillFoundryState:
    job_id = _job_id(state)
    next_attempt_id = f"{int(state.get('attempt_count', 0)) + 1:03d}"
    refs = _merge_refs(
        state,
        repair_instructions=f"attempts/{next_attempt_id}/repair_instructions.md",
        repair_basis=state.get("refs", {}).get("verification_result", "verifier/verification_result.json"),
    )
    hashes = _merge_hashes(state, repair_plan_hash=_stub_hash(job_id, f"repair-plan-{next_attempt_id}"))
    update: SkillFoundryState = {
        "stage": Stage.REPAIR.value,
        "status": WorkflowStatus.REPAIR_PLANNED.value,
        "repair_count": int(state.get("repair_count", 0)) + 1,
        "refs": refs,
        "hashes": hashes,
        "next_action": NextAction.BUILD.value,
    }
    return _validated_update(state, update)


def reuse_existing_node(state: SkillFoundryState) -> SkillFoundryState:
    reuse_ref = state.get("reuse_existing_ref", "registry/reused_skill.json")
    refs = _merge_refs(state, registry_entry=reuse_ref, reused_skill=reuse_ref)
    update: SkillFoundryState = {
        "stage": Stage.REUSE_EXISTING.value,
        "status": WorkflowStatus.REUSED.value,
        "refs": refs,
        "build_count": int(state.get("build_count", 0)),
        "next_action": NextAction.EMIT_REPORT.value,
    }
    return _validated_update(state, update)


def safe_stop_node(state: SkillFoundryState) -> SkillFoundryState:
    refs = _merge_refs(state, safety_report="verifier/safety_stop.json")
    update: SkillFoundryState = {
        "stage": Stage.SAFE_STOP.value,
        "status": WorkflowStatus.REJECTED.value,
        "failure_class": "unsafe_requirement",
        "refs": refs,
        "human_review_required": False,
        "next_action": None,
    }
    return _validated_update(state, update)


def human_review_node(state: SkillFoundryState) -> SkillFoundryState:
    refs = _merge_refs(state, human_review_request="human_review/request.json")
    status = (
        WorkflowStatus.FAIL_CLOSED.value
        if state.get("status") == WorkflowStatus.FAIL_CLOSED.value
        else WorkflowStatus.HUMAN_REVIEW_REQUIRED.value
    )
    update: SkillFoundryState = {
        "stage": Stage.HUMAN_REVIEW.value,
        "status": status,
        "refs": refs,
        "human_review_required": True,
        "next_action": None,
    }
    return _validated_update(state, update)


def emit_report_node(state: SkillFoundryState) -> SkillFoundryState:
    refs = _merge_refs(state, final_report="verifier/final_report.json")
    hashes = _merge_hashes(state, final_report_hash=_stub_hash(_job_id(state), "final-report"))
    update: SkillFoundryState = {
        "stage": Stage.EMIT_REPORT.value,
        "status": WorkflowStatus.REPORT_EMITTED.value,
        "refs": refs,
        "hashes": hashes,
        "next_action": None,
    }
    return _validated_update(state, update)


def _after_clarify(state: SkillFoundryState) -> str:
    validate_graph_state(state)
    if state.get("route") == Route.ASK_CLARIFYING_QUESTION.value or state.get("clarification_required"):
        return Stage.HUMAN_REVIEW.value
    return Stage.SPEC_GENERATE.value


def _after_route(state: SkillFoundryState) -> str:
    validate_graph_state(state)
    return _coerce_route(state.get("route")).value


def _after_repair_or_register(state: SkillFoundryState) -> str:
    validate_graph_state(state)
    if state.get("next_action") == NextAction.EMIT_REPORT.value:
        return Stage.EMIT_REPORT.value
    if state.get("next_action") == NextAction.REPAIR.value:
        return Stage.REPAIR.value
    return Stage.HUMAN_REVIEW.value


def _determine_route(state: SkillFoundryState) -> Route:
    if "route" in state and state["route"]:
        return _coerce_route(state["route"])
    if state.get("unsafe_detected"):
        return Route.REJECT_UNSAFE
    if state.get("clarification_required"):
        return Route.ASK_CLARIFYING_QUESTION
    if state.get("reuse_existing_ref"):
        return Route.REUSE_EXISTING
    return Route.BUILD_NEW


def _verification_passed(state: SkillFoundryState) -> bool:
    if "fail_verify_until_attempt" in state:
        return int(state.get("attempt_count", 0)) > int(state["fail_verify_until_attempt"])
    return bool(state.get("verification_passed", True))


def _validated_update(state: SkillFoundryState, update: SkillFoundryState) -> SkillFoundryState:
    merged = dict(state)
    merged.update(update)
    validate_graph_state(merged)
    return update


def _validate_input_state(state: SkillFoundryState) -> None:
    validate_graph_state(state)


def _job_id(state: SkillFoundryState) -> str:
    job_id = state.get("job_id")
    if not job_id:
        raise StateValidationError("job_id is required")
    return job_id


def _merge_refs(state: SkillFoundryState, **updates: str) -> dict[str, str]:
    refs = dict(state.get("refs", {}))
    refs.update(updates)
    return refs


def _merge_hashes(state: SkillFoundryState, **updates: str) -> dict[str, str]:
    hashes = dict(state.get("hashes", {}))
    hashes.update(updates)
    return hashes


def _stub_hash(job_id: str, artifact: str) -> str:
    return sha256_json({"artifact": artifact, "job_id": job_id, "wp": "wp2-langgraph-skeleton"})


def _coerce_route(value: Any) -> Route:
    try:
        return Route(str(value))
    except ValueError as exc:
        raise StateValidationError(f"route is not supported: {value!r}") from exc


def _coerce_stage(value: Any) -> Stage:
    try:
        return Stage(str(value))
    except ValueError as exc:
        raise StateValidationError(f"stage is not supported: {value!r}") from exc


def _coerce_status(value: Any) -> WorkflowStatus:
    try:
        return WorkflowStatus(str(value))
    except ValueError as exc:
        raise StateValidationError(f"status is not supported: {value!r}") from exc


def _coerce_next_action(value: Any) -> NextAction:
    try:
        return NextAction(str(value))
    except ValueError as exc:
        raise StateValidationError(f"next_action is not supported: {value!r}") from exc


def _require_small_non_empty_string(value: Any, field_name: str, max_inline_string_bytes: int) -> None:
    if not isinstance(value, str) or not value.strip():
        raise StateValidationError(f"{field_name} must be a non-empty string")
    _check_string_size(value, field_name, max_inline_string_bytes)


def _require_non_negative_int(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise StateValidationError(f"{field_name} must be a non-negative integer")


def _require_positive_int(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise StateValidationError(f"{field_name} must be a positive integer")


def _validate_string_mapping(
    value: Any,
    field_name: str,
    max_inline_string_bytes: int,
    *,
    require_sha256: bool,
) -> None:
    if not isinstance(value, Mapping):
        raise StateValidationError(f"{field_name} must be a mapping of strings")
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise StateValidationError(f"{field_name} contains a non-string or empty key")
        _check_string_size(key, f"{field_name} key", max_inline_string_bytes)
        if not isinstance(item, str) or not item.strip():
            raise StateValidationError(f"{field_name}.{key} must be a non-empty string")
        _check_string_size(item, f"{field_name}.{key}", max_inline_string_bytes)
        if require_sha256 and not SHA256_RE.fullmatch(item):
            raise StateValidationError(f"{field_name}.{key} must be a lowercase sha256 hex digest")


def _reject_forbidden_keys_and_large_strings(value: Any, path: str, max_inline_string_bytes: int) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise StateValidationError(f"{path} contains a non-string key")
            normalized_key = key.lower().replace("-", "_")
            if normalized_key in _FORBIDDEN_STATE_KEYS:
                raise StateValidationError(f"{path}.{key} is forbidden in refs-only graph state")
            _check_string_size(key, f"{path}.{key} key", max_inline_string_bytes)
            _reject_forbidden_keys_and_large_strings(item, f"{path}.{key}", max_inline_string_bytes)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_forbidden_keys_and_large_strings(item, f"{path}[{index}]", max_inline_string_bytes)
        return
    if isinstance(value, str):
        _check_string_size(value, path, max_inline_string_bytes)


def _check_string_size(value: str, path: str, max_inline_string_bytes: int) -> None:
    if len(value.encode("utf-8")) > max_inline_string_bytes:
        raise StateValidationError(f"{path} exceeds {max_inline_string_bytes} bytes")
