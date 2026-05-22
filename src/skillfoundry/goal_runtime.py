"""Offline Goal Harness vertical slice for SkillFoundry v2."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Literal

from contextforge import (
    CheckpointManager,
    ContextItem,
    ContextKernel,
    ContextLedger,
    ContextSource,
    GoalHarness,
    GoalHarnessRunResult,
    GoalRunRecord,
    VerificationResult as ContextForgeVerificationResult,
    VerificationRunner,
    estimate_tokens,
)

from .acceptance import AcceptanceCoverageEvaluator, AcceptanceCriteriaPlanner, AcceptanceCoverageResult
from .contracts import (
    BUILD_NODE_CONTRACT_REF,
    CONTRACT_MANIFEST_REF,
    GOAL_CONTRACT_REF,
    VERIFICATION_GATE_REF,
    ContextForgeContractArtifacts,
    write_contextforge_contract_artifacts,
)
from .registry import DEFAULT_REGISTRY_VERSION, DuplicatePolicy, LocalSkillRegistry
from .schema import (
    ExecutionReport,
    JsonValue,
    RegistryEntry,
    VerificationResult,
    ensure_json_compatible,
    sha256_file,
    sha256_json,
    utc_now,
)
from .verification_bridge import bridge_skillfoundry_verification_result
from .verifier import Verifier
from .workers_v2 import FakeSkillBuilderWorker
from .workspace import JobWorkspace


GOAL_RUNTIME_LEDGER_REF = "contextforge/ledger.sqlite3"
GOAL_RUNTIME_RESULT_REF = "contextforge/goal_runtime_result.json"
GOAL_RUNTIME_STATE_REF = "contextforge/goal_harness_state.json"
VERIFIED_GOAL_RUNTIME_RESULT_REF = "contextforge/verified_goal_runtime_result.json"
GOAL_RUNTIME_RESULT_SCHEMA_VERSION = "skillfoundry.goal_runtime_result.v1"
GOAL_RUNTIME_STATE_SCHEMA_VERSION = "skillfoundry.goal_harness_state.v1"
VERIFIED_GOAL_RUNTIME_RESULT_SCHEMA_VERSION = "skillfoundry.verified_goal_runtime_result.v1"

_GRAPH_ID = "skillfoundry-v2"
_BUILD_NODE_ID = "build_skill"
_TASK_ID = "build_skill"
_RAW_CONVERSATION_REF = "frontdesk/conversation.jsonl"


OfflineVerificationMode = Literal["pass", "fail_missing_coverage"]
GoalRuntimeVerificationMode = Literal["pass", "fail_missing_coverage", "verified"]


@dataclass(frozen=True)
class SkillFoundryGoalHarnessResult:
    """Artifacts produced by one offline SkillFoundry Goal Harness run."""

    contracts: ContextForgeContractArtifacts
    harness_result: GoalHarnessRunResult
    verification_result: ContextForgeVerificationResult
    goal_run: GoalRunRecord
    graph_state: dict[str, JsonValue]
    runtime_result: dict[str, JsonValue]
    ledger_ref: str
    runtime_result_ref: str
    graph_state_ref: str


@dataclass(frozen=True)
class VerifiedSkillFoundryGoalHarnessResult:
    """A v2 Goal Harness run promoted through SkillFoundry quality gates."""

    goal_harness: SkillFoundryGoalHarnessResult
    verifier_result: VerificationResult
    acceptance_coverage_result: AcceptanceCoverageResult
    contextforge_verification_result: ContextForgeVerificationResult
    registry_entry: RegistryEntry
    final_report: dict[str, JsonValue]
    verified_runtime_result: dict[str, JsonValue]
    verified_runtime_result_ref: str


def run_offline_goal_harness(
    workspace: JobWorkspace,
    *,
    verification_mode: OfflineVerificationMode = "pass",
    run_id: str | None = None,
    created_at: str | None = None,
) -> SkillFoundryGoalHarnessResult:
    """Run one deterministic SkillFoundry build node through ContextForge."""

    workspace.check_locked_inputs()
    timestamp = created_at or utc_now()
    resolved_run_id = run_id or f"{workspace.job_id}-offline-goal-run"
    contracts = write_contextforge_contract_artifacts(workspace, created_at=timestamp)
    ledger = ContextLedger.connect(workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF))
    ledger.initialize()
    try:
        seed_goal_harness_context(
            workspace,
            ledger,
            contracts,
            run_id=resolved_run_id,
            created_at=timestamp,
        )
        harness = GoalHarness(ContextKernel(ledger))
        harness_result = harness.run_single_node(
            contracts.goal_contract,
            contracts.build_node_contract,
            FakeSkillBuilderWorker(workspace),
            graph_id=_GRAPH_ID,
            run_id=resolved_run_id,
            task_id=_TASK_ID,
            created_at=timestamp,
            metadata={"skillfoundry_job_id": workspace.job_id, "attempt_id": "001"},
            checkpoint_reason="phase_complete",
            checkpoint_best_result="Build node completed and worker boundary evidence was recorded.",
            checkpoint_latest_diagnosis="Offline deterministic build node reached verification boundary.",
            checkpoint_next_plan="Run SkillFoundry verifier and bridge the result into ContextForge.",
        )
        _write_offline_verification_evidence(workspace, verification_mode, created_at=timestamp)
        verification_result = VerificationRunner(workspace.root).run(
            contracts.verification_gate,
            goal_run_id=harness_result.goal_run.goal_run_id,
            worker_id=harness_result.worker_run.worker_name,
            created_at=timestamp,
        )
        ledger.record_verification_result(verification_result)
        goal_run = _goal_run_with_verification(
            harness_result.goal_run,
            verification_result,
            created_at=timestamp,
        )
        ledger.record_goal_run_record(goal_run)
        graph_state = build_goal_harness_state(
            workspace,
            contracts,
            harness_result,
            verification_result,
            goal_run,
        )
        runtime_result = _runtime_result_payload(
            workspace,
            contracts,
            harness_result,
            verification_result,
            goal_run,
            graph_state,
            verification_mode,
            created_at=timestamp,
        )
        _write_json(workspace, GOAL_RUNTIME_STATE_REF, graph_state)
        _write_json(workspace, GOAL_RUNTIME_RESULT_REF, runtime_result)
        return SkillFoundryGoalHarnessResult(
            contracts=contracts,
            harness_result=harness_result,
            verification_result=verification_result,
            goal_run=goal_run,
            graph_state=graph_state,
            runtime_result=runtime_result,
            ledger_ref=GOAL_RUNTIME_LEDGER_REF,
            runtime_result_ref=GOAL_RUNTIME_RESULT_REF,
            graph_state_ref=GOAL_RUNTIME_STATE_REF,
        )
    finally:
        ledger.close()


def run_verified_offline_goal_harness(
    workspace: JobWorkspace,
    *,
    registry_path: str | Path,
    version: str = DEFAULT_REGISTRY_VERSION,
    run_id: str | None = None,
    created_at: str | None = None,
) -> VerifiedSkillFoundryGoalHarnessResult:
    """Run the offline v2 build node and promote only through real quality gates."""

    timestamp = created_at or utc_now()
    _check_verified_runtime_inputs(workspace)
    goal_harness = run_offline_goal_harness(
        workspace,
        verification_mode="fail_missing_coverage",
        run_id=run_id,
        created_at=timestamp,
    )
    _write_goal_harness_attempt_artifacts(workspace, goal_harness.harness_result, created_at=timestamp)
    verifier_result = Verifier().verify(workspace, attempt_id="001")
    coverage_plan = AcceptanceCriteriaPlanner().plan(workspace)
    acceptance_coverage_result = AcceptanceCoverageEvaluator().evaluate(workspace, plan=coverage_plan)
    contextforge_verification_result = bridge_skillfoundry_verification_result(
        workspace,
        goal_harness.contracts.verification_gate,
        goal_run_id=goal_harness.goal_run.goal_run_id,
        worker_id=goal_harness.harness_result.worker_run.worker_name,
        expected_gate_hash=goal_harness.contracts.verification_gate.gate_hash,
        created_at=timestamp,
    )
    goal_harness = _finalize_goal_harness_verification(
        workspace,
        goal_harness,
        contextforge_verification_result,
        verification_mode="verified",
        created_at=timestamp,
    )
    registry_entry = LocalSkillRegistry(
        registry_path,
        duplicate_policy=DuplicatePolicy.IDEMPOTENT,
    ).add_verified(
        workspace,
        version=version,
        review_status="v2_goal_harness_verified",
        require_contextforge_verification=True,
    )

    from .graph import WorkflowStatus
    from .offline import emit_final_report

    final_report = emit_final_report(
        workspace.root,
        final_status=WorkflowStatus.REGISTERED,
        registry_path=registry_path,
        registry_entry=registry_entry,
    )
    verified_runtime_result = _verified_runtime_result_payload(
        workspace,
        goal_harness,
        verifier_result,
        acceptance_coverage_result,
        contextforge_verification_result,
        registry_entry,
        final_report,
        created_at=timestamp,
    )
    _write_json(workspace, VERIFIED_GOAL_RUNTIME_RESULT_REF, verified_runtime_result)
    return VerifiedSkillFoundryGoalHarnessResult(
        goal_harness=goal_harness,
        verifier_result=verifier_result,
        acceptance_coverage_result=acceptance_coverage_result,
        contextforge_verification_result=contextforge_verification_result,
        registry_entry=registry_entry,
        final_report=final_report,
        verified_runtime_result=verified_runtime_result,
        verified_runtime_result_ref=VERIFIED_GOAL_RUNTIME_RESULT_REF,
    )


def _check_verified_runtime_inputs(workspace: JobWorkspace) -> None:
    try:
        workspace.resolve_path("acceptance_criteria.yaml", must_exist=True)
    except Exception as exc:
        raise ValueError(
            "verified Goal Harness runtime requires frozen root acceptance_criteria.yaml "
            "before any runtime evidence is persisted"
        ) from exc


def seed_goal_harness_context(
    workspace: JobWorkspace,
    ledger: ContextLedger,
    contracts: ContextForgeContractArtifacts,
    *,
    run_id: str,
    created_at: str,
) -> list[str]:
    """Seed the ContextForge ledger with frozen SkillFoundry context items."""

    items = [
        _context_item(
            workspace,
            item_id=f"{workspace.job_id}:skill_spec",
            run_id=run_id,
            item_type="artifact",
            artifact_ref="skill_spec.yaml",
            content=workspace.resolve_path("skill_spec.yaml", must_exist=True).read_text(encoding="utf-8"),
            context_type="skill_spec",
            prompt_category="project_fact",
            created_at=created_at,
        ),
        _context_item(
            workspace,
            item_id=f"{workspace.job_id}:acceptance_criteria",
            run_id=run_id,
            item_type="acceptance_criterion",
            artifact_ref="skill_spec.yaml",
            content="\n".join(contracts.goal_contract.success_criteria),
            context_type="acceptance_criteria",
            prompt_category="acceptance_criterion",
            created_at=created_at,
        ),
        _context_item(
            workspace,
            item_id=f"{workspace.job_id}:verification_gate",
            run_id=run_id,
            item_type="constraint",
            artifact_ref=VERIFICATION_GATE_REF,
            content=_verification_gate_summary(contracts),
            context_type="verification_gate",
            prompt_category="constraint",
            created_at=created_at,
        ),
        _context_item(
            workspace,
            item_id=f"{workspace.job_id}:build_contract",
            run_id=run_id,
            item_type="constraint",
            artifact_ref="build_contract.yaml",
            content=workspace.resolve_path("build_contract.yaml", must_exist=True).read_text(encoding="utf-8"),
            context_type="build_contract",
            prompt_category="constraint",
            created_at=created_at,
        ),
    ]
    raw_path = workspace.root / _RAW_CONVERSATION_REF
    if raw_path.is_file():
        raw_content = raw_path.read_text(encoding="utf-8")
        items.append(
            _context_item(
                workspace,
                item_id=f"{workspace.job_id}:raw_frontdesk_conversation",
                run_id=run_id,
                item_type="user_message",
                artifact_ref=_RAW_CONVERSATION_REF,
                content=raw_content,
                context_type="raw_frontdesk_conversation",
                prompt_category="recent_message",
                created_at=created_at,
                tags=["raw_frontdesk_conversation"],
                prompt_include=True,
            )
        )
    recorded: list[str] = []
    for item in items:
        recorded.append(ledger.record_context_item(item))
    return recorded


def build_goal_harness_state(
    workspace: JobWorkspace,
    contracts: ContextForgeContractArtifacts,
    harness_result: GoalHarnessRunResult,
    verification_result: ContextForgeVerificationResult,
    goal_run: GoalRunRecord,
) -> dict[str, JsonValue]:
    """Return the LangGraph-style refs-only state for the offline slice."""

    next_route = _route_for_verification(verification_result)
    contextforge_state: dict[str, JsonValue] = {
        "last_goal_run_id": goal_run.goal_run_id,
        "last_worker_run_id": harness_result.worker_run.worker_run_id,
        "last_context_view_id": harness_result.compiled_context.context_view.context_view_id,
        "last_prompt_cache_plan_id": harness_result.compiled_context.cache_plan.cache_plan_id,
        "last_verification_result_id": verification_result.verification_result_id,
        "last_verification_status": verification_result.status,
        "next_route": next_route,
    }
    if goal_run.checkpoint_ids:
        contextforge_state["last_checkpoint_id"] = goal_run.checkpoint_ids[-1]
        contextforge_state["checkpoint_ids"] = list(goal_run.checkpoint_ids)
    return {
        "schema_version": GOAL_RUNTIME_STATE_SCHEMA_VERSION,
        "job_id": workspace.job_id,
        "stage": "build",
        "status": goal_run.status,
        "attempt_count": 1,
        "refs": {
            "goal_contract": GOAL_CONTRACT_REF,
            "build_node_contract": BUILD_NODE_CONTRACT_REF,
            "verification_gate": VERIFICATION_GATE_REF,
            "contract_manifest": CONTRACT_MANIFEST_REF,
            "ledger": GOAL_RUNTIME_LEDGER_REF,
            "runtime_result": GOAL_RUNTIME_RESULT_REF,
        },
        "hashes": {
            "goal_contract": contracts.goal_contract.contract_hash,
            "build_node_contract": contracts.build_node_contract.contract_hash,
            "verification_gate": contracts.verification_gate.gate_hash,
        },
        "contextforge": contextforge_state,
        "human_review_required": verification_result.status == "human_acceptance_required",
        "next_route": next_route,
    }


def _context_item(
    workspace: JobWorkspace,
    *,
    item_id: str,
    run_id: str,
    item_type: str,
    artifact_ref: str,
    content: str,
    context_type: str,
    prompt_category: str,
    created_at: str,
    tags: list[str] | None = None,
    prompt_include: bool = True,
) -> ContextItem:
    metadata: dict[str, JsonValue] = {
        "skillfoundry_context_type": context_type,
        "prompt_category": prompt_category,
        "prompt_include": prompt_include,
        "tags": tags or ["frozen_input"],
    }
    return ContextItem(
        id=item_id,
        graph_id=_GRAPH_ID,
        run_id=run_id,
        task_id=_TASK_ID,
        node_id=_BUILD_NODE_ID,
        type=item_type,  # type: ignore[arg-type]
        content=content,
        source=ContextSource(
            kind="artifact",
            ref=artifact_ref,
            name=context_type,
            sha256=_sha256_or_none(workspace, artifact_ref),
            metadata={"workspace_job_id": workspace.job_id},
        ),
        importance=1.0,
        token_estimate=estimate_tokens(content),
        created_at=created_at,
        artifact_ref=artifact_ref,
        provenance={"job_id": workspace.job_id, "artifact_ref": artifact_ref},
        metadata=metadata,
    )


def _write_offline_verification_evidence(
    workspace: JobWorkspace,
    mode: OfflineVerificationMode,
    *,
    created_at: str,
) -> None:
    verifier_payload = {
        "schema_version": "skillfoundry.offline_verifier_result.v1",
        "job_id": workspace.job_id,
        "passed": mode == "pass",
        "created_at": created_at,
        "evidence": ["package/SKILL.md"],
        "worker_self_report_is_not_acceptance": True,
    }
    coverage_payload = {
        "schema_version": "skillfoundry.offline_acceptance_coverage.v1",
        "job_id": workspace.job_id,
        "passed": mode == "pass",
        "created_at": created_at,
        "covered": ["Reports correctness risks before summaries."],
    }
    _write_json(workspace, "verifier/verification_result.json", verifier_payload)
    if mode == "pass":
        (workspace.root / "qa").mkdir(parents=True, exist_ok=True)
        _write_json(workspace, "qa/acceptance_coverage_result.json", coverage_payload)
        return
    coverage_path = workspace.root / "qa" / "acceptance_coverage_result.json"
    if coverage_path.exists():
        coverage_path.unlink()


def _write_goal_harness_attempt_artifacts(
    workspace: JobWorkspace,
    harness_result: GoalHarnessRunResult,
    *,
    created_at: str,
    attempt_id: str = "001",
) -> None:
    """Write SkillFoundry verifier-compatible attempt evidence for a v2 WorkerRun."""

    worker_run = harness_result.worker_run
    attempt_dir_ref = f"attempts/{attempt_id}"
    attempt_dir = workspace.resolve_path(attempt_dir_ref)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    invocation_id = worker_run.worker_run_id
    input_manifest_ref = f"{attempt_dir_ref}/input_manifest.json"
    execution_report_ref = f"{attempt_dir_ref}/execution_report.json"
    transcript_ref = f"{attempt_dir_ref}/worker_transcript.log"
    diff_ref = f"{attempt_dir_ref}/output_diff.patch"
    artifact_refs = [
        ref
        for ref in worker_run.metadata.get("artifact_refs", [])
        if isinstance(ref, str) and ref.startswith("package/")
    ]
    input_manifest = {
        "schema_version": "skillfoundry.worker_input_manifest.v2",
        "adapter_version": "skillfoundry.goal_runtime.v2",
        "generated_at": created_at,
        "invocation_id": invocation_id,
        "job_id": workspace.job_id,
        "attempt_id": attempt_id,
        "worker_type": f"contextforge:{worker_run.worker_kind}",
        "build_contract_ref": "build_contract.yaml",
        "skill_spec_ref": "skill_spec.yaml",
        "verification_spec_ref": "verification_spec.yaml",
        "worker_input_ref": "worker_input.md",
        "artifact_manifest_ref": "artifact_manifest.json",
        "contextforge": {
            "goal_run_id": worker_run.goal_run_id,
            "worker_run_id": worker_run.worker_run_id,
            "context_view_id": worker_run.input_context_view_id,
            "prompt_view_ids": worker_run.prompt_view_ids,
        },
        "declared_allowed_write_paths": list(harness_result.goal_run.metadata.get("allowed_write_paths", [])),
        "writable_paths": ["package", attempt_dir_ref],
        "worker_config": {"runtime": "contextforge_goal_harness_v2"},
    }
    _write_json(workspace, input_manifest_ref, input_manifest)
    exit_status = "success" if worker_run.status == "completed" else worker_run.failure_class or worker_run.status
    report = ExecutionReport(
        report_id=f"report-{invocation_id}",
        invocation_id=invocation_id,
        job_id=workspace.job_id,
        attempt_id=attempt_id,
        status=worker_run.status,
        started_at=worker_run.created_at,
        finished_at=worker_run.completed_at or created_at,
        duration_ms=0,
        exit_status=exit_status,
        summary=str(worker_run.metadata.get("summary") or "ContextForge Goal Harness worker run."),
        artifacts=artifact_refs,
        failures=[] if exit_status == "success" else [worker_run.failure_class or worker_run.status],
    )
    report.write_json_file(workspace.resolve_path(execution_report_ref))
    _write_text(
        workspace,
        transcript_ref,
        "\n".join(
            [
                "ContextForge Goal Harness v2 worker boundary evidence.",
                f"goal_run_id={worker_run.goal_run_id}",
                f"worker_run_id={worker_run.worker_run_id}",
                f"worker_kind={worker_run.worker_kind}",
                f"status={worker_run.status}",
                "worker_self_report_is_not_acceptance=true",
                "",
            ]
        ),
    )
    _write_text(
        workspace,
        diff_ref,
        "\n".join(
            [
                "ContextForge Goal Harness v2 changed files:",
                *[f"- {item}" for item in worker_run.metadata.get("changed_files", []) if isinstance(item, str)],
                "",
            ]
        ),
    )


def _finalize_goal_harness_verification(
    workspace: JobWorkspace,
    goal_harness: SkillFoundryGoalHarnessResult,
    verification_result: ContextForgeVerificationResult,
    *,
    verification_mode: GoalRuntimeVerificationMode,
    created_at: str,
) -> SkillFoundryGoalHarnessResult:
    final_goal_run = _goal_run_with_verification(
        goal_harness.harness_result.goal_run,
        verification_result,
        created_at=created_at,
    )
    verification_checkpoint = CheckpointManager().create(
        goal_harness.contracts.goal_contract,
        final_goal_run,
        reason="phase_complete" if verification_result.status == "passed" else "verifier_failed",
        current_best_result=_checkpoint_best_result(verification_result),
        latest_diagnosis=_checkpoint_latest_diagnosis(verification_result),
        next_plan=_checkpoint_next_plan(verification_result),
        created_at=created_at,
        metadata={"skillfoundry_goal_runtime": GOAL_RUNTIME_RESULT_SCHEMA_VERSION},
    )
    final_goal_run = GoalRunRecord.from_dict(
        {
            **final_goal_run.to_dict(),
            "checkpoint_ids": _dedupe([*final_goal_run.checkpoint_ids, verification_checkpoint.checkpoint_id]),
            "updated_at": created_at,
            "metadata": {
                **final_goal_run.metadata,
                "latest_checkpoint_id": verification_checkpoint.checkpoint_id,
                "verification_checkpoint_id": verification_checkpoint.checkpoint_id,
            },
        }
    )
    graph_state = build_goal_harness_state(
        workspace,
        goal_harness.contracts,
        goal_harness.harness_result,
        verification_result,
        final_goal_run,
    )
    runtime_result = _runtime_result_payload(
        workspace,
        goal_harness.contracts,
        goal_harness.harness_result,
        verification_result,
        final_goal_run,
        graph_state,
        verification_mode,
        created_at=created_at,
    )
    ledger = ContextLedger.connect(workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF, must_exist=True))
    try:
        ledger.record_verification_result(verification_result)
        ledger.record_checkpoint(verification_checkpoint)
        ledger.record_goal_run_record(final_goal_run)
    finally:
        ledger.close()
    _write_json(workspace, GOAL_RUNTIME_STATE_REF, graph_state)
    _write_json(workspace, GOAL_RUNTIME_RESULT_REF, runtime_result)
    return replace(
        goal_harness,
        verification_result=verification_result,
        goal_run=final_goal_run,
        graph_state=graph_state,
        runtime_result=runtime_result,
    )


def _checkpoint_best_result(verification_result: ContextForgeVerificationResult) -> str:
    if verification_result.status == "passed":
        return "Verification bridge passed and final evidence is ready for registry gating."
    if verification_result.status == "failed":
        return "Verification bridge failed and repair evidence is required before registry gating."
    return f"Verification bridge returned {verification_result.status}; route according to review policy."


def _checkpoint_latest_diagnosis(verification_result: ContextForgeVerificationResult) -> str:
    failed = [item.validator_id for item in verification_result.validator_results if not item.passed]
    if not failed:
        return "All blocking verification bridge validators passed."
    return "Failed verification bridge validators: " + ", ".join(failed[:10])


def _checkpoint_next_plan(verification_result: ContextForgeVerificationResult) -> str:
    if verification_result.status == "passed":
        return "Proceed to registry gate using ContextForge bridge and SkillFoundry verifier evidence refs."
    if verification_result.status == "failed":
        return "Route to repair and preserve verifier/coverage failure refs for the next attempt."
    return "Route to human review or redesign according to verification status."


def _goal_run_with_verification(
    goal_run: GoalRunRecord,
    verification_result: ContextForgeVerificationResult,
    *,
    created_at: str,
) -> GoalRunRecord:
    if verification_result.status == "passed":
        status = "completed"
        decision = "complete"
    elif verification_result.status == "failed":
        status = "failed"
        decision = "repair"
    elif verification_result.status in {"review_required", "human_acceptance_required"}:
        status = "blocked"
        decision = "escalate"
    else:
        status = "blocked"
        decision = "redesign"
    payload = goal_run.to_dict()
    payload.update(
        {
            "status": status,
            "decision": decision,
            "verification_result_id": verification_result.verification_result_id,
            "updated_at": created_at,
            "completed_at": created_at,
            "evidence_ids": _dedupe(
                [
                    *goal_run.evidence_ids,
                    verification_result.verification_result_id,
                    "verifier/verification_result.json",
                    "qa/acceptance_coverage_result.json",
                ]
            ),
            "metadata": {
                **goal_run.metadata,
                "verification_pending": False,
                "verification_status": verification_result.status,
                "worker_self_report_is_not_acceptance": True,
            },
        }
    )
    return GoalRunRecord.from_dict(payload)


def _runtime_result_payload(
    workspace: JobWorkspace,
    contracts: ContextForgeContractArtifacts,
    harness_result: GoalHarnessRunResult,
    verification_result: ContextForgeVerificationResult,
    goal_run: GoalRunRecord,
    graph_state: dict[str, JsonValue],
    verification_mode: GoalRuntimeVerificationMode,
    *,
    created_at: str,
) -> dict[str, JsonValue]:
    return {
        "schema_version": GOAL_RUNTIME_RESULT_SCHEMA_VERSION,
        "job_id": workspace.job_id,
        "created_at": created_at,
        "verification_mode": verification_mode,
        "refs": {
            "goal_contract": GOAL_CONTRACT_REF,
            "build_node_contract": BUILD_NODE_CONTRACT_REF,
            "verification_gate": VERIFICATION_GATE_REF,
            "ledger": GOAL_RUNTIME_LEDGER_REF,
            "graph_state": GOAL_RUNTIME_STATE_REF,
        },
        "ids": {
            "goal_id": contracts.goal_contract.goal_id,
            "node_id": contracts.build_node_contract.node_id,
            "goal_run_id": goal_run.goal_run_id,
            "worker_run_id": harness_result.worker_run.worker_run_id,
            "context_view_id": harness_result.compiled_context.context_view.context_view_id,
            "prompt_view_id": harness_result.compiled_context.prompt_view.id,
            "cache_plan_id": harness_result.compiled_context.cache_plan.cache_plan_id,
            "verification_result_id": verification_result.verification_result_id,
        },
        "status": {
            "worker": harness_result.worker_run.status,
            "verification": verification_result.status,
            "goal_run": goal_run.status,
            "decision": goal_run.decision,
            "next_route": graph_state["next_route"],
        },
        "hashes": {
            "goal_contract": contracts.goal_contract.contract_hash,
            "build_node_contract": contracts.build_node_contract.contract_hash,
            "verification_gate": contracts.verification_gate.gate_hash,
            "graph_state": sha256_json(graph_state),
        },
    }


def _verified_runtime_result_payload(
    workspace: JobWorkspace,
    goal_harness: SkillFoundryGoalHarnessResult,
    verifier_result: VerificationResult,
    acceptance_coverage_result: AcceptanceCoverageResult,
    contextforge_verification_result: ContextForgeVerificationResult,
    registry_entry: RegistryEntry,
    final_report: dict[str, JsonValue],
    *,
    created_at: str,
) -> dict[str, JsonValue]:
    payload = {
        "schema_version": VERIFIED_GOAL_RUNTIME_RESULT_SCHEMA_VERSION,
        "job_id": workspace.job_id,
        "created_at": created_at,
        "refs": {
            **goal_harness.runtime_result.get("refs", {}),
            "goal_runtime_result": GOAL_RUNTIME_RESULT_REF,
            "verified_runtime_result": VERIFIED_GOAL_RUNTIME_RESULT_REF,
            "worker_input_manifest": "attempts/001/input_manifest.json",
            "worker_execution_report": "attempts/001/execution_report.json",
            "worker_transcript": "attempts/001/worker_transcript.log",
            "worker_diff": "attempts/001/output_diff.patch",
            "skillfoundry_verification_result": "verifier/verification_result.json",
            "acceptance_coverage_result": "qa/acceptance_coverage_result.json",
            "contextforge_verification_result": "contextforge/verification_result.json",
            "final_report": "final_report.json",
        },
        "ids": {
            **goal_harness.runtime_result.get("ids", {}),
            "skillfoundry_verification_result_id": verifier_result.result_id,
            "acceptance_coverage_result_id": acceptance_coverage_result.result_id,
            "contextforge_verification_result_id": contextforge_verification_result.verification_result_id,
            "registry_skill_id": registry_entry.skill_id,
            "registry_version": registry_entry.version,
        },
        "status": {
            **goal_harness.runtime_result.get("status", {}),
            "skillfoundry_verification_passed": verifier_result.passed,
            "acceptance_coverage_passed": acceptance_coverage_result.passed,
            "contextforge_verification": contextforge_verification_result.status,
            "registry_approved": registry_entry.approval_status == "approved",
            "final_status": final_report.get("final_status"),
        },
        "hashes": {
            **goal_harness.runtime_result.get("hashes", {}),
            "skillfoundry_verification_result": sha256_file(
                workspace.resolve_path("verifier/verification_result.json", must_exist=True)
            ),
            "acceptance_coverage_result": sha256_file(
                workspace.resolve_path("qa/acceptance_coverage_result.json", must_exist=True)
            ),
            "contextforge_verification_result": sha256_file(
                workspace.resolve_path("contextforge/verification_result.json", must_exist=True)
            ),
            "registry_entry": sha256_json(registry_entry.to_dict()),
        },
        "trust_boundaries": {
            "worker_self_report_is_not_acceptance": True,
            "registry_requires_contextforge_verification": True,
            "verifier_is_quality_fact_source": True,
            "acceptance_coverage_required": True,
        },
    }
    return ensure_json_compatible(payload)  # type: ignore[return-value]


def _verification_gate_summary(contracts: ContextForgeContractArtifacts) -> str:
    gate = contracts.verification_gate
    return json.dumps(
        {
            "verification_gate_id": gate.verification_gate_id,
            "gate_hash": gate.gate_hash,
            "required_evidence": gate.required_evidence,
            "forbidden_claims": gate.forbidden_claims,
            "unsupported_behavior": gate.unsupported_behavior,
            "stage": gate.metadata.get("gate_stage"),
        },
        sort_keys=True,
    )


def _route_for_verification(verification_result: ContextForgeVerificationResult) -> str:
    if verification_result.status == "passed":
        return "registry_gate"
    if verification_result.status == "failed":
        return "repair_goal_node"
    if verification_result.status in {"review_required", "human_acceptance_required"}:
        return "human_review"
    return "redesign"


def _sha256_or_none(workspace: JobWorkspace, artifact_ref: str) -> str | None:
    try:
        path = workspace.resolve_path(artifact_ref, must_exist=True)
    except Exception:
        return None
    if path.is_file():
        return "sha256:" + sha256_file(path)
    return None


def _write_json(workspace: JobWorkspace, relative_path: str, payload: dict[str, JsonValue]) -> None:
    compatible = ensure_json_compatible(payload)
    if not isinstance(compatible, dict):
        raise ValueError("payload must be a JSON object")
    path = workspace.resolve_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(compatible, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_text(workspace: JobWorkspace, relative_path: str, content: str) -> None:
    path = workspace.resolve_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
