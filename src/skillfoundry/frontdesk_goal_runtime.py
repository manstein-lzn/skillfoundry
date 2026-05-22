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

from .frontdesk_schema import (
    AcceptanceCriteriaSet,
    AcceptanceCriterion,
    CoreNeedBrief,
    CoreNeedDiscoveryReport,
    FeasibilityReport,
    PlanReviewRecord,
    SolutionPlan,
    SpecAuditReport,
)
from .frontdesk_v2 import (
    CORE_NEED_DISCOVERY_NODE_ID,
    FRONTDESK_V2_CONTRACT_DIR,
    FRONTDESK_V2_SCHEMA_VERSION,
    SOLUTION_PLANNER_NODE_ID,
    SPEC_AUDITOR_NODE_ID,
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
from .schema import JsonValue, SkillSpec, ensure_json_compatible, sha256_file, sha256_json, utc_now
from .workspace import JobWorkspace


FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION = "skillfoundry.frontdesk_goal_runtime.v1"
FRONTDESK_GOAL_RUNTIME_LEDGER_REF = f"{FRONTDESK_V2_CONTRACT_DIR}/goal_runtime_ledger.sqlite3"
FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF = f"{FRONTDESK_V2_CONTRACT_DIR}/core_need_runtime_result.json"
FRONTDESK_CORE_NEED_RUNTIME_STATE_REF = f"{FRONTDESK_V2_CONTRACT_DIR}/core_need_runtime_state.json"
FRONTDESK_CORE_NEED_BRIEF_REF = "frontdesk/core_need_brief.json"
FRONTDESK_CORE_NEED_REPORT_REF = "frontdesk/core_need_discovery_report.json"
FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF = f"{FRONTDESK_V2_CONTRACT_DIR}/solution_plan_runtime_result.json"
FRONTDESK_SOLUTION_PLAN_RUNTIME_STATE_REF = f"{FRONTDESK_V2_CONTRACT_DIR}/solution_plan_runtime_state.json"
FRONTDESK_SOLUTION_PLAN_REF = "frontdesk/solution_plan.json"
FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF = "frontdesk/solution_plan.md"
FRONTDESK_DRAFT_SKILL_SPEC_REF = "frontdesk/draft_skill_spec.yaml"
FRONTDESK_ACCEPTANCE_CRITERIA_REF = "frontdesk/acceptance_criteria.yaml"
FRONTDESK_SPEC_AUDIT_RUNTIME_RESULT_REF = f"{FRONTDESK_V2_CONTRACT_DIR}/spec_audit_runtime_result.json"
FRONTDESK_SPEC_AUDIT_RUNTIME_STATE_REF = f"{FRONTDESK_V2_CONTRACT_DIR}/spec_audit_runtime_state.json"
FRONTDESK_SPEC_AUDIT_REPORT_REF = "frontdesk/spec_audit_report_001.json"
FRONTDESK_FEASIBILITY_REPORT_REF = "frontdesk/feasibility_report.json"
FRONTDESK_SPEC_AUDIT_FAILURE_REF = "frontdesk/spec_audit_failure_001.json"
FRONTDESK_PLAN_REVIEW_REF = "frontdesk/plan_review_001.json"

_GRAPH_ID = "skillfoundry-frontdesk-v2"


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
class FrontDeskSolutionPlannerGoalHarnessResult:
    """Artifacts produced by the Solution Planner Goal Harness slice."""

    harness_result: GoalHarnessRunResult
    goal_run: GoalRunRecord
    runtime_result: dict[str, JsonValue]
    runtime_state: dict[str, JsonValue]
    ledger_ref: str
    runtime_result_ref: str
    runtime_state_ref: str


@dataclass(frozen=True)
class FrontDeskSpecAuditorGoalHarnessResult:
    """Artifacts produced by the Spec Auditor Goal Harness slice."""

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
                model_name="frontdesk_core_need_deterministic_fixture",
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
            model_name="frontdesk_core_need_deterministic_fixture",
            metadata={"frontdesk_core_need_fake_worker": True},
        )


