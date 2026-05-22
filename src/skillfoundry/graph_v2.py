"""SkillFoundry v2 LangGraph spine around ContextForge Goal Harness refs."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
import json
from pathlib import Path
import re
from typing import Any, Mapping, TypedDict

from contextforge import VerificationResult as ContextForgeVerificationResult
from langgraph.graph import END, START, StateGraph

from .goal_runtime import (
    GoalHarnessWorkerFactory,
    OfflineVerificationMode,
    VERIFIED_GOAL_RUNTIME_RESULT_REF,
    run_repair_goal_harness,
    run_offline_goal_harness,
    run_verified_offline_goal_harness,
)
from .registry import DEFAULT_REGISTRY_VERSION, LocalSkillRegistry
from .schema import JsonValue, SchemaValidationError, ensure_json_compatible, sha256_file, sha256_json, utc_now
from .workspace import JOB_ID_RE, JobWorkspace


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
    REPAIR_RECORDED = "repair_recorded"
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
GRAPH_V2_STATE_REF = "contextforge/graph_v2_state.json"
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
    repair_node_callable: V2Node | None = None,
    registry_gate_callable: V2Node | None = None,
) -> StateGraph:
    """Build the v2 refs-only LangGraph spine."""

    graph = StateGraph(SkillFoundryV2State)
    graph.add_node(V2Stage.FREEZE_CONTRACTS.value, freeze_contracts_node)
    graph.add_node(V2Stage.BUILD_GOAL_NODE.value, build_node_callable or build_goal_node)
    graph.add_node(V2Stage.VERIFY.value, verify_node)
    graph.add_node(V2Stage.ROUTE_AFTER_VERIFICATION.value, route_after_verification_node)
    graph.add_node(V2Stage.REPAIR_GOAL_NODE.value, repair_node_callable or repair_goal_node)
    graph.add_node(V2Stage.REGISTRY_GATE.value, registry_gate_callable or registry_gate_node)
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
    repair_node_callable: V2Node | None = None,
    registry_gate_callable: V2Node | None = None,
    checkpointer: Any | None = None,
    interrupt_before: list[str] | str | None = None,
    interrupt_after: list[str] | str | None = None,
    debug: bool = False,
) -> Any:
    """Compile the v2 graph while preserving LangGraph checkpoint options."""

    return build_skillfoundry_v2_graph(
        build_node_callable=build_node_callable,
        repair_node_callable=repair_node_callable,
        registry_gate_callable=registry_gate_callable,
    ).compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
        interrupt_after=interrupt_after,
        debug=debug,
    )


def run_verified_skillfoundry_v2_graph(
    runs_root: str | Path,
    job_id: str,
    *,
    registry_path: str | Path,
    attempt_limit: int = 2,
    version: str = DEFAULT_REGISTRY_VERSION,
    created_at: str | None = None,
    worker_factory: GoalHarnessWorkerFactory | None = None,
) -> SkillFoundryV2State:
    """Run the canonical offline v2 graph and persist its refs-only final state."""

    runs_path = Path(runs_root)
    safe_job_id = _job_id({"job_id": job_id})
    workspace = _graph_workspace(runs_path, safe_job_id)
    graph = compile_skillfoundry_v2_graph(
        build_node_callable=build_verified_goal_harness_node(
            runs_path,
            registry_path=registry_path,
            version=version,
            created_at=created_at,
            worker_factory=worker_factory,
        ),
        repair_node_callable=build_repair_goal_harness_node(
            runs_path,
            created_at=created_at,
            worker_factory=worker_factory,
        ),
        registry_gate_callable=build_verified_registry_gate_node(
            runs_path,
            registry_path=registry_path,
            created_at=created_at,
        ),
    )
    result = graph.invoke({"job_id": safe_job_id, "attempt_limit": attempt_limit})
    validate_v2_graph_state(result)
    _write_json_ref(workspace, GRAPH_V2_STATE_REF, result)
    return result


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
    worker_factory: GoalHarnessWorkerFactory | None = None,
) -> V2Node:
    """Return a v2 graph node backed by the offline Goal Harness slice."""

    runs_path = Path(runs_root)

    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        validate_v2_graph_state(state)
        job_id = _job_id(state)
        workspace = _graph_workspace(runs_path, job_id)
        result = run_offline_goal_harness(
            workspace,
            verification_mode=verification_mode,
            created_at=created_at,
            worker_factory=worker_factory,
        )
        runtime_state = result.graph_state
        refs = _merge_refs(state, **_string_mapping(runtime_state.get("refs", {}), "runtime refs"))
        hashes = dict(state.get("hashes", {}))
        hashes.update(_string_mapping(runtime_state.get("hashes", {}), "runtime hashes"))
        contextforge = dict(state.get("contextforge", {}))
        contextforge.update(_contextforge_mapping(runtime_state.get("contextforge", {}), "runtime contextforge"))
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


def build_verified_goal_harness_node(
    runs_root: str | Path,
    *,
    registry_path: str | Path,
    version: str = DEFAULT_REGISTRY_VERSION,
    created_at: str | None = None,
    worker_factory: GoalHarnessWorkerFactory | None = None,
) -> V2Node:
    """Return a v2 graph build node backed by the verified Goal Harness runtime."""

    runs_path = Path(runs_root)
    registry_file = Path(registry_path)

    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        validate_v2_graph_state(state)
        job_id = _job_id(state)
        workspace = _graph_workspace(runs_path, job_id)
        result = run_verified_offline_goal_harness(
            workspace,
            registry_path=registry_file,
            version=version,
            created_at=created_at,
            worker_factory=worker_factory,
        )
        runtime_state = result.goal_harness.graph_state
        verified_runtime = result.verified_runtime_result
        refs = _merge_refs(state, **_string_mapping(runtime_state.get("refs", {}), "runtime refs"))
        refs.update(_safe_verified_runtime_refs(verified_runtime.get("refs", {})))
        hashes = dict(state.get("hashes", {}))
        hashes.update(_string_mapping(runtime_state.get("hashes", {}), "runtime hashes"))
        hashes.update(_string_mapping(verified_runtime.get("hashes", {}), "verified runtime hashes"))
        hashes["verified_runtime_result"] = sha256_file(
            workspace.resolve_path(VERIFIED_GOAL_RUNTIME_RESULT_REF, must_exist=True)
        )
        hashes["final_report"] = sha256_file(workspace.resolve_path("final_report.json", must_exist=True))
        contextforge = dict(state.get("contextforge", {}))
        contextforge.update(_contextforge_mapping(runtime_state.get("contextforge", {}), "runtime contextforge"))
        contextforge.update(
            {
                "last_goal_status": result.goal_harness.goal_run.status,
                "last_goal_decision": result.goal_harness.goal_run.decision or "",
                "registry_approved": result.registry_entry.approval_status == "approved",
                "registry_skill_id": result.registry_entry.skill_id,
                "registry_version": result.registry_entry.version,
                "verified_runtime_result_ref": VERIFIED_GOAL_RUNTIME_RESULT_REF,
            }
        )
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


def build_repair_goal_harness_node(
    runs_root: str | Path,
    *,
    created_at: str | None = None,
    worker_factory: GoalHarnessWorkerFactory | None = None,
) -> V2Node:
    """Return a repair node backed by a ContextForge Goal Harness worker boundary."""

    runs_path = Path(runs_root)

    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        validate_v2_graph_state(state)
        if route_after_verification(state) != V2Route.REPAIR_GOAL_NODE.value:
            raise V2StateValidationError("repair Goal Harness node requires a failed verification repair route")
        job_id = _job_id(state)
        workspace = _graph_workspace(runs_path, job_id)
        next_attempt = int(state.get("attempt_count", 0)) + 1
        attempt_id = f"{next_attempt:03d}"
        contextforge = dict(state.get("contextforge", {}))
        result = run_repair_goal_harness(
            workspace,
            attempt_id=attempt_id,
            based_on_result_id=_optional_str(contextforge.get("last_verification_result_id")),
            repair_basis_ref=_state_ref(state, "verification_result", "verifier/verification_result.json"),
            created_at=created_at,
            worker_factory=worker_factory,
        )
        runtime_state = result.graph_state
        refs = _merge_refs(state, **_string_mapping(runtime_state.get("refs", {}), "repair runtime refs"))
        refs["repair_instructions"] = result.repair_attempt.repair_instructions_ref
        refs["repair_attempt"] = result.repair_attempt_ref
        refs["repair_runtime_result"] = result.runtime_result_ref
        hashes = dict(state.get("hashes", {}))
        hashes.update(_string_mapping(runtime_state.get("hashes", {}), "repair runtime hashes"))
        hashes["repair_runtime_result"] = sha256_file(
            workspace.resolve_path(result.runtime_result_ref, must_exist=True)
        )
        contextforge.update(_contextforge_mapping(runtime_state.get("contextforge", {}), "repair contextforge"))
        contextforge["repair_runtime_result_ref"] = result.runtime_result_ref
        update: SkillFoundryV2State = {
            "schema_version": _STATE_SCHEMA_VERSION,
            "job_id": job_id,
            "stage": V2Stage.REPAIR_GOAL_NODE.value,
            "status": V2Status.REPAIR_RECORDED.value,
            "attempt_count": next_attempt,
            "attempt_limit": int(state.get("attempt_limit", 1)),
            "refs": refs,
            "hashes": hashes,
            "contextforge": contextforge,
            "human_review_required": False,
            "next_route": V2Route.CONTINUE.value,
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


def build_verified_registry_gate_node(
    runs_root: str | Path,
    *,
    registry_path: str | Path,
    created_at: str | None = None,
) -> V2Node:
    """Return a registry gate that validates verified runtime and registry evidence."""

    runs_path = Path(runs_root)
    registry_file = Path(registry_path)

    def _node(state: SkillFoundryV2State) -> SkillFoundryV2State:
        validate_v2_graph_state(state)
        job_id = _job_id(state)
        workspace = _graph_workspace(runs_path, job_id)
        verified_ref = _state_ref(state, "verified_runtime_result", VERIFIED_GOAL_RUNTIME_RESULT_REF)
        verified_runtime = _read_json_ref(workspace, verified_ref, "verified runtime result")
        final_report_ref = _json_ref(verified_runtime, ("refs", "final_report"), "final_report.json")
        final_report = _read_json_ref(workspace, final_report_ref, "final report")
        _require_verified_runtime_registered(verified_runtime, final_report, job_id=job_id)
        skill_id = _json_str_at(verified_runtime, ("ids", "registry_skill_id"), "registry skill id")
        version = _json_str_at(verified_runtime, ("ids", "registry_version"), "registry version")
        registry = LocalSkillRegistry(registry_file)
        entry = registry.get(skill_id, version)
        _require_registry_entry_for_workspace(entry, workspace)
        contextforge_result = _read_current_contextforge_verification(workspace, verified_runtime)
        _require_contextforge_result_for_workspace(contextforge_result, workspace, verified_runtime, entry.package_hash)
        verification_report = registry.verify_entry(entry)
        if not verification_report.valid:
            raise V2StateValidationError(
                "verified registry gate failed: " + "; ".join(verification_report.failures)
            )
        entry_hash = sha256_json(entry.to_dict())
        report_entry_hash = _optional_nested_str(final_report, ("refs", "registry_entry", "entry_hash"))
        if report_entry_hash != entry_hash:
            raise V2StateValidationError(
                f"final_report registry entry hash mismatch: expected {entry_hash}, got {report_entry_hash!r}"
            )
        registry_dir = workspace.resolve_path("registry")
        registry_dir.mkdir(parents=True, exist_ok=True)
        entry_ref = "registry/entry.json"
        decision_ref = "registry/decision.json"
        timestamp = created_at or utc_now()
        entry_payload = {
            "schema_version": "skillfoundry.graph_v2.registry_entry_snapshot.v1",
            "job_id": job_id,
            "registry_path": registry_file.as_posix(),
            "entry_hash": entry_hash,
            "entry": entry.to_dict(),
            "verification_report": verification_report.to_dict(),
            "created_at": timestamp,
        }
        decision_payload = {
            "schema_version": "skillfoundry.graph_v2.registry_decision.v1",
            "job_id": job_id,
            "passed": True,
            "decision": "registered",
            "registry_path": registry_file.as_posix(),
            "skill_id": entry.skill_id,
            "version": entry.version,
            "entry_ref": entry_ref,
            "entry_hash": entry_hash,
            "verified_runtime_result_ref": verified_ref,
            "contextforge_verification_result_ref": _json_ref(
                verified_runtime,
                ("refs", "contextforge_verification_result"),
                "contextforge/verification_result.json",
            ),
            "created_at": timestamp,
        }
        _write_json_ref(workspace, entry_ref, entry_payload)
        _write_json_ref(workspace, decision_ref, decision_payload)
        refs = _merge_refs(state, registry_decision=decision_ref, registry_entry=entry_ref)
        hashes = dict(state.get("hashes", {}))
        hashes["registry_decision"] = sha256_file(workspace.resolve_path(decision_ref, must_exist=True))
        hashes["registry_entry"] = sha256_file(workspace.resolve_path(entry_ref, must_exist=True))
        contextforge = dict(state.get("contextforge", {}))
        contextforge.update(
            {
                "registry_approved": True,
                "registry_skill_id": entry.skill_id,
                "registry_version": entry.version,
                "registry_verification_report_valid": True,
            }
        )
        update: SkillFoundryV2State = {
            "stage": V2Stage.REGISTRY_GATE.value,
            "status": V2Status.REGISTERED.value,
            "refs": refs,
            "hashes": hashes,
            "contextforge": contextforge,
            "human_review_required": False,
            "next_route": V2Route.CONTINUE.value,
        }
        return _validated_update(state, update)

    return _node


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
    refs = dict(state.get("refs", {}))
    refs.setdefault("final_report", "contextforge/final_report.json")
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
    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        raise V2StateValidationError("job_id must be a safe workspace path segment")
    return job_id


def _graph_workspace(runs_path: Path, job_id: str) -> JobWorkspace:
    try:
        resolved_runs = runs_path.resolve(strict=True)
        root = (resolved_runs / job_id).resolve(strict=True)
        root.relative_to(resolved_runs)
    except Exception as exc:
        raise V2StateValidationError(f"job workspace must be under runs_root: {job_id}") from exc
    return JobWorkspace(root=root, job_id=job_id)


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


def _safe_verified_runtime_refs(value: Any) -> dict[str, str]:
    refs = _string_mapping(value, "verified runtime refs")
    forbidden_ref_keys = {
        "worker_transcript",
        "worker_diff",
    }
    return {key: item for key, item in refs.items() if key not in forbidden_ref_keys}


def _contextforge_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise V2StateValidationError(f"{field_name} must be a mapping")
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise V2StateValidationError(f"{field_name} keys must be non-empty strings")
        if isinstance(item, (str, int, bool)) or item is None:
            result[key] = item
            continue
        if isinstance(item, list) and all(isinstance(entry, str) and entry for entry in item):
            result[key] = list(item)
            continue
        raise V2StateValidationError(f"{field_name}.{key} must be an ID, status, flag, or string list")
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


def _state_ref(state: Mapping[str, Any], key: str, fallback: str) -> str:
    refs = state.get("refs", {})
    if isinstance(refs, Mapping):
        value = _optional_str(refs.get(key))
        if value:
            return value
    return fallback


def _read_json_ref(workspace: JobWorkspace, ref: str, label: str) -> dict[str, JsonValue]:
    try:
        path = workspace.resolve_path(ref, must_exist=True)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise V2StateValidationError(f"{label} is missing or invalid at {ref}: {exc}") from exc
    if not isinstance(payload, dict):
        raise V2StateValidationError(f"{label} at {ref} must be a JSON object")
    compatible = ensure_json_compatible(payload)
    if not isinstance(compatible, dict):
        raise V2StateValidationError(f"{label} at {ref} must be a JSON object")
    return compatible  # type: ignore[return-value]


def _write_json_ref(workspace: JobWorkspace, ref: str, payload: Mapping[str, Any]) -> None:
    compatible = ensure_json_compatible(dict(payload))
    if not isinstance(compatible, dict):
        raise V2StateValidationError(f"{ref} payload must be a JSON object")
    path = workspace.resolve_path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(compatible, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def _require_verified_runtime_registered(
    verified_runtime: Mapping[str, Any],
    final_report: Mapping[str, Any],
    *,
    job_id: str,
) -> None:
    if verified_runtime.get("job_id") != job_id:
        raise V2StateValidationError(
            f"verified runtime job_id mismatch: expected {job_id}, got {verified_runtime.get('job_id')!r}"
        )
    if final_report.get("job_id") != job_id:
        raise V2StateValidationError(
            f"final_report job_id mismatch: expected {job_id}, got {final_report.get('job_id')!r}"
        )
    if _optional_nested_str(verified_runtime, ("status", "contextforge_verification")) != "passed":
        raise V2StateValidationError("verified runtime did not record passed ContextForge verification")
    if _optional_nested_str(verified_runtime, ("status", "final_status")) != "registered":
        raise V2StateValidationError("verified runtime did not record registered final status")
    if _optional_nested_bool(verified_runtime, ("status", "registry_approved")) is not True:
        raise V2StateValidationError("verified runtime did not record registry approval")
    if final_report.get("final_status") != "registered":
        raise V2StateValidationError("final_report did not record registered final status")


def _require_registry_entry_for_workspace(entry: Any, workspace: JobWorkspace) -> None:
    if entry.build_job_id != workspace.job_id:
        raise V2StateValidationError(
            f"registry entry build_job_id mismatch: expected {workspace.job_id}, got {entry.build_job_id!r}"
        )
    provenance_root = _optional_nested_str(entry.provenance, ("workspace_root",))
    current_root = workspace.root.resolve(strict=True).as_posix()
    if provenance_root != current_root:
        raise V2StateValidationError(
            f"registry entry workspace_root mismatch: expected {current_root}, got {provenance_root!r}"
        )


def _read_current_contextforge_verification(
    workspace: JobWorkspace,
    verified_runtime: Mapping[str, Any],
) -> ContextForgeVerificationResult:
    ref = _json_ref(verified_runtime, ("refs", "contextforge_verification_result"), "contextforge/verification_result.json")
    try:
        path = workspace.resolve_path(ref, must_exist=True)
        result = ContextForgeVerificationResult.from_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise V2StateValidationError(f"ContextForge verification result is missing or invalid at {ref}: {exc}") from exc
    recorded_hash = _optional_nested_str(verified_runtime, ("hashes", "contextforge_verification_result"))
    actual_hash = sha256_file(path)
    if recorded_hash != actual_hash:
        raise V2StateValidationError(
            f"ContextForge verification hash mismatch: expected {recorded_hash!r}, got {actual_hash}"
        )
    return result


def _require_contextforge_result_for_workspace(
    result: ContextForgeVerificationResult,
    workspace: JobWorkspace,
    verified_runtime: Mapping[str, Any],
    package_hash: str,
) -> None:
    if result.status != "passed" or not result.passed:
        raise V2StateValidationError(f"ContextForge verification result did not pass: {result.status}")
    if result.metadata.get("job_id") != workspace.job_id:
        raise V2StateValidationError(
            f"ContextForge verification job_id mismatch: expected {workspace.job_id}, "
            f"got {result.metadata.get('job_id')!r}"
        )
    if result.metadata.get("current_package_hash") != package_hash:
        raise V2StateValidationError(
            "ContextForge verification package hash mismatch: "
            f"expected {package_hash}, got {result.metadata.get('current_package_hash')!r}"
        )
    _require_metadata_hash_matches_workspace(
        workspace,
        result,
        "skillfoundry_verification_result_hash",
        "verifier/verification_result.json",
    )
    _require_metadata_hash_matches_workspace(
        workspace,
        result,
        "acceptance_coverage_result_hash",
        "qa/acceptance_coverage_result.json",
    )
    recorded_id = _optional_nested_str(verified_runtime, ("ids", "contextforge_verification_result_id"))
    if recorded_id != result.verification_result_id:
        raise V2StateValidationError(
            f"verified runtime ContextForge verification id mismatch: expected {recorded_id!r}, "
            f"got {result.verification_result_id}"
        )


def _require_metadata_hash_matches_workspace(
    workspace: JobWorkspace,
    result: ContextForgeVerificationResult,
    metadata_key: str,
    ref: str,
) -> None:
    expected = result.metadata.get(metadata_key)
    actual = sha256_file(workspace.resolve_path(ref, must_exist=True))
    if expected != actual:
        raise V2StateValidationError(f"ContextForge metadata {metadata_key} mismatch: expected {expected!r}, got {actual}")


def _json_ref(payload: Mapping[str, Any], path: tuple[str, ...], fallback: str) -> str:
    return _optional_nested_str(payload, path) or fallback


def _json_str_at(payload: Mapping[str, Any], path: tuple[str, ...], label: str) -> str:
    value = _optional_nested_str(payload, path)
    if value is None:
        raise V2StateValidationError(f"{label} is missing")
    return value


def _optional_nested_str(payload: Mapping[str, Any], path: tuple[str, ...]) -> str | None:
    value: Any = payload
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return _optional_str(value)


def _optional_nested_bool(payload: Mapping[str, Any], path: tuple[str, ...]) -> bool | None:
    value: Any = payload
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value if isinstance(value, bool) else None


__all__ = [
    "MAX_V2_INLINE_STRING_BYTES",
    "GRAPH_V2_STATE_REF",
    "SkillFoundryV2State",
    "V2Route",
    "V2Stage",
    "V2StateValidationError",
    "V2Status",
    "build_goal_node",
    "build_offline_goal_harness_node",
    "build_repair_goal_harness_node",
    "build_skillfoundry_v2_graph",
    "build_verified_goal_harness_node",
    "build_verified_registry_gate_node",
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
    "run_verified_skillfoundry_v2_graph",
    "validate_v2_graph_state",
    "verify_node",
]
