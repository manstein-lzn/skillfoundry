"""Front Desk v2 Goal Harness runtime slices."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from contextforge import (
    ContextItem,
    ContextKernel,
    ContextLedger,
    ContextSource,
    GoalHarness,
    GoalHarnessRunResult,
    GoalRunRecord,
    PolicyViolation,
    WorkerRunRequest,
    WorkerRunResult,
    enforce_write_scope,
    estimate_tokens,
)

from .frontdesk_schema import CoreNeedBrief, CoreNeedDiscoveryReport
from .frontdesk_v2 import (
    CORE_NEED_DISCOVERY_NODE_ID,
    FRONTDESK_V2_CONTRACT_DIR,
    FRONTDESK_V2_SCHEMA_VERSION,
    write_frontdesk_v2_contract_artifacts,
)
from .frontdesk_workspace import (
    FRONTDESK_BUDGET_REF,
    FRONTDESK_CLARIFICATION_SUMMARY_REF,
    FRONTDESK_CONVERSATION_REF,
    FRONTDESK_RISK_REPORT_REF,
    FrontDeskWorkspace,
    write_frontdesk_artifact,
)
from .schema import JsonValue, ensure_json_compatible, sha256_file, sha256_json, utc_now
from .workspace import JobWorkspace


FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION = "skillfoundry.frontdesk_goal_runtime.v1"
FRONTDESK_GOAL_RUNTIME_LEDGER_REF = f"{FRONTDESK_V2_CONTRACT_DIR}/goal_runtime_ledger.sqlite3"
FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF = f"{FRONTDESK_V2_CONTRACT_DIR}/core_need_runtime_result.json"
FRONTDESK_CORE_NEED_RUNTIME_STATE_REF = f"{FRONTDESK_V2_CONTRACT_DIR}/core_need_runtime_state.json"
FRONTDESK_CORE_NEED_BRIEF_REF = "frontdesk/core_need_brief.json"
FRONTDESK_CORE_NEED_REPORT_REF = "frontdesk/core_need_discovery_report.json"

_GRAPH_ID = "skillfoundry-frontdesk-v2"
_RUN_TASK_ID = CORE_NEED_DISCOVERY_NODE_ID


@dataclass(frozen=True)
class FrontDeskCoreNeedGoalHarnessResult:
    """Artifacts produced by the Core Need Discovery Goal Harness slice."""

    harness_result: GoalHarnessRunResult
    goal_run: GoalRunRecord
    runtime_result: dict[str, JsonValue]
    runtime_state: dict[str, JsonValue]
    ledger_ref: str
    runtime_result_ref: str
    runtime_state_ref: str


@dataclass(frozen=True)
class FrontDeskCoreNeedFakeWorker:
    """Deterministic worker used to prove the Front Desk Goal Harness boundary."""

    frontdesk: FrontDeskWorkspace
    name: str = "frontdesk-core-need-deterministic-worker"

    kind: str = "fake_model"

    def run(self, request: WorkerRunRequest) -> WorkerRunResult:
        changed_files = [FRONTDESK_CORE_NEED_BRIEF_REF, FRONTDESK_CORE_NEED_REPORT_REF]
        try:
            enforce_write_scope(changed_files, request.node_contract.write_scope)
        except PolicyViolation as exc:
            return _frontdesk_worker_result(
                request,
                worker_name=self.name,
                status="failed",
                final_output_ref=None,
                summary="Front Desk Core Need worker failed closed on write scope policy.",
                failure_class="write_scope_violation",
                artifact_refs=[],
                changed_files=[],
                attempted_changed_files=changed_files,
                metadata={"policy_error": str(exc)},
            )

        brief = CoreNeedBrief(
            problem_statement="The user needs a governed Codex Skill requirement before build execution.",
            target_user="SkillFoundry requester",
            usage_moment="Before routing a clarified requirement into the build pipeline.",
            desired_outcome="A concise core-need brief that downstream planning can consume by ref.",
            success_signal="Front Desk core need is marked ready without exposing raw conversation.",
            current_workaround="Manual interpretation of conversation history.",
            assumptions=["Derived from governed Front Desk summary artifacts, not raw conversation."],
            risk_flags=[],
            confidence_score=0.75,
            source_turn_ids=[],
        )
        report = CoreNeedDiscoveryReport(
            readiness="core_need_ready",
            current_understanding=brief.problem_statement,
            core_need_brief=brief,
            decision_ledger_ref=FRONTDESK_CORE_NEED_REPORT_REF,
            summary_ref=FRONTDESK_CLARIFICATION_SUMMARY_REF,
            round_index=1,
        )
        write_frontdesk_artifact(self.frontdesk, FRONTDESK_CORE_NEED_BRIEF_REF, brief)
        write_frontdesk_artifact(self.frontdesk, FRONTDESK_CORE_NEED_REPORT_REF, report)
        return _frontdesk_worker_result(
            request,
            worker_name=self.name,
            status="completed",
            final_output_ref=FRONTDESK_CORE_NEED_REPORT_REF,
            summary="Front Desk Core Need worker wrote governed core-need artifacts.",
            failure_class=None,
            artifact_refs=changed_files,
            changed_files=changed_files,
            attempted_changed_files=changed_files,
            metadata={"frontdesk_core_need_fake_worker": True},
        )


def run_frontdesk_core_need_goal_harness(
    workspace: FrontDeskWorkspace | JobWorkspace,
    *,
    run_id: str | None = None,
    created_at: str | None = None,
) -> FrontDeskCoreNeedGoalHarnessResult:
    """Run Front Desk Core Need Discovery as a ContextForge Goal Harness node."""

    frontdesk = _coerce_frontdesk(workspace)
    frontdesk.workspace.check_locked_inputs()
    timestamp = created_at or utc_now()
    resolved_run_id = run_id or f"{frontdesk.job_id}-frontdesk-core-need-run"
    artifacts = write_frontdesk_v2_contract_artifacts(frontdesk, created_at=timestamp)
    goal_contract = _load_json_contract(frontdesk, artifacts.goal_contract_ref)
    node_contract = _load_json_contract(frontdesk, artifacts.node_contract_refs[CORE_NEED_DISCOVERY_NODE_ID])
    ledger = ContextLedger.connect(frontdesk.workspace.resolve_path(FRONTDESK_GOAL_RUNTIME_LEDGER_REF))
    ledger.initialize()
    try:
        _seed_frontdesk_context(frontdesk, ledger, run_id=resolved_run_id, created_at=timestamp)
        harness_result = GoalHarness(ContextKernel(ledger)).run_single_node(
            goal_contract,
            node_contract,
            FrontDeskCoreNeedFakeWorker(frontdesk),
            graph_id=_GRAPH_ID,
            run_id=resolved_run_id,
            task_id=_RUN_TASK_ID,
            created_at=timestamp,
            metadata={
                "skillfoundry_job_id": frontdesk.job_id,
                "frontdesk_v2": FRONTDESK_V2_SCHEMA_VERSION,
                "frontdesk_goal_runtime": FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION,
            },
            checkpoint_reason="phase_complete",
            checkpoint_best_result="Core Need Discovery completed through Front Desk Goal Harness boundary.",
            checkpoint_latest_diagnosis="Governed context was compiled and raw conversation remained forbidden.",
            checkpoint_next_plan="Route governed core-need brief to solution planning.",
        )
        goal_run = harness_result.goal_run
        runtime_state = _runtime_state(frontdesk, harness_result, goal_run)
        runtime_result = _runtime_result(frontdesk, harness_result, goal_run, runtime_state, created_at=timestamp)
        _write_json(frontdesk.workspace, FRONTDESK_CORE_NEED_RUNTIME_STATE_REF, runtime_state)
        _write_json(frontdesk.workspace, FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF, runtime_result)
        return FrontDeskCoreNeedGoalHarnessResult(
            harness_result=harness_result,
            goal_run=goal_run,
            runtime_result=runtime_result,
            runtime_state=runtime_state,
            ledger_ref=FRONTDESK_GOAL_RUNTIME_LEDGER_REF,
            runtime_result_ref=FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF,
            runtime_state_ref=FRONTDESK_CORE_NEED_RUNTIME_STATE_REF,
        )
    finally:
        ledger.close()


def _seed_frontdesk_context(
    frontdesk: FrontDeskWorkspace,
    ledger: ContextLedger,
    *,
    run_id: str,
    created_at: str,
) -> list[str]:
    refs = [
        (FRONTDESK_CLARIFICATION_SUMMARY_REF, "artifact", "frontdesk_clarification_summary", ["governed_frontdesk"]),
        (FRONTDESK_RISK_REPORT_REF, "constraint", "frontdesk_risk_report", ["governed_frontdesk"]),
        (FRONTDESK_BUDGET_REF, "constraint", "frontdesk_budget", ["governed_frontdesk"]),
        (
            FRONTDESK_CONVERSATION_REF,
            "user_message",
            "raw_frontdesk_conversation",
            ["raw_frontdesk_conversation"],
        ),
    ]
    recorded: list[str] = []
    for ref, item_type, context_type, tags in refs:
        try:
            content = frontdesk.workspace.resolve_path(ref, must_exist=True).read_text(encoding="utf-8")
        except Exception:
            if ref == FRONTDESK_CONVERSATION_REF:
                content = ""
            else:
                continue
        item_id = f"{frontdesk.job_id}:{context_type}"
        ledger.record_context_item(
            ContextItem(
                id=item_id,
                graph_id=_GRAPH_ID,
                run_id=run_id,
                task_id=_RUN_TASK_ID,
                node_id=CORE_NEED_DISCOVERY_NODE_ID,
                type=item_type,  # type: ignore[arg-type]
                content=content,
                source=ContextSource(
                    kind="artifact",
                    ref=ref,
                    name=context_type,
                    sha256=_sha256_or_none(frontdesk.workspace, ref),
                    metadata={"workspace_job_id": frontdesk.job_id},
                ),
                importance=1.0,
                token_estimate=estimate_tokens(content),
                created_at=created_at,
                artifact_ref=ref,
                provenance={"job_id": frontdesk.job_id, "artifact_ref": ref},
                metadata={
                    "frontdesk_context_type": context_type,
                    "prompt_category": "provenance" if ref == FRONTDESK_CONVERSATION_REF else "project_fact",
                    "prompt_include": ref != FRONTDESK_CONVERSATION_REF,
                    "tags": tags,
                    "raw_conversation_included": False,
                },
            )
        )
        recorded.append(item_id)
    return recorded


def _frontdesk_worker_result(
    request: WorkerRunRequest,
    *,
    worker_name: str,
    status: str,
    final_output_ref: str | None,
    summary: str,
    failure_class: str | None,
    artifact_refs: list[str],
    changed_files: list[str],
    attempted_changed_files: list[str],
    metadata: dict[str, JsonValue],
) -> WorkerRunResult:
    return WorkerRunResult(
        status=status,
        worker_name=worker_name,
        final_output_ref=final_output_ref,
        summary=summary,
        failure_class=failure_class,
        prompt_view_ids=[request.prompt_view.id],
        artifact_ids=[_artifact_id(request.metadata.get("skillfoundry_job_id"), ref) for ref in artifact_refs],
        usage_summary={
            "provider": "offline",
            "model": "frontdesk_core_need_deterministic_fixture",
            "expected_cacheable_tokens": request.cache_plan.expected_cacheable_tokens,
            "cache_telemetry_status": request.cache_plan.cache_telemetry_status,
            "usage_available": False,
            "usage_unavailable_reason": "Front Desk deterministic Goal Harness fixture does not call a provider.",
        },
        metadata={
            "frontdesk_goal_runtime": FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION,
            "changed_files": changed_files,
            "attempted_changed_files": attempted_changed_files,
            "artifact_refs": artifact_refs,
            "worker_self_report_is_not_acceptance": True,
            "raw_conversation_included": False,
            **metadata,
        },
    )


def _runtime_state(
    frontdesk: FrontDeskWorkspace,
    harness_result: GoalHarnessRunResult,
    goal_run: GoalRunRecord,
) -> dict[str, JsonValue]:
    payload = {
        "schema_version": FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION,
        "job_id": frontdesk.job_id,
        "stage": CORE_NEED_DISCOVERY_NODE_ID,
        "status": goal_run.status,
        "refs": {
            "ledger": FRONTDESK_GOAL_RUNTIME_LEDGER_REF,
            "runtime_result": FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF,
            "core_need_brief": FRONTDESK_CORE_NEED_BRIEF_REF,
            "core_need_report": FRONTDESK_CORE_NEED_REPORT_REF,
        },
        "contextforge": {
            "goal_run_id": goal_run.goal_run_id,
            "worker_run_id": harness_result.worker_run.worker_run_id,
            "context_view_id": harness_result.compiled_context.context_view.context_view_id,
            "prompt_view_id": harness_result.compiled_context.prompt_view.id,
            "cache_plan_id": harness_result.compiled_context.cache_plan.cache_plan_id,
            "checkpoint_ids": list(goal_run.checkpoint_ids),
        },
        "raw_conversation_included": False,
    }
    return ensure_json_compatible(payload)  # type: ignore[return-value]


def _runtime_result(
    frontdesk: FrontDeskWorkspace,
    harness_result: GoalHarnessRunResult,
    goal_run: GoalRunRecord,
    runtime_state: dict[str, JsonValue],
    *,
    created_at: str,
) -> dict[str, JsonValue]:
    payload = {
        "schema_version": FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION,
        "job_id": frontdesk.job_id,
        "created_at": created_at,
        "refs": {
            "ledger": FRONTDESK_GOAL_RUNTIME_LEDGER_REF,
            "runtime_state": FRONTDESK_CORE_NEED_RUNTIME_STATE_REF,
            "core_need_brief": FRONTDESK_CORE_NEED_BRIEF_REF,
            "core_need_report": FRONTDESK_CORE_NEED_REPORT_REF,
        },
        "ids": {
            "goal_run_id": goal_run.goal_run_id,
            "worker_run_id": harness_result.worker_run.worker_run_id,
            "context_view_id": harness_result.compiled_context.context_view.context_view_id,
            "prompt_view_id": harness_result.compiled_context.prompt_view.id,
            "cache_plan_id": harness_result.compiled_context.cache_plan.cache_plan_id,
        },
        "status": {
            "worker": harness_result.worker_run.status,
            "goal_run": goal_run.status,
            "decision": goal_run.decision,
        },
        "usage": harness_result.worker_run.usage_summary,
        "hashes": {
            "runtime_state": sha256_json(runtime_state),
            "core_need_brief": sha256_file(frontdesk.workspace.resolve_path(FRONTDESK_CORE_NEED_BRIEF_REF)),
            "core_need_report": sha256_file(frontdesk.workspace.resolve_path(FRONTDESK_CORE_NEED_REPORT_REF)),
        },
        "trust_boundaries": {
            "worker_self_report_is_not_acceptance": True,
            "raw_conversation_included": False,
        },
    }
    return ensure_json_compatible(payload)  # type: ignore[return-value]


def _load_json_contract(frontdesk: FrontDeskWorkspace, ref: str) -> Any:
    path = frontdesk.workspace.resolve_path(ref, must_exist=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if ref.endswith("goal_contract.json"):
        from contextforge import GoalContract

        return GoalContract.from_dict(payload)
    from contextforge import AgentNodeContract

    return AgentNodeContract.from_dict(payload)


def _sha256_or_none(workspace: JobWorkspace, artifact_ref: str) -> str | None:
    try:
        path = workspace.resolve_path(artifact_ref, must_exist=True)
    except Exception:
        return None
    if path.is_file():
        return "sha256:" + sha256_file(path)
    return None


def _write_json(workspace: JobWorkspace, ref: str, payload: dict[str, JsonValue]) -> None:
    path = workspace.resolve_path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def _artifact_id(job_id: object, ref: str) -> str:
    prefix = str(job_id) if isinstance(job_id, str) and job_id else "skillfoundry-job"
    return f"{prefix}:{ref}"


def _coerce_frontdesk(workspace: FrontDeskWorkspace | JobWorkspace) -> FrontDeskWorkspace:
    if isinstance(workspace, FrontDeskWorkspace):
        return workspace
    return FrontDeskWorkspace(workspace=workspace)


__all__ = [
    "FRONTDESK_CORE_NEED_BRIEF_REF",
    "FRONTDESK_CORE_NEED_REPORT_REF",
    "FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF",
    "FRONTDESK_CORE_NEED_RUNTIME_STATE_REF",
    "FRONTDESK_GOAL_RUNTIME_LEDGER_REF",
    "FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION",
    "FrontDeskCoreNeedFakeWorker",
    "FrontDeskCoreNeedGoalHarnessResult",
    "run_frontdesk_core_need_goal_harness",
]