@dataclass(frozen=True)
class FrontDeskSolutionPlannerFakeWorker:
    """Deterministic worker used to prove the Solution Planner Goal Harness boundary."""

    frontdesk: FrontDeskWorkspace
    name: str = "frontdesk-solution-planner-deterministic-worker"

    kind: str = "fake_model"

    def run(self, request: WorkerRunRequest) -> WorkerRunResult:
        changed_files = [
            FRONTDESK_SOLUTION_PLAN_REF,
            FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF,
            FRONTDESK_DRAFT_SKILL_SPEC_REF,
            FRONTDESK_ACCEPTANCE_CRITERIA_REF,
        ]
        try:
            enforce_write_scope(changed_files, request.node_contract.write_scope)
        except PolicyViolation as exc:
            return _frontdesk_worker_result(
                request,
                worker_name=self.name,
                status="failed",
                final_output_ref=None,
                summary="Front Desk Solution Planner worker failed closed on write scope policy.",
                failure_class="write_scope_violation",
                artifact_refs=[],
                changed_files=[],
                attempted_changed_files=changed_files,
                model_name="frontdesk_solution_planner_deterministic_fixture",
                metadata={"policy_error": str(exc)},
            )

        try:
            brief = CoreNeedBrief.from_json(
                self.frontdesk.workspace.resolve_path(FRONTDESK_CORE_NEED_BRIEF_REF, must_exist=True).read_text(
                    encoding="utf-8"
                )
            )
        except Exception as exc:
            return _frontdesk_worker_result(
                request,
                worker_name=self.name,
                status="failed",
                final_output_ref=None,
                summary="Front Desk Solution Planner worker requires a valid governed core-need brief.",
                failure_class="missing_or_invalid_core_need_brief",
                artifact_refs=[],
                changed_files=[],
                attempted_changed_files=changed_files,
                model_name="frontdesk_solution_planner_deterministic_fixture",
                metadata={"core_need_error": str(exc)},
            )

        skill_spec = _draft_skill_spec_from_core_need(brief)
        acceptance_criteria = _acceptance_criteria_from_core_need(self.frontdesk, brief)
        plan = SolutionPlan(
            plan_id="solution-plan-001",
            core_need_brief_ref=FRONTDESK_CORE_NEED_BRIEF_REF,
            summary=brief.problem_statement,
            proposed_skill_name=skill_spec.title,
            target_user=brief.target_user,
            user_problem=brief.problem_statement,
            desired_outcome=brief.desired_outcome,
            approach=(
                "Create a governed SkillFoundry skill from frozen Front Desk artifacts after explicit user "
                "review."
            ),
            implementation_outline=[
                "Use the approved solution plan and acceptance criteria as frozen builder inputs.",
                "Route build execution through ContextForge Goal Harness worker boundaries.",
                "Require verifier and registry evidence before promotion.",
            ],
            key_decisions=[
                "Input boundary: governed core_need_brief.json; clarification_summary.md; risk_report.json; budget.json",
                "Output target: solution_plan.json; draft_skill_spec.yaml; acceptance_criteria.yaml",
                "Raw conversation remains forbidden provenance and is not a planning input.",
            ],
            acceptance_summary=[
                brief.success_signal,
                "Builder receives frozen artifacts only after user approval.",
                "Raw Front Desk conversation never enters builder context.",
            ],
            risks=list(brief.risk_flags),
            open_confirmation_items=[
                "User must approve or request changes before freeze.",
            ],
            status="awaiting_user_review",
            draft_skill_spec_ref=FRONTDESK_DRAFT_SKILL_SPEC_REF,
            acceptance_criteria_ref=FRONTDESK_ACCEPTANCE_CRITERIA_REF,
            markdown_ref=FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF,
        )
        write_frontdesk_artifact(self.frontdesk, FRONTDESK_DRAFT_SKILL_SPEC_REF, skill_spec)
        write_frontdesk_artifact(self.frontdesk, FRONTDESK_ACCEPTANCE_CRITERIA_REF, acceptance_criteria)
        write_frontdesk_artifact(self.frontdesk, FRONTDESK_SOLUTION_PLAN_REF, plan)
        write_frontdesk_artifact(self.frontdesk, FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF, _solution_plan_markdown(plan, brief))
        return _frontdesk_worker_result(
            request,
            worker_name=self.name,
            status="completed",
            final_output_ref=FRONTDESK_SOLUTION_PLAN_REF,
            summary="Front Desk Solution Planner worker wrote governed plan artifacts for user review.",
            failure_class=None,
            artifact_refs=changed_files,
            changed_files=changed_files,
            attempted_changed_files=changed_files,
            model_name="frontdesk_solution_planner_deterministic_fixture",
            metadata={"frontdesk_solution_planner_fake_worker": True},
        )


