"""SkillFoundry v2 LangGraph spine around ContextForge Goal Harness refs."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
import re
from typing import Any, Mapping, TypedDict

from langgraph.graph import END, START, StateGraph

from .goal_runtime import OfflineVerificationMode, run_offline_goal_harness
from .schema import SchemaValidationError, ensure_json_compatible
from .workspace import JobWorkspace


MAX_V2_INLINE_STRING_BYTES = 1024
SHA256_REF_RE = re.compile(r"^(sha256:)?[0-9a-f]{64}$")


class V2StateValidationError(ValueError):
    """Raised when SkillFoundry v2 graph state stops being refs-only."""


class V2Stage(StrEnum):
    FREEZE_CONTRACTS = "freeze_contracts"
    BUILD_GOAL_NODE = "build_goal_node"
    VERIFY = "verify"
    ROUTE_AFTER_VERIFICATION = "route_after_verification"
    REPAIR_GOAL_NODE = "repair_goal_node"
    REGISTRY_GATE = "registry_gate"
    HUMAN_REVIEW = "human_review"
    REDESIGN = "redesign"
    REJECT = "reject"
    EMIT_REPORT = "emit_report"


class V2Status(StrEnum):
    RUNNING = "running"
    READY_TO_BUILD = "ready_to_build"
    BUILD_RECORDED = "build_recorded"
    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"
    REPAIR_PLANNED = "repair_planned"
    REGISTERED = "registered"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    REDESIGN_REQUIRED = "redesign_required"
    REJECTED = "rejected"
    REPORT_EMITTED = "report_emitted"


class V2Route(StrEnum):
    CONTINUE = "continue"
    REGISTRY_GATE = "registry_gate"
    REPAIR_GOAL_NODE = "repair_goal_node"
    HUMAN_REVIEW = "human_review"
    REDESIGN = "redesign"
    REJECT = "reject"


class SkillFoundryV2State(TypedDict, total=False):
    """Refs-only state shape for the SkillFoundry v2 graph spine."""

    schema_version: str
    job_id: str
    stage: str
    status: str
    attempt_count: int
    attempt_limit: int
    refs: dict[str, str]
    hashes: dict[str, str]
    contextforge: dict[str, Any]
    next_route: str
    human_review_required: bool


V2Node = Callable[[SkillFoundryV2State], SkillFoundryV2State]

_STATE_SCHEMA_VERSION = "skillfoundry.graph_v2_state.v1"
_ALLOWED_STATE_KEYS = frozenset(SkillFoundryV2State.__annotations__)
_FORBIDDEN_RAW_KEYS = frozenset(
    {
        "conversation",
        "conversation_jsonl",
        "full_skill_package",
        "large_prompt",
        "messages",
        "model_output",
        "package_content",
        "prompt",
        "prompt_text",
        "raw_conversation",
        "raw_frontdesk_conversation",
        "raw_logs",
        "raw_model_response",
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


def validate_v2_graph_state(
    state: Mapping[str, Any],
    *,
    max_inline_string_bytes: int = MAX_V2_INLINE_STRING_BYTES,
) -> None:
    """Fail closed unless state is JSON-safe, small, and refs/IDs-only."""

    if not isinstance(state, Mapping):
        raise V2StateValidationError("v2 graph state must be a mapping")

    unknown = sorted(set(state) - _ALLOWED_STATE_KEYS)
    if unknown:
        raise V2StateValidationError(f"state contains unsupported key(s): {', '.join(unknown)}")

    _reject_raw_keys_and_large_strings(state, "$", max_inline_string_bytes)
    try:
        ensure_json_compatible(dict(state))
    except SchemaValidationError as exc:
        raise V2StateValidationError(str(exc)) from exc

    if "schema_version" in state:
        _require_small_non_empty_string(state["schema_version"], "schema_version", max_inline_string_bytes)
    if "job_id" in state:
        _require_small_non_empty_string(state["job_id"], "job_id", max_inline_string_bytes)
    if "stage" in state:
        _coerce_stage(state["stage"])
    if "status" in state:
        _coerce_status(state["status"])
    if "next_route" in state:
        _coerce_route(state["next_route"])
    if "attempt_count" in state:
        _require_non_negative_int(state["attempt_count"], "attempt_count")
    if "attempt_limit" in state:
        _require_positive_int(state["attempt_limit"], "attempt_limit")
    if "human_review_required" in state and not isinstance(state["human_review_required"], bool):
        raise V2StateValidationError("human_review_required must be a boolean")
    if "refs" in state:
        _validate_string_mapping(state["refs"], "refs", max_inline_string_bytes, require_hash=False)
    if "hashes" in state:
        _validate_string_mapping(state["hashes"], "hashes", max_inline_string_bytes, require_hash=True)
    if "contextforge" in state:
        _validate_contextforge_state(state["contextforge"], max_inline_string_bytes)


def route_after_verification(state: Mapping[str, Any]) -> str:
    """Return the next v2 route from ContextForge verification state."""

    validate_v2_graph_state(state)
    contextforge = state.get("contextforge", {})
    if not isinstance(contextforge, Mapping):
        raise V2StateValidationError("contextforge must be a mapping")

    verification_status = _optional_str(contextforge.get("last_verification_status"))

    if verification_status == "passed":
        return V2Route.REGISTRY_GATE.value
    if verification_status == "failed":
        return V2Route.HUMAN_REVIEW.value if _attempts_exhausted(state) else V2Route.REPAIR_GOAL_NODE.value
    if verification_status in {"review_required", "human_acceptance_required"}:
        return V2Route.HUMAN_REVIEW.value
    if verification_status == "unsupported_verification_spec":
        return V2Route.REDESIGN.value

    decision = _optional_str(contextforge.get("last_goal_decision"))
    if decision == "complete":
        return V2Route.REGISTRY_GATE.value
    if decision == "repair":
        return V2Route.HUMAN_REVIEW.value if _attempts_exhausted(state) else V2Route.REPAIR_GOAL_NODE.value
    if decision == "redesign":
        return V2Route.REDESIGN.value
    if decision in {"escalate", "stop"}:
        return V2Route.HUMAN_REVIEW.value

    explicit = _optional_str(state.get("next_route")) or _optional_str(contextforge.get("next_route"))
    if explicit in {route.value for route in V2Route} and explicit != V2Route.CONTINUE.value:
        if explicit == V2Route.REPAIR_GOAL_NODE.value and _attempts_exhausted(state):
            return V2Route.HUMAN_REVIEW.value
        return explicit
    return V2Route.CONTINUE.value


def build_skillfoundry_v2_graph(
    *,
    build_node_callable: V2Node | None = None,
) -> StateGraph:
    """Build the v2 refs-only LangGraph spine."""

    graph = StateGraph(SkillFoundryV2State)
    graph.add_node(V2Stage.FREEZE_CONTRACTS.value, freeze_contracts_node)
    graph.add_node(V2Stage.BUILD_GOAL_NODE.value, build_node_callable or build_goal_node)
    graph.add_node(V2Stage.VERIFY.value, verify_node)
    graph.add_node(V2Stage.ROUTE_AFTER_VERIFICATION.value, route_after_verification_node)
    graph.add_node(V2Stage.REPAIR_GOAL_NODE.value, repair_goal_node)
    graph.add_node(V2Stage.REGISTRY_GATE.value, registry_gate_node)
    graph.add_node(V2Stage.HUMAN_REVIEW.value, human_review_node)
    graph.add_node(V2Stage.REDESIGN.value, redesign_node)
    graph.add_node(V2Stage.REJECT.value, reject_node)
    graph.add_node(V2Stage.EMIT_REPORT.value, emit_report_node)

    graph.add_edge(START, V2Stage.FREEZE_CONTRACTS.value)
    graph.add_edge(V2Stage.FREEZE_CONTRACTS.value, V2Stage.BUILD_GOAL_NODE.value)
    graph.add_edge(V2Stage.BUILD_GOAL_NODE.value, V2Stage.VERIFY.value)
    graph.add_edge(V2Stage.VERIFY.value, V2Stage.ROUTE_AFTER_VERIFICATION.value)
    graph.add_conditional_edges(
        V2Stage.ROUTE_AFTER_VERIFICATION.value,
        route_after_verification,
        {
            V2Route.CONTINUE.value: V2Stage.EMIT_REPORT.value,
            V2Route.REGISTRY_GATE.value: V2Stage.REGISTRY_GATE.value,
            V2Route.REPAIR_GOAL_NODE.value: V2Stage.REPAIR_GOAL_NODE.value,
            V2Route.HUMAN_REVIEW.value: V2Stage.HUMAN_REVIEW.value,
            V2Route.REDESIGN.value: V2Stage.REDESIGN.value,
            V2Route.REJECT.value: V2Stage.REJECT.value,
        },
    )
    graph.add_edge(V2Stage.REGISTRY_GATE.value, V2Stage.EMIT_REPORT.value)
    graph.add_edge(V2Stage.REPAIR_GOAL_NODE.value, END)
    graph.add_edge(V2Stage.HUMAN_REVIEW.value, END)
    graph.add_edge(V2Stage.REDESIGN.value, END)
    graph.add_edge(V2Stage.REJECT.value, END)
    graph.add_edge(V2Stage.EMIT_REPORT.value, END)
    return graph


def compile_skillfoundry_v2_graph(
    *,
    build_node_callable: V2Node | None = None,
    checkpointer: Any | None = None,
    interrupt_before: list[str] | str | None = None,
    interrupt_after: list[str] | str | None = None,
    debug: bool = False,
) -> Any:
    """Compile the v2 graph while preserving LangGraph checkpoint options."""

    return build_skillfoundry_v2_graph(build_node_callable=build_node_callable).compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
        interrupt_after=interrupt_after,
        debug=debug,
    )


def freeze_contracts_node(state: SkillFoundryV2State) -> SkillFoundryV2State:
    validate_v2_graph_state(state)
    job_id = _job_id(state)
    refs = _merge_refs(
        state,
        goal_contract="contextforge/goal_contract.json",
        build_node_contract="contextforge/build_node_contract.json",
        verification_gate="contextforge/verification_gate.json",
        contract_manifest="contextforge/contract_manifest.json",
    )
    update: SkillFoundryV2State = {
        "schema_version": str(state.get("schema_version") or _STATE_SCHEMA_VERSION),
        "job_id": job_id,
        "stage": V2Stage.FREEZE_CONTRACTS.value,
        "status": V2Status.READY_TO_BUILD.value,
        "attempt_count": int(state.get("attempt_count", 0)),
        "attempt_limit": int(state.get("attempt_limit", 1)),
        "refs": refs,
        "hashes": dict(state.get("hashes", {})),
        "contextforge": dict(state.get("contextforge", {})),
        "human_review_required": bool(state.get("human_review_required", False)),
        "next_route": V2Route.CONTINUE.value,
    }
    return _validated_update(state, update)


def build_goal_node(state: SkillFoundryV2State) -> SkillFoundryV2State:
    contextforge = dict(state.get("contextforge", {}))
    contextforge.setdefault("last_goal_run_id", _required_context_id(state, "last_goal_run_id", "pending-goal-run"))
    contextforge.setdefault("last_worker_run_id", _required_context_id(state, "last_worker_run_id", "pending-worker-run"))
    contextforge.setdefault("last_context_view_id", _required_context_id(state, "last_context_view_id", "pending-context-view"))
    contextforge.setdefault(
        "last_prompt_cache_plan_id",
        _required_context_id(state, "last_prompt_cache_plan_id", "pending-cache-plan"),
    )
    update: SkillFoundryV2State = {
        "stage": V2Stage.BUILD_GOAL_NODE.value,
        "status": V2Status.BUILD_RECORDED.value,
        "attempt_count": int(state.get("attempt_count", 0)) or 1,
        "contextforge": contextforge,
        "next_route": V2Route.CONTINUE.value,
    }
    return _validated_update(state, update)


def build_offline_goal_harness_node(
    runs_root: str | Path,
    *,
    verification_mode: OfflineVerificationMode = "pass",
    created_at: str | None = None,
) -> V2Node:
    """Return a v2 graph node backed by the offline Goal Harness slice."""

    runs_path = Path(runs_root)

    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        validate_v2_graph_state(state)
        job_id = _job_id(state)
        workspace = JobWorkspace(root=runs_path / job_id, job_id=job_id)
        result = run_offline_goal_harness(
            workspace,
            verification_mode=verification_mode,
            created_at=created_at,
        )
        runtime_state = result.graph_state
        refs = _merge_refs(state, **_string_mapping(runtime_state.get("refs", {}), "runtime refs"))
        hashes = dict(state.get("hashes", {}))
        hashes.update(_string_mapping(runtime_state.get("hashes", {}), "runtime hashes"))
        contextforge = dict(state.get("contextforge", {}))
        contextforge.update(_string_mapping(runtime_state.get("contextforge", {}), "runtime contextforge"))
        contextforge["last_goal_status"] = result.goal_run.status
        if result.goal_run.decision is not None:
            contextforge["last_goal_decision"] = result.goal_run.decision
        update: SkillFoundryV2State = {
            "schema_version": _STATE_SCHEMA_VERSION,
            "job_id": job_id,
            "stage": V2Stage.BUILD_GOAL_NODE.value,
            "status": V2Status.BUILD_RECORDED.value,
            "attempt_count": max(int(state.get("attempt_count", 0)), int(runtime_state.get("attempt_count", 1))),
            "attempt_limit": int(state.get("attempt_limit", 1)),
            "refs": refs,
            "hashes": hashes,
            "contextforge": contextforge,
            "human_review_required": bool(runtime_state.get("human_review_required", False)),
            "next_route": str(runtime_state.get("next_route", V2Route.CONTINUE.value)),
        }
        return _validated_update(state, update)

    return _node


def verify_node(state: SkillFoundryV2State) -> SkillFoundryV2State:
    status = _optional_str(state.get("contextforge", {}).get("last_verification_status"))
    if status == "passed":
        graph_status = V2Status.VERIFIED.value
    elif status == "failed":
        graph_status = V2Status.VERIFICATION_FAILED.value
    elif status in {"review_required", "human_acceptance_required"}:
        graph_status = V2Status.HUMAN_REVIEW_REQUIRED.value
    elif status == "unsupported_verification_spec":
        graph_status = V2Status.REDESIGN_REQUIRED.value
    else:
        graph_status = V2Status.RUNNING.value
    update: SkillFoundryV2State = {
        "stage": V2Stage.VERIFY.value,
        "status": graph_status,
        "next_route": route_after_verification(state),
    }
    return _validated_update(state, update)


def route_after_verification_node(state: SkillFoundryV2State) -> SkillFoundryV2State:
    route = route_after_verification(state)
    update: SkillFoundryV2State = {
        "stage": V2Stage.ROUTE_AFTER_VERIFICATION.value,
        "status": str(state.get("status", V2Status.RUNNING.value)),
        "next_route": route,
        "human_review_required": route == V2Route.HUMAN_REVIEW.value,
    }
    return _validated_update(state, update)


def registry_gate_node(state: SkillFoundryV2State) -> SkillFoundryV2State:
    refs = _merge_refs(state, registry_decision="registry/decision.json", registry_entry="registry/entry.json")
    update: SkillFoundryV2State = {
        "stage": V2Stage.REGISTRY_GATE.value,
        "status": V2Status.REGISTERED.value,
        "refs": refs,
        "human_review_required": False,
        "next_route": V2Route.CONTINUE.value,
    }
    return _validated_update(state, update)


def repair_goal_node(state: SkillFoundryV2State) -> SkillFoundryV2State:
    next_attempt = int(state.get("attempt_count", 0)) + 1
    refs = _merge_refs(
        state,
        repair_instructions=f"attempts/{next_attempt:03d}/repair_instructions.md",
        repair_basis=str(state.get("refs", {}).get("verification_result", "verifier/verification_result.json")),
    )
    update: SkillFoundryV2State = {
        "stage": V2Stage.REPAIR_GOAL_NODE.value,
        "status": V2Status.REPAIR_PLANNED.value,
        "refs": refs,
        "human_review_required": False,
        "next_route": V2Route.CONTINUE.value,
    }
    return _validated_update(state, update)


def human_review_node(state: SkillFoundryV2State) -> SkillFoundryV2State:
    refs = _merge_refs(state, human_review_request="human_review/request.json")
    update: SkillFoundryV2State = {
        "stage": V2Stage.HUMAN_REVIEW.value,
        "status": V2Status.HUMAN_REVIEW_REQUIRED.value,
        "refs": refs,
        "human_review_required": True,
        "next_route": V2Route.CONTINUE.value,
    }
    return _validated_update(state, update)


def redesign_node(state: SkillFoundryV2State) -> SkillFoundryV2State:
    refs = _merge_refs(state, redesign_report="contextforge/redesign_required.json")
    update: SkillFoundryV2State = {
        "stage": V2Stage.REDESIGN.value,
        "status": V2Status.REDESIGN_REQUIRED.value,
        "refs": refs,
        "human_review_required": True,
        "next_route": V2Route.CONTINUE.value,
    }
    return _validated_update(state, update)


def reject_node(state: SkillFoundryV2State) -> SkillFoundryV2State:
    refs = _merge_refs(state, rejection_report="contextforge/rejected.json")
    update: SkillFoundryV2State = {
        "stage": V2Stage.REJECT.value,
        "status": V2Status.REJECTED.value,
        "refs": refs,
        "human_review_required": False,
        "next_route": V2Route.CONTINUE.value,
    }
    return _validated_update(state, update)


def emit_report_node(state: SkillFoundryV2State) -> SkillFoundryV2State:
    refs = _merge_refs(state, final_report="contextforge/final_report.json")
    update: SkillFoundryV2State = {
        "stage": V2Stage.EMIT_REPORT.value,
        "status": V2Status.REPORT_EMITTED.value,
        "refs": refs,
        "human_review_required": False,
        "next_route": V2Route.CONTINUE.value,
    }
    return _validated_update(state, update)


def _validated_update(
    state: Mapping[str, Any],
    update: SkillFoundryV2State,
) -> SkillFoundryV2State:
    merged = dict(state)
    merged.update(update)
    validate_v2_graph_state(merged)
    return update


def _attempts_exhausted(state: Mapping[str, Any]) -> bool:
    attempt_count = int(state.get("attempt_count", 0))
    attempt_limit = int(state.get("attempt_limit", 1))
    return attempt_count >= attempt_limit


def _job_id(state: Mapping[str, Any]) -> str:
    job_id = state.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise V2StateValidationError("job_id is required")
    return job_id


def _merge_refs(state: Mapping[str, Any], **updates: str) -> dict[str, str]:
    refs = dict(state.get("refs", {}))
    refs.update(updates)
    return refs


def _string_mapping(value: Any, field_name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise V2StateValidationError(f"{field_name} must be a mapping")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise V2StateValidationError(f"{field_name} must contain only string keys and values")
        result[key] = item
    return result


def _required_context_id(state: Mapping[str, Any], key: str, fallback: str) -> str:
    contextforge = state.get("contextforge", {})
    if isinstance(contextforge, Mapping):
        value = _optional_str(contextforge.get(key))
        if value is not None:
            return value
    return fallback


def _validate_contextforge_state(value: Any, max_inline_string_bytes: int) -> None:
    if not isinstance(value, Mapping):
        raise V2StateValidationError("contextforge must be a mapping")
    _reject_raw_keys_and_large_strings(value, "$.contextforge", max_inline_string_bytes)
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise V2StateValidationError("contextforge keys must be non-empty strings")
        if isinstance(item, (str, int, bool)) or item is None:
            continue
        if isinstance(item, list) and all(isinstance(entry, str) and entry for entry in item):
            continue
        raise V2StateValidationError(f"contextforge.{key} must be an ID, status, flag, or string list")


def _validate_string_mapping(
    value: Any,
    field_name: str,
    max_inline_string_bytes: int,
    *,
    require_hash: bool,
) -> None:
    if not isinstance(value, Mapping):
        raise V2StateValidationError(f"{field_name} must be a mapping")
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise V2StateValidationError(f"{field_name} keys must be non-empty strings")
        _check_string_size(key, f"{field_name} key", max_inline_string_bytes)
        if not isinstance(item, str) or not item:
            raise V2StateValidationError(f"{field_name}.{key} must be a non-empty string")
        _check_string_size(item, f"{field_name}.{key}", max_inline_string_bytes)
        if require_hash and not SHA256_REF_RE.fullmatch(item):
            raise V2StateValidationError(f"{field_name}.{key} must be a sha256 digest or sha256: reference")


def _reject_raw_keys_and_large_strings(value: Any, path: str, max_inline_string_bytes: int) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise V2StateValidationError(f"{path} contains a non-string key")
            normalized_key = key.lower().replace("-", "_")
            if normalized_key in _FORBIDDEN_RAW_KEYS:
                raise V2StateValidationError(f"{path}.{key} is forbidden in refs-only v2 graph state")
            _check_string_size(key, f"{path}.{key} key", max_inline_string_bytes)
            _reject_raw_keys_and_large_strings(item, f"{path}.{key}", max_inline_string_bytes)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_raw_keys_and_large_strings(item, f"{path}[{index}]", max_inline_string_bytes)
        return
    if isinstance(value, str):
        _check_string_size(value, path, max_inline_string_bytes)


def _check_string_size(value: str, path: str, max_inline_string_bytes: int) -> None:
    if len(value.encode("utf-8")) > max_inline_string_bytes:
        raise V2StateValidationError(f"{path} exceeds {max_inline_string_bytes} bytes")


def _require_small_non_empty_string(value: Any, field_name: str, max_inline_string_bytes: int) -> None:
    if not isinstance(value, str) or not value:
        raise V2StateValidationError(f"{field_name} must be a non-empty string")
    _check_string_size(value, field_name, max_inline_string_bytes)


def _require_non_negative_int(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise V2StateValidationError(f"{field_name} must be a non-negative integer")


def _require_positive_int(value: Any, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise V2StateValidationError(f"{field_name} must be a positive integer")


def _coerce_stage(value: Any) -> V2Stage:
    try:
        return V2Stage(str(value))
    except ValueError as exc:
        raise V2StateValidationError(f"unsupported v2 stage: {value!r}") from exc


def _coerce_status(value: Any) -> V2Status:
    try:
        return V2Status(str(value))
    except ValueError as exc:
        raise V2StateValidationError(f"unsupported v2 status: {value!r}") from exc


def _coerce_route(value: Any) -> V2Route:
    try:
        return V2Route(str(value))
    except ValueError as exc:
        raise V2StateValidationError(f"unsupported v2 route: {value!r}") from exc


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "MAX_V2_INLINE_STRING_BYTES",
    "SkillFoundryV2State",
    "V2Route",
    "V2Stage",
    "V2StateValidationError",
    "V2Status",
    "build_goal_node",
    "build_offline_goal_harness_node",
    "build_skillfoundry_v2_graph",
    "compile_skillfoundry_v2_graph",
    "emit_report_node",
    "freeze_contracts_node",
    "human_review_node",
    "redesign_node",
    "registry_gate_node",
    "reject_node",
    "repair_goal_node",
    "route_after_verification",
    "route_after_verification_node",
    "validate_v2_graph_state",
    "verify_node",
]
