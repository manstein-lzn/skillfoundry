"""Offline Goal Harness vertical slice for SkillFoundry v2."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal

from contextforge import (
    ContextItem,
    ContextKernel,
    ContextLedger,
    ContextSource,
    GoalHarness,
    GoalHarnessRunResult,
    GoalRunRecord,
    VerificationResult as ContextForgeVerificationResult,
    VerificationRunner,
    WorkerRunRequest,
    WorkerRunResult,
    estimate_tokens,
)

from .contracts import (
    BUILD_NODE_CONTRACT_REF,
    CONTRACT_MANIFEST_REF,
    GOAL_CONTRACT_REF,
    VERIFICATION_GATE_REF,
    ContextForgeContractArtifacts,
    write_contextforge_contract_artifacts,
)
from .schema import JsonValue, ensure_json_compatible, sha256_file, sha256_json, utc_now
from .workspace import JobWorkspace


GOAL_RUNTIME_LEDGER_REF = "contextforge/ledger.sqlite3"
GOAL_RUNTIME_RESULT_REF = "contextforge/goal_runtime_result.json"
GOAL_RUNTIME_STATE_REF = "contextforge/goal_harness_state.json"
GOAL_RUNTIME_RESULT_SCHEMA_VERSION = "skillfoundry.goal_runtime_result.v1"
GOAL_RUNTIME_STATE_SCHEMA_VERSION = "skillfoundry.goal_harness_state.v1"

_GRAPH_ID = "skillfoundry-v2"
_BUILD_NODE_ID = "build_skill"
_TASK_ID = "build_skill"
_RAW_CONVERSATION_REF = "frontdesk/conversation.jsonl"


OfflineVerificationMode = Literal["pass", "fail_missing_coverage"]


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
class FakeSkillBuilderWorker:
    """Deterministic fake SkillFoundry builder used by the offline slice."""

    workspace: JobWorkspace
    name: str = "skillfoundry-fake-skill-builder"
    status: Literal["completed", "failed"] = "completed"
    failure_class: str | None = None

    kind: str = "fake_model"

    def run(self, request: WorkerRunRequest) -> WorkerRunResult:
        package_ref = "package/SKILL.md"
        report_ref = "attempts/fake_worker_report.json"
        if self.status == "completed":
            _write_fake_skill_package(self.workspace, request, package_ref)
        _write_fake_worker_report(self.workspace, request, report_ref, self.status, self.failure_class)
        package_id = f"{self.workspace.job_id}:{package_ref}"
        report_id = f"{self.workspace.job_id}:{report_ref}"
        artifact_ids = [report_id]
        if self.status == "completed":
            artifact_ids.insert(0, package_id)
        return WorkerRunResult(
            status=self.status,
            worker_name=self.name,
            final_output_ref=package_ref if self.status == "completed" else report_ref,
            summary="Fake SkillFoundry builder wrote deterministic offline artifacts.",
            failure_class=self.failure_class,
            prompt_view_ids=[request.prompt_view.id],
            artifact_ids=artifact_ids,
            usage_summary={
                "provider": "offline",
                "model": "fake_model",
                "expected_cacheable_tokens": request.cache_plan.expected_cacheable_tokens,
                "cache_telemetry_status": request.cache_plan.cache_telemetry_status,
                "usage_unavailable_reason": "offline_fake_worker",
            },
            metadata={
                "fake_skillfoundry_worker": True,
                "package_ref": package_ref if self.status == "completed" else None,
                "report_ref": report_ref,
                "worker_self_report_is_not_acceptance": True,
            },
        )


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
            metadata={"skillfoundry_job_id": workspace.job_id},
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
        "contextforge": {
            "last_goal_run_id": goal_run.goal_run_id,
            "last_worker_run_id": harness_result.worker_run.worker_run_id,
            "last_context_view_id": harness_result.compiled_context.context_view.context_view_id,
            "last_prompt_cache_plan_id": harness_result.compiled_context.cache_plan.cache_plan_id,
            "last_verification_result_id": verification_result.verification_result_id,
            "last_verification_status": verification_result.status,
            "next_route": next_route,
        },
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


def _write_fake_skill_package(
    workspace: JobWorkspace,
    request: WorkerRunRequest,
    package_ref: str,
) -> None:
    package = workspace.resolve_path(package_ref)
    content = "\n".join(
        [
            "---",
            "name: generated-review-assistant",
            "description: Deterministic offline SkillFoundry package generated by Goal Harness tests.",
            "---",
            "",
            "# Generated Review Assistant",
            "",
            "Use this skill when a user asks for repository review assistance.",
            "",
            "## Instructions",
            "",
            "- Inspect repository-local evidence before reporting findings.",
            "- Report correctness risks before summaries.",
            "- Include file and line references for each finding.",
            "- Do not claim verification or registry approval.",
            "",
            "## Goal Harness Evidence",
            "",
            f"- Goal run: {request.goal_run_id}",
            f"- Context view: {request.context_view.context_view_id}",
            f"- Prompt cache plan: {request.cache_plan.cache_plan_id}",
            "",
        ]
    )
    package.write_text(content, encoding="utf-8")


def _write_fake_worker_report(
    workspace: JobWorkspace,
    request: WorkerRunRequest,
    report_ref: str,
    status: str,
    failure_class: str | None,
) -> None:
    payload = {
        "schema_version": "skillfoundry.fake_worker_report.v1",
        "job_id": workspace.job_id,
        "goal_run_id": request.goal_run_id,
        "context_view_id": request.context_view.context_view_id,
        "prompt_view_id": request.prompt_view.id,
        "cache_plan_id": request.cache_plan.cache_plan_id,
        "status": status,
        "failure_class": failure_class,
        "worker_self_report_is_not_acceptance": True,
    }
    _write_json(workspace, report_ref, payload)


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
    verification_mode: OfflineVerificationMode,
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


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