@dataclass(frozen=True)
class FrontDeskSpecAuditorFakeWorker:
    """Deterministic worker used to prove the Spec Auditor Goal Harness boundary."""

    frontdesk: FrontDeskWorkspace
    plan_review_ref: str = FRONTDESK_PLAN_REVIEW_REF
    audit_report_ref: str = FRONTDESK_SPEC_AUDIT_REPORT_REF
    audit_elicitation_report_ref: str = FRONTDESK_SOLUTION_PLAN_REF
    name: str = "frontdesk-spec-auditor-deterministic-worker"

    kind: str = "fake_model"

    def run(self, request: WorkerRunRequest) -> WorkerRunResult:
        success_files = [self.audit_report_ref, FRONTDESK_FEASIBILITY_REPORT_REF]
        attempted_changed_files = [*success_files, FRONTDESK_SPEC_AUDIT_FAILURE_REF]
        try:
            enforce_write_scope(attempted_changed_files, request.node_contract.write_scope)
        except PolicyViolation as exc:
            return _frontdesk_worker_result(
                request,
                worker_name=self.name,
                status="failed",
                final_output_ref=None,
                summary="Front Desk Spec Auditor worker failed closed on write scope policy.",
                failure_class="write_scope_violation",
                artifact_refs=[],
                changed_files=[],
                attempted_changed_files=attempted_changed_files,
                model_name="frontdesk_spec_auditor_deterministic_fixture",
                metadata={"policy_error": str(exc)},
            )

        try:
            plan = SolutionPlan.from_json(
                self.frontdesk.workspace.resolve_path(FRONTDESK_SOLUTION_PLAN_REF, must_exist=True).read_text(
                    encoding="utf-8"
                )
            )
            draft_spec = self.frontdesk.workspace.resolve_path(
                FRONTDESK_DRAFT_SKILL_SPEC_REF, must_exist=True
            ).read_text(encoding="utf-8")
            acceptance_criteria = self.frontdesk.workspace.resolve_path(
                FRONTDESK_ACCEPTANCE_CRITERIA_REF, must_exist=True
            ).read_text(encoding="utf-8")
        except Exception as exc:
            return self._fail_closed(
                request,
                failure_class="missing_or_invalid_audit_inputs",
                message="Front Desk Spec Auditor requires valid governed plan, draft spec, and acceptance refs.",
                attempted_changed_files=attempted_changed_files,
                details={"audit_input_error": str(exc)},
            )

        plan_review: PlanReviewRecord | None = None
        plan_review_error: Exception | None = None
        try:
            plan_review = PlanReviewRecord.from_json(
                self.frontdesk.workspace.resolve_path(self.plan_review_ref, must_exist=True).read_text(
                    encoding="utf-8"
                )
            )
        except Exception as exc:
            plan_review_error = exc
        if plan.status != "approved" and plan_review_error is not None:
            return self._fail_closed(
                request,
                failure_class="solution_plan_not_approved",
                message="Front Desk Spec Auditor requires an approved solution plan before audit.",
                attempted_changed_files=attempted_changed_files,
                details={"solution_plan_status": plan.status},
            )
        if plan_review_error is not None or plan_review is None:
            return self._fail_closed(
                request,
                failure_class="missing_or_invalid_plan_review",
                message="Front Desk Spec Auditor requires a valid approved plan review record before audit.",
                attempted_changed_files=attempted_changed_files,
                details={"plan_review_error": str(plan_review_error), "plan_review_ref": self.plan_review_ref},
            )
        review_failure = _plan_review_failure(self.frontdesk, plan_review, plan_review_ref=self.plan_review_ref)
        if review_failure is not None:
            failure_class, message, details = review_failure
            return self._fail_closed(
                request,
                failure_class=failure_class,
                message=message,
                attempted_changed_files=attempted_changed_files,
                details=details,
            )

        feasibility = FeasibilityReport(
            decision="feasible",
            feasibility_score=0.86,
            risk_score=0.18,
            routing_recommendation="codex_worker",
            required_capabilities=[
                "ContextForge Goal Harness worker boundary",
                "SkillFoundry verifier gate",
                "SkillFoundry registry gate",
            ],
            missing_capabilities=[],
            constraints=[
                "Use the approved solution plan and frozen acceptance criteria as builder inputs.",
                "Do not expose raw Front Desk conversation to builder or verifier prompts.",
            ],
            risks=list(plan.risks),
            assumptions=[
                "The solution plan was explicitly approved before audit execution.",
                "The draft spec and acceptance criteria are governed Front Desk artifacts.",
            ],
            human_review_reasons=[],
            report_ref=FRONTDESK_FEASIBILITY_REPORT_REF,
        )
        audit = SpecAuditReport(
            decision="approved",
            clarity_score=0.86,
            feasibility_score=feasibility.feasibility_score,
            testability_score=0.84,
            risk_score=feasibility.risk_score,
            missing_requirements=[],
            unsafe_assumptions=[],
            required_followup_questions=[],
            spec_patch_suggestions=[
                "Keep raw Front Desk conversation outside builder-visible context.",
                "Preserve verifier and registry gates before promotion.",
            ],
            routing_recommendation="codex_worker",
            approval_rationale=(
                "The approved plan, draft spec, and acceptance criteria are clear, feasible, and testable "
                "for a governed SkillFoundry build."
            ),
            elicitation_report_ref=self.audit_elicitation_report_ref,
            feasibility_report_ref=FRONTDESK_FEASIBILITY_REPORT_REF,
        )
        write_frontdesk_artifact(self.frontdesk, FRONTDESK_FEASIBILITY_REPORT_REF, feasibility)
        write_frontdesk_artifact(self.frontdesk, self.audit_report_ref, audit)
        return _frontdesk_worker_result(
            request,
            worker_name=self.name,
            status="completed",
            final_output_ref=self.audit_report_ref,
            summary="Front Desk Spec Auditor worker wrote governed audit artifacts.",
            failure_class=None,
            artifact_refs=success_files,
            changed_files=success_files,
            attempted_changed_files=attempted_changed_files,
            model_name="frontdesk_spec_auditor_deterministic_fixture",
            metadata={
                "frontdesk_spec_auditor_fake_worker": True,
                "draft_spec_bytes": len(draft_spec.encode("utf-8")),
                "acceptance_criteria_bytes": len(acceptance_criteria.encode("utf-8")),
            },
        )

    def _fail_closed(
        self,
        request: WorkerRunRequest,
        *,
        failure_class: str,
        message: str,
        attempted_changed_files: list[str],
        details: dict[str, JsonValue],
    ) -> WorkerRunResult:
        payload = {
            "schema_version": "skillfoundry.spec_audit_failure.v1",
            "status": "fail_closed",
            "failure_class": failure_class,
            "message": message,
            "expected_refs": {
                "solution_plan": FRONTDESK_SOLUTION_PLAN_REF,
                "plan_review": self.plan_review_ref,
                "draft_skill_spec": FRONTDESK_DRAFT_SKILL_SPEC_REF,
                "acceptance_criteria": FRONTDESK_ACCEPTANCE_CRITERIA_REF,
                "spec_audit_report": self.audit_report_ref,
                "feasibility_report": FRONTDESK_FEASIBILITY_REPORT_REF,
            },
            "raw_conversation_included": False,
            "details": details,
        }
        write_frontdesk_artifact(self.frontdesk, FRONTDESK_SPEC_AUDIT_FAILURE_REF, payload)
        return _frontdesk_worker_result(
            request,
            worker_name=self.name,
            status="failed",
            final_output_ref=FRONTDESK_SPEC_AUDIT_FAILURE_REF,
            summary=message,
            failure_class=failure_class,
            artifact_refs=[FRONTDESK_SPEC_AUDIT_FAILURE_REF],
            changed_files=[FRONTDESK_SPEC_AUDIT_FAILURE_REF],
            attempted_changed_files=attempted_changed_files,
            model_name="frontdesk_spec_auditor_deterministic_fixture",
            metadata={"frontdesk_spec_auditor_fake_worker": True, **details},
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
        _seed_frontdesk_context(
            frontdesk,
            ledger,
            run_id=resolved_run_id,
            task_id=CORE_NEED_DISCOVERY_NODE_ID,
            node_id=CORE_NEED_DISCOVERY_NODE_ID,
            created_at=timestamp,
            legacy_item_ids=True,
        )
        harness_result = GoalHarness(ContextKernel(ledger)).run_single_node(
            goal_contract,
            node_contract,
            FrontDeskCoreNeedFakeWorker(frontdesk),
            graph_id=_GRAPH_ID,
            run_id=resolved_run_id,
            task_id=CORE_NEED_DISCOVERY_NODE_ID,
            created_at=timestamp,
            metadata={
                "skillfoundry_job_id": frontdesk.job_id,
                "frontdesk_stage": CORE_NEED_DISCOVERY_NODE_ID,
                "frontdesk_v2": FRONTDESK_V2_SCHEMA_VERSION,
                "frontdesk_goal_runtime": FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION,
            },
            checkpoint_reason="phase_complete",
            checkpoint_best_result="Core Need Discovery completed through Front Desk Goal Harness boundary.",
            checkpoint_latest_diagnosis="Governed context was compiled and raw conversation remained forbidden.",
            checkpoint_next_plan="Route governed core-need brief to solution planning.",
        )
        goal_run = harness_result.goal_run
        runtime_state = _runtime_state(
            frontdesk,
            harness_result,
            goal_run,
            stage=CORE_NEED_DISCOVERY_NODE_ID,
            runtime_result_ref=FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF,
            output_refs={
                "core_need_brief": FRONTDESK_CORE_NEED_BRIEF_REF,
                "core_need_report": FRONTDESK_CORE_NEED_REPORT_REF,
            },
        )
        runtime_result = _runtime_result(
            frontdesk,
            harness_result,
            goal_run,
            runtime_state,
            runtime_state_ref=FRONTDESK_CORE_NEED_RUNTIME_STATE_REF,
            output_refs={
                "core_need_brief": FRONTDESK_CORE_NEED_BRIEF_REF,
                "core_need_report": FRONTDESK_CORE_NEED_REPORT_REF,
            },
            hash_refs={
                "core_need_brief": FRONTDESK_CORE_NEED_BRIEF_REF,
                "core_need_report": FRONTDESK_CORE_NEED_REPORT_REF,
            },
            created_at=timestamp,
        )
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


def run_frontdesk_solution_planner_goal_harness(
    workspace: FrontDeskWorkspace | JobWorkspace,
    *,
    run_id: str | None = None,
    created_at: str | None = None,
) -> FrontDeskSolutionPlannerGoalHarnessResult:
    """Run Front Desk Solution Planner as a ContextForge Goal Harness node."""

    frontdesk = _coerce_frontdesk(workspace)
    frontdesk.workspace.check_locked_inputs()
    timestamp = created_at or utc_now()
    resolved_run_id = run_id or f"{frontdesk.job_id}-frontdesk-solution-planner-run"
    artifacts = write_frontdesk_v2_contract_artifacts(frontdesk, created_at=timestamp)
    goal_contract = _load_json_contract(frontdesk, artifacts.goal_contract_ref)
    node_contract = _load_json_contract(frontdesk, artifacts.node_contract_refs[SOLUTION_PLANNER_NODE_ID])
    ledger = ContextLedger.connect(frontdesk.workspace.resolve_path(FRONTDESK_GOAL_RUNTIME_LEDGER_REF))
    ledger.initialize()
    try:
        _seed_frontdesk_context(
            frontdesk,
            ledger,
            run_id=resolved_run_id,
            task_id=SOLUTION_PLANNER_NODE_ID,
            node_id=SOLUTION_PLANNER_NODE_ID,
            created_at=timestamp,
            include_core_need=True,
        )
        harness_result = GoalHarness(ContextKernel(ledger)).run_single_node(
            goal_contract,
            node_contract,
            FrontDeskSolutionPlannerFakeWorker(frontdesk),
            graph_id=_GRAPH_ID,
            run_id=resolved_run_id,
            task_id=SOLUTION_PLANNER_NODE_ID,
            created_at=timestamp,
            metadata={
                "skillfoundry_job_id": frontdesk.job_id,
                "frontdesk_stage": SOLUTION_PLANNER_NODE_ID,
                "frontdesk_v2": FRONTDESK_V2_SCHEMA_VERSION,
                "frontdesk_goal_runtime": FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION,
            },
            checkpoint_reason="phase_complete",
            checkpoint_best_result="Solution Planner completed through Front Desk Goal Harness boundary.",
            checkpoint_latest_diagnosis="Governed plan artifacts were written and raw conversation remained forbidden.",
            checkpoint_next_plan="Wait for user review before freeze or route an approved plan to Spec Auditor.",
        )
        goal_run = harness_result.goal_run
        output_refs = {
            "core_need_brief": FRONTDESK_CORE_NEED_BRIEF_REF,
            "solution_plan": FRONTDESK_SOLUTION_PLAN_REF,
            "solution_plan_markdown": FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF,
            "draft_skill_spec": FRONTDESK_DRAFT_SKILL_SPEC_REF,
            "acceptance_criteria": FRONTDESK_ACCEPTANCE_CRITERIA_REF,
        }
        runtime_state = _runtime_state(
            frontdesk,
            harness_result,
            goal_run,
            stage=SOLUTION_PLANNER_NODE_ID,
            runtime_result_ref=FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF,
            output_refs=output_refs,
        )
        runtime_result = _runtime_result(
            frontdesk,
            harness_result,
            goal_run,
            runtime_state,
            runtime_state_ref=FRONTDESK_SOLUTION_PLAN_RUNTIME_STATE_REF,
            output_refs=output_refs,
            hash_refs=output_refs,
            created_at=timestamp,
        )
        _write_json(frontdesk.workspace, FRONTDESK_SOLUTION_PLAN_RUNTIME_STATE_REF, runtime_state)
        _write_json(frontdesk.workspace, FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF, runtime_result)
        return FrontDeskSolutionPlannerGoalHarnessResult(
            harness_result=harness_result,
            goal_run=goal_run,
            runtime_result=runtime_result,
            runtime_state=runtime_state,
            ledger_ref=FRONTDESK_GOAL_RUNTIME_LEDGER_REF,
            runtime_result_ref=FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF,
            runtime_state_ref=FRONTDESK_SOLUTION_PLAN_RUNTIME_STATE_REF,
        )
    finally:
        ledger.close()


def run_frontdesk_spec_auditor_goal_harness(
    workspace: FrontDeskWorkspace | JobWorkspace,
    *,
    run_id: str | None = None,
    plan_review_ref: str = FRONTDESK_PLAN_REVIEW_REF,
    audit_report_ref: str = FRONTDESK_SPEC_AUDIT_REPORT_REF,
    audit_elicitation_report_ref: str = FRONTDESK_SOLUTION_PLAN_REF,
    created_at: str | None = None,
) -> FrontDeskSpecAuditorGoalHarnessResult:
    """Run Front Desk Spec Auditor as a ContextForge Goal Harness node."""

    frontdesk = _coerce_frontdesk(workspace)
    frontdesk.workspace.check_locked_inputs()
    timestamp = created_at or utc_now()
    resolved_run_id = run_id or f"{frontdesk.job_id}-frontdesk-spec-auditor-run"
    artifacts = write_frontdesk_v2_contract_artifacts(frontdesk, created_at=timestamp)
    goal_contract = _load_json_contract(frontdesk, artifacts.goal_contract_ref)
    node_contract = _load_json_contract(frontdesk, artifacts.node_contract_refs[SPEC_AUDITOR_NODE_ID])
    ledger = ContextLedger.connect(frontdesk.workspace.resolve_path(FRONTDESK_GOAL_RUNTIME_LEDGER_REF))
    ledger.initialize()
    try:
        _seed_frontdesk_context(
            frontdesk,
            ledger,
            run_id=resolved_run_id,
            task_id=SPEC_AUDITOR_NODE_ID,
            node_id=SPEC_AUDITOR_NODE_ID,
            created_at=timestamp,
            include_core_need=True,
            include_solution_plan=True,
            include_plan_review=True,
            plan_review_ref=plan_review_ref,
            include_draft_outputs=True,
        )
        harness_result = GoalHarness(ContextKernel(ledger)).run_single_node(
            goal_contract,
            node_contract,
            FrontDeskSpecAuditorFakeWorker(
                frontdesk,
                plan_review_ref=plan_review_ref,
                audit_report_ref=audit_report_ref,
                audit_elicitation_report_ref=audit_elicitation_report_ref,
            ),
            graph_id=_GRAPH_ID,
            run_id=resolved_run_id,
            task_id=SPEC_AUDITOR_NODE_ID,
            created_at=timestamp,
            metadata={
                "skillfoundry_job_id": frontdesk.job_id,
                "frontdesk_stage": SPEC_AUDITOR_NODE_ID,
                "frontdesk_v2": FRONTDESK_V2_SCHEMA_VERSION,
                "frontdesk_goal_runtime": FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION,
            },
            checkpoint_reason="phase_complete",
            checkpoint_best_result="Spec Auditor completed through Front Desk Goal Harness boundary.",
            checkpoint_latest_diagnosis="Governed audit artifacts were written or failed closed before freeze.",
            checkpoint_next_plan="Use audit and feasibility evidence as Front Desk freeze inputs after approval checks.",
        )
        goal_run = harness_result.goal_run
        output_refs = {
            "core_need_brief": FRONTDESK_CORE_NEED_BRIEF_REF,
            "solution_plan": FRONTDESK_SOLUTION_PLAN_REF,
            "plan_review": plan_review_ref,
            "draft_skill_spec": FRONTDESK_DRAFT_SKILL_SPEC_REF,
            "acceptance_criteria": FRONTDESK_ACCEPTANCE_CRITERIA_REF,
        }
        if harness_result.worker_run.status == "completed":
            output_refs.update(
                {
                    "spec_audit_report": audit_report_ref,
                    "feasibility_report": FRONTDESK_FEASIBILITY_REPORT_REF,
                }
            )
        else:
            output_refs["spec_audit_failure"] = FRONTDESK_SPEC_AUDIT_FAILURE_REF
        runtime_state = _runtime_state(
            frontdesk,
            harness_result,
            goal_run,
            stage=SPEC_AUDITOR_NODE_ID,
            runtime_result_ref=FRONTDESK_SPEC_AUDIT_RUNTIME_RESULT_REF,
            output_refs=output_refs,
        )
        runtime_result = _runtime_result(
            frontdesk,
            harness_result,
            goal_run,
            runtime_state,
            runtime_state_ref=FRONTDESK_SPEC_AUDIT_RUNTIME_STATE_REF,
            output_refs=output_refs,
            hash_refs=output_refs,
            created_at=timestamp,
        )
        _write_json(frontdesk.workspace, FRONTDESK_SPEC_AUDIT_RUNTIME_STATE_REF, runtime_state)
        _write_json(frontdesk.workspace, FRONTDESK_SPEC_AUDIT_RUNTIME_RESULT_REF, runtime_result)
        return FrontDeskSpecAuditorGoalHarnessResult(
            harness_result=harness_result,
            goal_run=goal_run,
            runtime_result=runtime_result,
            runtime_state=runtime_state,
            ledger_ref=FRONTDESK_GOAL_RUNTIME_LEDGER_REF,
            runtime_result_ref=FRONTDESK_SPEC_AUDIT_RUNTIME_RESULT_REF,
            runtime_state_ref=FRONTDESK_SPEC_AUDIT_RUNTIME_STATE_REF,
        )
    finally:
        ledger.close()


def _seed_frontdesk_context(
    frontdesk: FrontDeskWorkspace,
    ledger: ContextLedger,
    *,
    run_id: str,
    task_id: str,
    node_id: str,
    created_at: str,
    include_core_need: bool = False,
    include_solution_plan: bool = False,
    include_plan_review: bool = False,
    plan_review_ref: str = FRONTDESK_PLAN_REVIEW_REF,
    include_draft_outputs: bool = False,
    legacy_item_ids: bool = False,
) -> list[str]:
    refs = [
        (FRONTDESK_CLARIFICATION_SUMMARY_REF, "artifact", "frontdesk_clarification_summary", ["governed_frontdesk"]),
        (FRONTDESK_RISK_REPORT_REF, "constraint", "frontdesk_risk_report", ["governed_frontdesk"]),
        (FRONTDESK_BUDGET_REF, "constraint", "frontdesk_budget", ["governed_frontdesk"]),
    ]
    if include_core_need:
        refs.append(
            (
                FRONTDESK_CORE_NEED_BRIEF_REF,
                "artifact",
                "frontdesk_core_need_brief",
                ["governed_frontdesk", "core_need_brief"],
            )
        )
    if include_solution_plan:
        refs.append(
            (
                FRONTDESK_SOLUTION_PLAN_REF,
                "artifact",
                "frontdesk_solution_plan",
                ["governed_frontdesk", "solution_plan"],
            )
        )
    if include_plan_review:
        refs.append(
            (
                plan_review_ref,
                "artifact",
                "frontdesk_plan_review",
                ["governed_frontdesk", "plan_review"],
            )
        )
    if include_draft_outputs:
        refs.extend(
            [
                (
                    FRONTDESK_DRAFT_SKILL_SPEC_REF,
                    "artifact",
                    "frontdesk_draft_skill_spec",
                    ["governed_frontdesk", "draft_skill_spec"],
                ),
                (
                    FRONTDESK_ACCEPTANCE_CRITERIA_REF,
                    "artifact",
                    "frontdesk_acceptance_criteria",
                    ["governed_frontdesk", "acceptance_criteria"],
                ),
            ]
        )
    refs.append(
        (
            FRONTDESK_CONVERSATION_REF,
            "user_message",
            "raw_frontdesk_conversation",
            ["raw_frontdesk_conversation"],
        ),
    )
    recorded: list[str] = []
    for ref, item_type, context_type, tags in refs:
        try:
            content = frontdesk.workspace.resolve_path(ref, must_exist=True).read_text(encoding="utf-8")
        except Exception:
            if ref == FRONTDESK_CONVERSATION_REF:
                content = ""
            else:
                continue
        item_id = (
            f"{frontdesk.job_id}:{context_type}"
            if legacy_item_ids
            else f"{frontdesk.job_id}:{node_id}:{context_type}"
        )
        ledger.record_context_item(
            ContextItem(
                id=item_id,
                graph_id=_GRAPH_ID,
                run_id=run_id,
                task_id=task_id,
                node_id=node_id,
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
    model_name: str,
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
            "model": model_name,
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
    *,
    stage: str,
    runtime_result_ref: str,
    output_refs: dict[str, str],
) -> dict[str, JsonValue]:
    payload = {
        "schema_version": FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION,
        "job_id": frontdesk.job_id,
        "stage": stage,
        "status": goal_run.status,
        "refs": {
            "ledger": FRONTDESK_GOAL_RUNTIME_LEDGER_REF,
            "runtime_result": runtime_result_ref,
            **output_refs,
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
    runtime_state_ref: str,
    output_refs: dict[str, str],
    hash_refs: dict[str, str],
    created_at: str,
) -> dict[str, JsonValue]:
    payload = {
        "schema_version": FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION,
        "job_id": frontdesk.job_id,
        "created_at": created_at,
        "refs": {
            "ledger": FRONTDESK_GOAL_RUNTIME_LEDGER_REF,
            "runtime_state": runtime_state_ref,
            **output_refs,
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
            **_ref_hashes(
                frontdesk,
                hash_refs,
                require_all=harness_result.worker_run.status == "completed",
            ),
        },
        "trust_boundaries": {
            "worker_self_report_is_not_acceptance": True,
            "raw_conversation_included": False,
        },
    }
    return ensure_json_compatible(payload)  # type: ignore[return-value]


def _ref_hashes(frontdesk: FrontDeskWorkspace, refs: dict[str, str], *, require_all: bool) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name, ref in refs.items():
        try:
            path = frontdesk.workspace.resolve_path(ref, must_exist=True)
        except Exception:
            if require_all:
                raise
            continue
        if path.is_file():
            hashes[name] = sha256_file(path)
        elif require_all:
            raise ValueError(f"frontdesk runtime hash target is not a file: {ref}")
    return hashes


def _plan_review_failure(
    frontdesk: FrontDeskWorkspace,
    plan_review: PlanReviewRecord,
    *,
    plan_review_ref: str,
) -> tuple[str, str, dict[str, JsonValue]] | None:
    if plan_review.solution_plan_ref != FRONTDESK_SOLUTION_PLAN_REF:
        return (
            "plan_review_solution_plan_ref_mismatch",
            "Plan review record must reference the canonical solution plan artifact.",
            {
                "solution_plan_ref": plan_review.solution_plan_ref,
                "expected_solution_plan_ref": FRONTDESK_SOLUTION_PLAN_REF,
            },
        )
    if plan_review.decision != "approve":
        return (
            "plan_review_not_approved",
            "Spec Auditor requires an approved plan review record before audit.",
            {"plan_review_decision": plan_review.decision},
        )
    if plan_review.source_hash is None:
        return (
            "plan_review_source_hash_missing",
            "Plan review record must include the reviewed solution_plan.json hash.",
            {"plan_review_ref": plan_review_ref},
        )
    actual_hash = sha256_file(frontdesk.workspace.resolve_path(FRONTDESK_SOLUTION_PLAN_REF, must_exist=True))
    if actual_hash != plan_review.source_hash:
        return (
            "plan_review_source_hash_mismatch",
            "Plan review source_hash must match the current solution_plan.json.",
            {
                "plan_review_source_hash": plan_review.source_hash,
                "actual_solution_plan_hash": actual_hash,
                "plan_review_ref": plan_review_ref,
            },
        )
    return None


def _draft_skill_spec_from_core_need(brief: CoreNeedBrief) -> SkillSpec:
    return SkillSpec(
        skill_id="frontdesk-governed-skill",
        title="Governed Requirement Skill",
        description=brief.problem_statement,
        trigger_scenarios=[brief.usage_moment],
        non_trigger_scenarios=list(brief.non_goals)
        or ["Do not run before the solution plan and acceptance criteria are approved."],
        required_inputs=["Approved solution plan", "Frozen acceptance criteria"],
        expected_outputs=[brief.desired_outcome],
        constraints=[
            "Use only frozen Front Desk artifacts as builder inputs.",
            "Do not read raw Front Desk conversation during build.",
        ],
        acceptance_criteria=[brief.success_signal],
        reference_materials=[FRONTDESK_CORE_NEED_BRIEF_REF, FRONTDESK_SOLUTION_PLAN_REF],
        security_notes=["Raw conversation is forbidden provenance only."],
    )


def _acceptance_criteria_from_core_need(frontdesk: FrontDeskWorkspace, brief: CoreNeedBrief) -> AcceptanceCriteriaSet:
    return AcceptanceCriteriaSet(
        criteria=[
            AcceptanceCriterion(
                id="AC-001",
                description=brief.success_signal,
                source_requirement=brief.problem_statement,
                requirement_id="REQ-001",
                test_method="static",
                pass_condition="Verifier evidence confirms the generated skill satisfies the approved core need.",
                required_evidence=["verification_result.json", "acceptance coverage report"],
                evidence_kind="verifier_check",
                coverage_status="planned",
            ),
            AcceptanceCriterion(
                id="AC-002",
                description="Builder context must be based on frozen governed artifacts, not raw Front Desk conversation.",
                source_requirement="Raw Front Desk conversation is provenance only.",
                requirement_id="REQ-002",
                test_method="static",
                pass_condition="ContextForge evidence shows raw conversation was excluded from builder-visible context.",
                required_evidence=["ContextForge ContextView", "ContextForge PromptView"],
                evidence_kind="verifier_check",
                coverage_status="planned",
            ),
        ],
        job_id=frontdesk.job_id,
    )


def _solution_plan_markdown(plan: SolutionPlan, brief: CoreNeedBrief) -> str:
    sections = [
        "# Solution Plan",
        "",
        "## Core Problem",
        brief.problem_statement,
        "",
        "## Recommended Skill",
        plan.proposed_skill_name,
        "",
        "## Target User",
        plan.target_user,
        "",
        "## Desired Outcome",
        plan.desired_outcome,
        "",
        "## Approach",
        plan.approach,
        "",
        "## Implementation Outline",
        *[f"- {item}" for item in plan.implementation_outline],
        "",
        "## Acceptance Summary",
        *[f"- {item}" for item in plan.acceptance_summary],
        "",
        "## Review Status",
        plan.status,
    ]
    return "\n".join(sections).rstrip() + "\n"


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
    "FRONTDESK_ACCEPTANCE_CRITERIA_REF",
    "FRONTDESK_CORE_NEED_BRIEF_REF",
    "FRONTDESK_CORE_NEED_REPORT_REF",
    "FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF",
    "FRONTDESK_CORE_NEED_RUNTIME_STATE_REF",
    "FRONTDESK_DRAFT_SKILL_SPEC_REF",
    "FRONTDESK_FEASIBILITY_REPORT_REF",
    "FRONTDESK_GOAL_RUNTIME_LEDGER_REF",
    "FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION",
    "FRONTDESK_PLAN_REVIEW_REF",
    "FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF",
    "FRONTDESK_SOLUTION_PLAN_REF",
    "FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF",
    "FRONTDESK_SOLUTION_PLAN_RUNTIME_STATE_REF",
    "FRONTDESK_SPEC_AUDIT_FAILURE_REF",
    "FRONTDESK_SPEC_AUDIT_REPORT_REF",
    "FRONTDESK_SPEC_AUDIT_RUNTIME_RESULT_REF",
    "FRONTDESK_SPEC_AUDIT_RUNTIME_STATE_REF",
    "FrontDeskCoreNeedFakeWorker",
    "FrontDeskCoreNeedGoalHarnessResult",
    "FrontDeskSolutionPlannerFakeWorker",
    "FrontDeskSolutionPlannerGoalHarnessResult",
    "FrontDeskSpecAuditorFakeWorker",
    "FrontDeskSpecAuditorGoalHarnessResult",
    "run_frontdesk_core_need_goal_harness",
    "run_frontdesk_solution_planner_goal_harness",
    "run_frontdesk_spec_auditor_goal_harness",
]
