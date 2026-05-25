"""Deterministic Front Desk loop orchestration.

This module intentionally keeps loop state refs-only. The existing elicitor and
auditor may write ContextForge replay artifacts, but this loop never stores raw
conversation text, prompts, or model payloads in ``FrontDeskState``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping

from .frontdesk import (
    ELICITATION_STATUS_FAIL_CLOSED,
    ELICITATION_REPORT_REF_TEMPLATE,
    FEASIBILITY_REPORT_REF,
    FREEZE_GATE_DECISION_ASK_USER,
    FREEZE_GATE_DECISION_FREEZE,
    FREEZE_GATE_DECISION_HUMAN_REVIEW_REQUIRED,
    FREEZE_GATE_DECISION_REJECT,
    FRONTDESK_ACCEPTANCE_CRITERIA_REF,
    FRONTDESK_CORE_NEED_BRIEF_REF,
    FRONTDESK_DRAFT_SKILL_SPEC_REF,
    FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF,
    FRONTDESK_SOLUTION_PLAN_REF,
    FREEZE_MANIFEST_REF,
    PLAN_REVIEW_REF_TEMPLATE,
    ROOT_ACCEPTANCE_CRITERIA_REF,
    ROOT_SKILL_SPEC_REF,
    ROOT_VERIFICATION_SPEC_REF,
    SPEC_AUDIT_REPORT_REF_TEMPLATE,
    SPEC_AUDIT_STATUS_FAIL_CLOSED,
    FrontDeskFreezeGate,
    RequirementsElicitor,
    SpecAuditor,
    _normalize_acceptance_criterion_payload,
    _normalize_skill_spec_payload,
)
from .frontdesk_goal_runtime import (
    FRONTDESK_CORE_NEED_REPORT_REF as FRONTDESK_GOAL_CORE_NEED_REPORT_REF,
    FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF,
    FRONTDESK_CORE_NEED_RUNTIME_STATE_REF,
    FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF,
    FRONTDESK_SOLUTION_PLAN_RUNTIME_STATE_REF,
    run_frontdesk_core_need_goal_harness,
    run_frontdesk_solution_planner_goal_harness,
    run_frontdesk_spec_auditor_goal_harness,
)
from .frontdesk_schema import (
    AcceptanceCriteriaSet,
    CoreNeedBrief,
    CoreNeedDiscoveryReport,
    ElicitationReport,
    FeasibilityReport,
    FrontDeskConfig,
    FrontDeskState,
    PlanReviewRecord,
    SpecAuditReport,
    SolutionPlan,
)
from .frontdesk_workspace import (
    FRONTDESK_BUDGET_REF,
    FrontDeskWorkspace,
    write_acceptance_criteria,
    write_frontdesk_artifact,
)
from .schema import JsonValue, SchemaValidationError, SkillSpec, ensure_json_compatible, sha256_file, utc_now
from .workspace import JobWorkspace


FRONTDESK_LOOP_FAILURE_SCHEMA_VERSION = "skillfoundry.frontdesk_loop_failure.v1"
FRONTDESK_LOOP_FAILURE_REF_TEMPLATE = "frontdesk/frontdesk_loop_failure_{sequence:03d}.json"

FRONTDESK_LOOP_STATUS_ASK_USER = "ask_user"
FRONTDESK_LOOP_STATUS_ROUTE_TO_BUILD = "route_to_build"
FRONTDESK_LOOP_STATUS_HUMAN_REVIEW = "human_review"
FRONTDESK_LOOP_STATUS_REJECT = "reject"
FRONTDESK_LOOP_STATUS_FAIL_CLOSED = "fail_closed"
FRONTDESK_LOOP_STATUS_RETRY_ELICIT = "retry_elicit"
FRONTDESK_LOOP_STATUS_AWAIT_PLAN_REVIEW = "await_user_plan_review"

_TERMINAL_READINESS = frozenset({"frozen", "human_review_required", "rejected", "failed"})
FRONTDESK_CORE_NEED_REPORT_REF_TEMPLATE = "frontdesk/core_need_report_{sequence:03d}.json"
FRONTDESK_DECISION_LEDGER_REF = "frontdesk/decision_ledger.json"


@dataclass(frozen=True)
class FrontDeskLoopResult:
    """Refs-only result for one Front Desk loop round."""

    state: FrontDeskState
    round_index: int
    status: str
    materialized_artifact_refs: dict[str, str] = field(default_factory=dict)
    frozen_artifact_refs: dict[str, str] = field(default_factory=dict)
    elicitation_report_ref: str | None = None
    audit_report_ref: str | None = None
    feasibility_report_ref: str | None = None
    freeze_gate_result_ref: str | None = None
    freeze_manifest_ref: str | None = None
    failure_ref: str | None = None

    @property
    def next_action(self) -> str:
        return self.state.next_action

    @property
    def frozen(self) -> bool:
        return self.state.readiness == "frozen"

    @property
    def failed_closed(self) -> bool:
        return self.state.next_action == "fail_closed"

    @property
    def human_review_required(self) -> bool:
        return self.state.human_review_required

    def to_dict(self) -> dict[str, JsonValue]:
        return ensure_json_compatible(
            {
                "state": self.state.to_dict(),
                "round_index": self.round_index,
                "status": self.status,
                "materialized_artifact_refs": dict(self.materialized_artifact_refs),
                "frozen_artifact_refs": dict(self.frozen_artifact_refs),
                "elicitation_report_ref": self.elicitation_report_ref,
                "audit_report_ref": self.audit_report_ref,
                "feasibility_report_ref": self.feasibility_report_ref,
                "freeze_gate_result_ref": self.freeze_gate_result_ref,
                "freeze_manifest_ref": self.freeze_manifest_ref,
                "failure_ref": self.failure_ref,
            }
        )  # type: ignore[return-value]


class FrontDeskLoop:
    """Run one deterministic Front Desk round around WP13-WP15 components."""

    def __init__(
        self,
        *,
        config: FrontDeskConfig | None = None,
        elicitor: RequirementsElicitor | None = None,
        auditor: SpecAuditor | None = None,
        freeze_gate: FrontDeskFreezeGate | None = None,
    ) -> None:
        if config is not None:
            config.validate()
        self.config = config
        self.elicitor = elicitor or RequirementsElicitor()
        self.auditor = auditor or SpecAuditor()
        self.freeze_gate = freeze_gate or FrontDeskFreezeGate()

    def run_round(
        self,
        workspace: FrontDeskWorkspace | JobWorkspace,
        *,
        state: FrontDeskState | Mapping[str, Any] | None = None,
        elicitor_client: Any | None = None,
        auditor_client: Any | None = None,
        elicitor_model_params: Mapping[str, Any] | None = None,
        auditor_model_params: Mapping[str, Any] | None = None,
        elicitor_provider: str = "fake",
        auditor_provider: str = "fake",
        elicitor_model: str = "skillfoundry-requirements-elicitor-fake",
        auditor_model: str = "skillfoundry-spec-auditor-fake",
    ) -> FrontDeskLoopResult:
        """Run one Front Desk round and return refs-only state.

        The loop always uses the fake provider boundary. Tests should pass
        scripted clients; without a client the existing deterministic fake model
        is used and will fail closed if its response is not valid Front Desk
        JSON.
        """

        frontdesk = _as_frontdesk_workspace(workspace)
        current_state = _coerce_state(state, job_id=frontdesk.job_id)
        config = _load_config(frontdesk, self.config)

        if current_state.readiness in _TERMINAL_READINESS:
            return _result_from_terminal_state(current_state)

        if current_state.next_action == "plan_solution":
            current_state = _copy_state_for_next_planning_round(current_state)
        elif current_state.readiness == "plan_approved" or current_state.next_action == "freeze_approved_plan":
            return self._audit_and_freeze_approved_plan(
                frontdesk,
                state=current_state,
                config=config,
                auditor_client=auditor_client,
                auditor_model_params=auditor_model_params,
                auditor_provider=auditor_provider,
                auditor_model=auditor_model,
            )

        if current_state.clarification_round >= config.max_clarification_rounds:
            next_state = _human_review_state(
                current_state,
                stage="human_review",
                clarification_round=current_state.clarification_round,
            )
            failure_ref = _write_loop_failure(
                frontdesk,
                round_index=max(1, current_state.clarification_round),
                failure_type="max_clarification_rounds_reached",
                message="max_clarification_rounds reached before starting another front desk model loop",
                details={
                    "clarification_round": current_state.clarification_round,
                    "max_clarification_rounds": config.max_clarification_rounds,
                },
                artifact_refs=_artifact_refs_from_state(current_state),
            )
            return FrontDeskLoopResult(
                state=next_state,
                round_index=max(1, current_state.clarification_round),
                status=FRONTDESK_LOOP_STATUS_HUMAN_REVIEW,
                elicitation_report_ref=next_state.latest_elicitation_report_ref,
                audit_report_ref=next_state.latest_audit_report_ref,
                freeze_gate_result_ref=next_state.freeze_gate_result_ref,
                freeze_manifest_ref=next_state.freeze_manifest_ref,
                failure_ref=failure_ref,
            )

        round_index = current_state.clarification_round + 1
        if _use_goal_harness_planning(self.elicitor, elicitor_client):
            return self._plan_with_goal_harness(
                frontdesk,
                state=current_state,
                config=config,
                round_index=round_index,
            )

        try:
            elicitation = self.elicitor.elicit(
                frontdesk,
                round_index=round_index,
                client=elicitor_client,
                config=config,
                provider=elicitor_provider,
                model=elicitor_model,
                model_params=elicitor_model_params,
            )
        except Exception as exc:
            failure_ref = _write_loop_failure(
                frontdesk,
                round_index=round_index,
                failure_type="elicitor_exception",
                message=str(exc),
                details={"exception_type": type(exc).__name__},
                artifact_refs=_artifact_refs_from_state(current_state),
            )
            failed_state = _failed_state(
                current_state,
                clarification_round=round_index,
                latest_elicitation_report_ref=current_state.latest_elicitation_report_ref,
                latest_audit_report_ref=current_state.latest_audit_report_ref,
            )
            return _failure_result(failed_state, round_index=round_index, failure_ref=failure_ref)

        if elicitation.status == ELICITATION_STATUS_FAIL_CLOSED:
            if _is_transient_model_failure(elicitation.failure):
                retry_state = _retry_elicit_state(current_state)
                return FrontDeskLoopResult(
                    state=retry_state,
                    round_index=round_index,
                    status=FRONTDESK_LOOP_STATUS_RETRY_ELICIT,
                    elicitation_report_ref=current_state.latest_elicitation_report_ref,
                    audit_report_ref=current_state.latest_audit_report_ref,
                    freeze_gate_result_ref=current_state.freeze_gate_result_ref,
                    freeze_manifest_ref=current_state.freeze_manifest_ref,
                    failure_ref=elicitation.failure_ref,
                )
            failed_state = _failed_state(
                current_state,
                clarification_round=round_index,
                latest_elicitation_report_ref=current_state.latest_elicitation_report_ref,
                latest_audit_report_ref=current_state.latest_audit_report_ref,
            )
            return _failure_result(
                failed_state,
                round_index=round_index,
                failure_ref=elicitation.failure_ref,
            )

        if elicitation.report is None or elicitation.report_ref is None:
            failure_ref = _write_loop_failure(
                frontdesk,
                round_index=round_index,
                failure_type="invalid_elicitation_result",
                message="elicitor returned success without a report and report_ref",
                artifact_refs=_artifact_refs_from_state(current_state),
            )
            failed_state = _failed_state(
                current_state,
                clarification_round=round_index,
                latest_elicitation_report_ref=current_state.latest_elicitation_report_ref,
                latest_audit_report_ref=current_state.latest_audit_report_ref,
            )
            return _failure_result(failed_state, round_index=round_index, failure_ref=failure_ref)

        materialized = _materialize_elicitation_drafts(
            frontdesk,
            report=elicitation.report,
            round_index=round_index,
        )
        if materialized.failure_ref is not None:
            failed_state = _failed_state(
                current_state,
                clarification_round=round_index,
                latest_elicitation_report_ref=elicitation.report_ref,
                latest_audit_report_ref=current_state.latest_audit_report_ref,
            )
            return FrontDeskLoopResult(
                state=failed_state,
                round_index=round_index,
                status=FRONTDESK_LOOP_STATUS_FAIL_CLOSED,
                materialized_artifact_refs=materialized.artifact_refs,
                elicitation_report_ref=elicitation.report_ref,
                audit_report_ref=current_state.latest_audit_report_ref,
                failure_ref=materialized.failure_ref,
            )

        if elicitation.report.readiness_guess == "needs_clarification":
            if round_index >= min(config.max_clarification_rounds, config.max_core_need_rounds):
                next_state = _human_review_state(
                    current_state,
                    stage="human_review",
                    clarification_round=round_index,
                    latest_elicitation_report_ref=elicitation.report_ref,
                    latest_audit_report_ref=current_state.latest_audit_report_ref,
                )
                return FrontDeskLoopResult(
                    state=next_state,
                    round_index=round_index,
                    status=FRONTDESK_LOOP_STATUS_HUMAN_REVIEW,
                    materialized_artifact_refs=materialized.artifact_refs,
                    elicitation_report_ref=elicitation.report_ref,
                    audit_report_ref=current_state.latest_audit_report_ref,
                )
            next_state = FrontDeskState(
                job_id=frontdesk.job_id,
                stage="ask_user",
                frontdesk_phase="core_need_discovery",
                clarification_round=round_index,
                core_need_round=round_index,
                plan_revision_count=current_state.plan_revision_count,
                readiness="needs_clarification",
                latest_core_need_report_ref=current_state.latest_core_need_report_ref,
                core_need_brief_ref=current_state.core_need_brief_ref,
                decision_ledger_ref=current_state.decision_ledger_ref,
                solution_plan_ref=current_state.solution_plan_ref,
                solution_plan_markdown_ref=current_state.solution_plan_markdown_ref,
                latest_plan_review_ref=current_state.latest_plan_review_ref,
                latest_elicitation_report_ref=elicitation.report_ref,
                latest_audit_report_ref=current_state.latest_audit_report_ref,
                next_action="ask_user",
                human_review_required=False,
                frontdesk_budget_ref=current_state.frontdesk_budget_ref,
                risk_report_ref=current_state.risk_report_ref,
                freeze_gate_result_ref=current_state.freeze_gate_result_ref,
                freeze_manifest_ref=current_state.freeze_manifest_ref,
                acceptance_coverage_plan_ref=current_state.acceptance_coverage_plan_ref,
            )
            next_state.validate()
            return FrontDeskLoopResult(
                state=next_state,
                round_index=round_index,
                status=FRONTDESK_LOOP_STATUS_ASK_USER,
                materialized_artifact_refs=materialized.artifact_refs,
                elicitation_report_ref=elicitation.report_ref,
                audit_report_ref=current_state.latest_audit_report_ref,
            )

        plan_materialized = _materialize_core_need_and_solution_plan(
            frontdesk,
            report=elicitation.report,
            round_index=round_index,
        )
        if plan_materialized.failure_ref is not None:
            failed_state = _failed_state(
                current_state,
                clarification_round=round_index,
                latest_elicitation_report_ref=elicitation.report_ref,
                latest_audit_report_ref=current_state.latest_audit_report_ref,
            )
            return FrontDeskLoopResult(
                state=failed_state,
                round_index=round_index,
                status=FRONTDESK_LOOP_STATUS_FAIL_CLOSED,
                materialized_artifact_refs={**materialized.artifact_refs, **plan_materialized.artifact_refs},
                elicitation_report_ref=elicitation.report_ref,
                audit_report_ref=current_state.latest_audit_report_ref,
                failure_ref=plan_materialized.failure_ref,
            )
        next_state = FrontDeskState(
            job_id=frontdesk.job_id,
            stage="await_user_plan_review",
            frontdesk_phase="user_review",
            clarification_round=round_index,
            core_need_round=min(round_index, config.max_core_need_rounds),
            plan_revision_count=current_state.plan_revision_count,
            readiness="awaiting_plan_review",
            latest_core_need_report_ref=plan_materialized.artifact_refs.get("core_need_report"),
            core_need_brief_ref=plan_materialized.artifact_refs.get("core_need_brief", FRONTDESK_CORE_NEED_BRIEF_REF),
            decision_ledger_ref=plan_materialized.artifact_refs.get("decision_ledger", FRONTDESK_DECISION_LEDGER_REF),
            solution_plan_ref=plan_materialized.artifact_refs.get("solution_plan", FRONTDESK_SOLUTION_PLAN_REF),
            solution_plan_markdown_ref=plan_materialized.artifact_refs.get(
                "solution_plan_markdown", FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF
            ),
            latest_plan_review_ref=current_state.latest_plan_review_ref,
            latest_elicitation_report_ref=elicitation.report_ref,
            latest_audit_report_ref=current_state.latest_audit_report_ref,
            next_action="await_user_plan_review",
            human_review_required=False,
            frontdesk_budget_ref=current_state.frontdesk_budget_ref,
            risk_report_ref=current_state.risk_report_ref,
            freeze_gate_result_ref=current_state.freeze_gate_result_ref,
            freeze_manifest_ref=current_state.freeze_manifest_ref,
            acceptance_coverage_plan_ref=current_state.acceptance_coverage_plan_ref,
        )
        next_state.validate()
        combined_refs = {**materialized.artifact_refs, **plan_materialized.artifact_refs}
        return FrontDeskLoopResult(
            state=next_state,
            round_index=round_index,
            status=FRONTDESK_LOOP_STATUS_AWAIT_PLAN_REVIEW,
            materialized_artifact_refs=combined_refs,
            elicitation_report_ref=elicitation.report_ref,
            audit_report_ref=current_state.latest_audit_report_ref,
        )

    def _plan_with_goal_harness(
        self,
        frontdesk: FrontDeskWorkspace,
        *,
        state: FrontDeskState,
        config: FrontDeskConfig,
        round_index: int,
    ) -> FrontDeskLoopResult:
        try:
            core_need = run_frontdesk_core_need_goal_harness(frontdesk)
        except Exception as exc:
            failure_ref = _write_loop_failure(
                frontdesk,
                round_index=round_index,
                failure_type="goal_harness_core_need_exception",
                message=str(exc),
                details={"exception_type": type(exc).__name__},
                artifact_refs=_artifact_refs_from_state(state),
            )
            failed_state = _failed_state(
                state,
                clarification_round=round_index,
                latest_elicitation_report_ref=state.latest_elicitation_report_ref,
                latest_audit_report_ref=state.latest_audit_report_ref,
            )
            return _failure_result(failed_state, round_index=round_index, failure_ref=failure_ref)
        if core_need.harness_result.worker_run.status != "completed":
            failure_ref = core_need.harness_result.worker_run.final_output_ref
            if failure_ref is None:
                failure_ref = _write_loop_failure(
                    frontdesk,
                    round_index=round_index,
                    failure_type="goal_harness_core_need_failed",
                    message="Front Desk Core Need Goal Harness worker did not complete.",
                    details={
                        "worker_status": core_need.harness_result.worker_run.status,
                        "failure_class": core_need.harness_result.worker_run.failure_class,
                    },
                    artifact_refs=_artifact_refs_from_state(state),
                )
            failed_state = _failed_state(
                state,
                clarification_round=round_index,
                latest_elicitation_report_ref=state.latest_elicitation_report_ref,
                latest_audit_report_ref=state.latest_audit_report_ref,
            )
            return _failure_result(
                failed_state,
                round_index=round_index,
                failure_ref=failure_ref,
            )

        try:
            solution_plan = run_frontdesk_solution_planner_goal_harness(frontdesk)
        except Exception as exc:
            failure_ref = _write_loop_failure(
                frontdesk,
                round_index=round_index,
                failure_type="goal_harness_solution_planner_exception",
                message=str(exc),
                details={"exception_type": type(exc).__name__},
                artifact_refs=_artifact_refs_from_state(state),
            )
            failed_state = _failed_state(
                state,
                clarification_round=round_index,
                latest_elicitation_report_ref=state.latest_elicitation_report_ref,
                latest_audit_report_ref=state.latest_audit_report_ref,
            )
            return _failure_result(failed_state, round_index=round_index, failure_ref=failure_ref)
        if solution_plan.harness_result.worker_run.status != "completed":
            failure_ref = solution_plan.harness_result.worker_run.final_output_ref
            if failure_ref is None:
                failure_ref = _write_loop_failure(
                    frontdesk,
                    round_index=round_index,
                    failure_type="goal_harness_solution_planner_failed",
                    message="Front Desk Solution Planner Goal Harness worker did not complete.",
                    details={
                        "worker_status": solution_plan.harness_result.worker_run.status,
                        "failure_class": solution_plan.harness_result.worker_run.failure_class,
                    },
                    artifact_refs={
                        **_artifact_refs_from_state(state),
                        "core_need_runtime_result": FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF,
                    },
                )
            failed_state = _failed_state(
                state,
                clarification_round=round_index,
                latest_elicitation_report_ref=state.latest_elicitation_report_ref,
                latest_audit_report_ref=state.latest_audit_report_ref,
            )
            return _failure_result(
                failed_state,
                round_index=round_index,
                failure_ref=failure_ref,
            )

        try:
            core_report = CoreNeedDiscoveryReport.read_json_file(
                frontdesk.workspace.resolve_path(FRONTDESK_GOAL_CORE_NEED_REPORT_REF, must_exist=True)
            )
            core_brief = CoreNeedBrief.read_json_file(
                frontdesk.workspace.resolve_path(FRONTDESK_CORE_NEED_BRIEF_REF, must_exist=True)
            )
            plan = SolutionPlan.read_json_file(
                frontdesk.workspace.resolve_path(FRONTDESK_SOLUTION_PLAN_REF, must_exist=True)
            )
            draft_skill_spec = SkillSpec.read_yaml_file(
                frontdesk.workspace.resolve_path(FRONTDESK_DRAFT_SKILL_SPEC_REF, must_exist=True)
            )
            acceptance_criteria = AcceptanceCriteriaSet.read_yaml_file(
                frontdesk.workspace.resolve_path(FRONTDESK_ACCEPTANCE_CRITERIA_REF, must_exist=True)
            )
            elicitation_report = _elicitation_report_from_goal_harness_plan(
                core_report=core_report,
                core_brief=core_brief,
                plan=plan,
                draft_skill_spec=draft_skill_spec,
                acceptance_criteria=acceptance_criteria,
                round_index=round_index,
            )
            elicitation_ref = ELICITATION_REPORT_REF_TEMPLATE.format(sequence=round_index)
            write_frontdesk_artifact(frontdesk, elicitation_ref, elicitation_report)
            _write_round_risk_report(
                frontdesk,
                round_index=round_index,
                elicitation_report=elicitation_report,
                audit_report=None,
                feasibility_report=None,
            )
        except Exception as exc:
            failure_ref = _write_loop_failure(
                frontdesk,
                round_index=round_index,
                failure_type="invalid_goal_harness_planning_result",
                message=str(exc),
                details={"exception_type": type(exc).__name__},
                artifact_refs={
                    **_artifact_refs_from_state(state),
                    "core_need_runtime_result": FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF,
                    "solution_plan_runtime_result": FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF,
                },
            )
            failed_state = _failed_state(
                state,
                clarification_round=round_index,
                latest_elicitation_report_ref=state.latest_elicitation_report_ref,
                latest_audit_report_ref=state.latest_audit_report_ref,
            )
            return _failure_result(failed_state, round_index=round_index, failure_ref=failure_ref)

        artifact_refs = {
            "core_need_runtime_result": FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF,
            "core_need_runtime_state": FRONTDESK_CORE_NEED_RUNTIME_STATE_REF,
            "solution_plan_runtime_result": FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF,
            "solution_plan_runtime_state": FRONTDESK_SOLUTION_PLAN_RUNTIME_STATE_REF,
            "core_need_report": FRONTDESK_GOAL_CORE_NEED_REPORT_REF,
            "core_need_brief": FRONTDESK_CORE_NEED_BRIEF_REF,
            "solution_plan": FRONTDESK_SOLUTION_PLAN_REF,
            "solution_plan_markdown": FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF,
            "draft_skill_spec": FRONTDESK_DRAFT_SKILL_SPEC_REF,
            "acceptance_criteria": FRONTDESK_ACCEPTANCE_CRITERIA_REF,
            "elicitation_report": elicitation_ref,
        }
        next_state = FrontDeskState(
            job_id=frontdesk.job_id,
            stage="await_user_plan_review",
            frontdesk_phase="user_review",
            clarification_round=round_index,
            core_need_round=min(round_index, config.max_core_need_rounds),
            plan_revision_count=state.plan_revision_count,
            readiness="awaiting_plan_review",
            latest_core_need_report_ref=FRONTDESK_GOAL_CORE_NEED_REPORT_REF,
            core_need_brief_ref=FRONTDESK_CORE_NEED_BRIEF_REF,
            decision_ledger_ref=state.decision_ledger_ref,
            solution_plan_ref=FRONTDESK_SOLUTION_PLAN_REF,
            solution_plan_markdown_ref=FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF,
            latest_plan_review_ref=state.latest_plan_review_ref,
            latest_elicitation_report_ref=elicitation_ref,
            latest_audit_report_ref=state.latest_audit_report_ref,
            next_action="await_user_plan_review",
            human_review_required=False,
            frontdesk_budget_ref=state.frontdesk_budget_ref,
            risk_report_ref=state.risk_report_ref,
            freeze_gate_result_ref=state.freeze_gate_result_ref,
            freeze_manifest_ref=state.freeze_manifest_ref,
            acceptance_coverage_plan_ref=state.acceptance_coverage_plan_ref,
        )
        next_state.validate()
        return FrontDeskLoopResult(
            state=next_state,
            round_index=round_index,
            status=FRONTDESK_LOOP_STATUS_AWAIT_PLAN_REVIEW,
            materialized_artifact_refs=artifact_refs,
            elicitation_report_ref=elicitation_ref,
            audit_report_ref=state.latest_audit_report_ref,
        )

    def _audit_and_freeze_approved_plan(
        self,
        frontdesk: FrontDeskWorkspace,
        *,
        state: FrontDeskState,
        config: FrontDeskConfig,
        auditor_client: Any | None,
        auditor_model_params: Mapping[str, Any] | None,
        auditor_provider: str,
        auditor_model: str,
    ) -> FrontDeskLoopResult:
        round_index = _report_index_from_ref(state.latest_elicitation_report_ref) or max(1, state.clarification_round)
        if not state.solution_plan_ref or not state.latest_plan_review_ref:
            failure_ref = _write_loop_failure(
                frontdesk,
                round_index=round_index,
                failure_type="plan_approval_missing",
                message="approved plan freeze requested without solution_plan_ref and latest_plan_review_ref",
                artifact_refs=_artifact_refs_from_state(state),
            )
            failed_state = _failed_state(
                state,
                clarification_round=round_index,
                latest_elicitation_report_ref=state.latest_elicitation_report_ref,
                latest_audit_report_ref=state.latest_audit_report_ref,
            )
            return _failure_result(failed_state, round_index=round_index, failure_ref=failure_ref)

        if _use_goal_harness_spec_auditor(self.auditor, auditor_client):
            audit_report_ref = SPEC_AUDIT_REPORT_REF_TEMPLATE.format(sequence=round_index)
            feasibility_report_ref = FEASIBILITY_REPORT_REF
            elicitation_report_ref = state.latest_elicitation_report_ref or ELICITATION_REPORT_REF_TEMPLATE.format(
                sequence=round_index
            )
            try:
                goal_audit = run_frontdesk_spec_auditor_goal_harness(
                    frontdesk,
                    plan_review_ref=state.latest_plan_review_ref,
                    audit_report_ref=audit_report_ref,
                    audit_elicitation_report_ref=elicitation_report_ref,
                )
            except Exception as exc:
                failure_ref = _write_loop_failure(
                    frontdesk,
                    round_index=round_index,
                    failure_type="goal_harness_spec_auditor_exception",
                    message=str(exc),
                    details={"exception_type": type(exc).__name__},
                    artifact_refs=_artifact_refs_from_state(state),
                )
                failed_state = _failed_state(
                    state,
                    clarification_round=round_index,
                    latest_elicitation_report_ref=state.latest_elicitation_report_ref,
                    latest_audit_report_ref=state.latest_audit_report_ref,
                )
                return _failure_result(failed_state, round_index=round_index, failure_ref=failure_ref)
            if goal_audit.harness_result.worker_run.status != "completed":
                failed_state = _failed_state(
                    state,
                    clarification_round=round_index,
                    latest_elicitation_report_ref=state.latest_elicitation_report_ref,
                    latest_audit_report_ref=state.latest_audit_report_ref,
                )
                return _failure_result(
                    failed_state,
                    round_index=round_index,
                    failure_ref=goal_audit.harness_result.worker_run.final_output_ref,
                )
            try:
                audit_report = SpecAuditReport.read_json_file(
                    frontdesk.workspace.resolve_path(audit_report_ref, must_exist=True)
                )
                feasibility_report = FeasibilityReport.read_json_file(
                    frontdesk.workspace.resolve_path(feasibility_report_ref, must_exist=True)
                )
            except Exception as exc:
                failure_ref = _write_loop_failure(
                    frontdesk,
                    round_index=round_index,
                    failure_type="invalid_goal_harness_spec_auditor_result",
                    message=str(exc),
                    details={"exception_type": type(exc).__name__},
                    artifact_refs=_artifact_refs_from_state(state),
                )
                failed_state = _failed_state(
                    state,
                    clarification_round=round_index,
                    latest_elicitation_report_ref=state.latest_elicitation_report_ref,
                    latest_audit_report_ref=state.latest_audit_report_ref,
                )
                return _failure_result(failed_state, round_index=round_index, failure_ref=failure_ref)
        else:
            try:
                audit = self.auditor.audit(
                    frontdesk,
                    round_index=round_index,
                    client=auditor_client,
                    config=config,
                    provider=auditor_provider,
                    model=auditor_model,
                    model_params=auditor_model_params,
                )
            except Exception as exc:
                failure_ref = _write_loop_failure(
                    frontdesk,
                    round_index=round_index,
                    failure_type="auditor_exception",
                    message=str(exc),
                    details={"exception_type": type(exc).__name__},
                    artifact_refs=_artifact_refs_from_state(state),
                )
                failed_state = _failed_state(
                    state,
                    clarification_round=round_index,
                    latest_elicitation_report_ref=state.latest_elicitation_report_ref,
                    latest_audit_report_ref=state.latest_audit_report_ref,
                )
                return _failure_result(failed_state, round_index=round_index, failure_ref=failure_ref)

            if audit.status == SPEC_AUDIT_STATUS_FAIL_CLOSED:
                failed_state = _failed_state(
                    state,
                    clarification_round=round_index,
                    latest_elicitation_report_ref=state.latest_elicitation_report_ref,
                    latest_audit_report_ref=state.latest_audit_report_ref,
                )
                return _failure_result(failed_state, round_index=round_index, failure_ref=audit.failure_ref)

            if audit.audit_report_ref is None or audit.feasibility_report_ref is None:
                failure_ref = _write_loop_failure(
                    frontdesk,
                    round_index=round_index,
                    failure_type="invalid_audit_result",
                    message="auditor returned success without required report refs",
                    artifact_refs=_artifact_refs_from_state(state),
                )
                failed_state = _failed_state(
                    state,
                    clarification_round=round_index,
                    latest_elicitation_report_ref=state.latest_elicitation_report_ref,
                    latest_audit_report_ref=state.latest_audit_report_ref,
                )
                return _failure_result(failed_state, round_index=round_index, failure_ref=failure_ref)
            audit_report_ref = audit.audit_report_ref
            feasibility_report_ref = audit.feasibility_report_ref
            audit_report = audit.audit_report
            feasibility_report = audit.feasibility_report

        elicitation_report = None
        if state.latest_elicitation_report_ref is not None:
            try:
                elicitation_report = ElicitationReport.read_json_file(
                    frontdesk.workspace.resolve_path(state.latest_elicitation_report_ref, must_exist=True)
                )
            except Exception:
                elicitation_report = None
        _write_round_risk_report(
            frontdesk,
            round_index=round_index,
            elicitation_report=elicitation_report,
            audit_report=audit_report,
            feasibility_report=feasibility_report,
        )

        try:
            freeze = self.freeze_gate.evaluate_and_freeze(frontdesk, round_index=round_index, config=config)
        except Exception as exc:
            failure_ref = _write_loop_failure(
                frontdesk,
                round_index=round_index,
                failure_type="freeze_gate_exception",
                message=str(exc),
                details={"exception_type": type(exc).__name__},
                artifact_refs=_artifact_refs_from_state(state),
            )
            failed_state = _failed_state(
                state,
                clarification_round=round_index,
                latest_elicitation_report_ref=state.latest_elicitation_report_ref,
                latest_audit_report_ref=audit_report_ref,
            )
            return _failure_result(failed_state, round_index=round_index, failure_ref=failure_ref)

        next_state = _state_from_freeze_result(
            state,
            job_id=frontdesk.job_id,
            round_index=round_index,
            elicitation_report_ref=state.latest_elicitation_report_ref
            or ELICITATION_REPORT_REF_TEMPLATE.format(sequence=round_index),
            audit_report_ref=audit_report_ref,
            freeze_decision=freeze.decision,
            freeze_gate_result_ref=freeze.freeze_gate_result_ref,
            freeze_manifest_ref=freeze.freeze_manifest_ref,
            frozen_artifact_refs=freeze.frozen_artifact_refs,
            config=config,
        )
        return FrontDeskLoopResult(
            state=next_state,
            round_index=round_index,
            status=next_state.next_action,
            frozen_artifact_refs=dict(freeze.frozen_artifact_refs),
            elicitation_report_ref=state.latest_elicitation_report_ref,
            audit_report_ref=audit_report_ref,
            feasibility_report_ref=feasibility_report_ref,
            freeze_gate_result_ref=freeze.freeze_gate_result_ref,
            freeze_manifest_ref=freeze.freeze_manifest_ref,
        )


def _use_goal_harness_planning(elicitor: RequirementsElicitor, elicitor_client: Any | None) -> bool:
    return elicitor_client is None and type(elicitor) is RequirementsElicitor


def _use_goal_harness_spec_auditor(auditor: SpecAuditor, auditor_client: Any | None) -> bool:
    return auditor_client is None and type(auditor) is SpecAuditor


def run_frontdesk_round(
    workspace: FrontDeskWorkspace | JobWorkspace,
    *,
    state: FrontDeskState | Mapping[str, Any] | None = None,
    config: FrontDeskConfig | None = None,
    elicitor_client: Any | None = None,
    auditor_client: Any | None = None,
    elicitor: RequirementsElicitor | None = None,
    auditor: SpecAuditor | None = None,
    freeze_gate: FrontDeskFreezeGate | None = None,
    elicitor_model_params: Mapping[str, Any] | None = None,
    auditor_model_params: Mapping[str, Any] | None = None,
    elicitor_provider: str = "fake",
    auditor_provider: str = "fake",
    elicitor_model: str = "skillfoundry-requirements-elicitor-fake",
    auditor_model: str = "skillfoundry-spec-auditor-fake",
) -> FrontDeskLoopResult:
    """Convenience wrapper for ``FrontDeskLoop(...).run_round(...)``."""

    loop = FrontDeskLoop(config=config, elicitor=elicitor, auditor=auditor, freeze_gate=freeze_gate)
    return loop.run_round(
        workspace,
        state=state,
        elicitor_client=elicitor_client,
        auditor_client=auditor_client,
        elicitor_model_params=elicitor_model_params,
        auditor_model_params=auditor_model_params,
        elicitor_provider=elicitor_provider,
        auditor_provider=auditor_provider,
        elicitor_model=elicitor_model,
        auditor_model=auditor_model,
    )


@dataclass(frozen=True)
class _MaterializationResult:
    artifact_refs: dict[str, str] = field(default_factory=dict)
    failure_ref: str | None = None


def _as_frontdesk_workspace(workspace: FrontDeskWorkspace | JobWorkspace) -> FrontDeskWorkspace:
    if isinstance(workspace, FrontDeskWorkspace):
        return workspace
    if isinstance(workspace, JobWorkspace):
        return FrontDeskWorkspace(workspace=workspace)
    raise TypeError("workspace must be a FrontDeskWorkspace or JobWorkspace")


def _coerce_state(state: FrontDeskState | Mapping[str, Any] | None, *, job_id: str) -> FrontDeskState:
    if state is None:
        result = FrontDeskState(
            job_id=job_id,
            stage="new_conversation",
            frontdesk_phase="core_need_discovery",
            clarification_round=0,
            readiness="new_conversation",
            next_action="discover_core_need",
        )
    elif isinstance(state, FrontDeskState):
        result = state
        result.validate()
    elif isinstance(state, Mapping):
        result = FrontDeskState.from_dict(state)
    else:
        raise TypeError("state must be a FrontDeskState, mapping, or None")
    if result.job_id != job_id:
        raise SchemaValidationError("FrontDeskState job_id does not match workspace job_id")
    return result


def _load_config(frontdesk: FrontDeskWorkspace, config: FrontDeskConfig | None) -> FrontDeskConfig:
    if config is not None:
        config.validate()
        return config
    return FrontDeskConfig.read_json_file(frontdesk.workspace.resolve_path(FRONTDESK_BUDGET_REF, must_exist=True))


def _result_from_terminal_state(state: FrontDeskState) -> FrontDeskLoopResult:
    status = state.next_action
    if state.readiness == "frozen":
        status = FRONTDESK_LOOP_STATUS_ROUTE_TO_BUILD
    elif state.readiness == "human_review_required":
        status = FRONTDESK_LOOP_STATUS_HUMAN_REVIEW
    elif state.readiness == "rejected":
        status = FRONTDESK_LOOP_STATUS_REJECT
    elif state.readiness == "failed":
        status = FRONTDESK_LOOP_STATUS_FAIL_CLOSED
    return FrontDeskLoopResult(
        state=state,
        round_index=max(1, state.clarification_round),
        status=status,
        elicitation_report_ref=state.latest_elicitation_report_ref,
        audit_report_ref=state.latest_audit_report_ref,
        freeze_gate_result_ref=state.freeze_gate_result_ref,
        freeze_manifest_ref=state.freeze_manifest_ref,
    )


def _materialize_elicitation_drafts(
    frontdesk: FrontDeskWorkspace,
    *,
    report: Any,
    round_index: int,
) -> _MaterializationResult:
    artifact_refs: dict[str, str] = {}
    failures: list[dict[str, JsonValue]] = []
    ready_for_audit = report.readiness_guess == "ready_for_audit"

    if report.draft_skill_spec:
        try:
            if ready_for_audit:
                skill_spec = _skill_spec_from_draft_payload(report.draft_skill_spec)
                artifact = write_frontdesk_artifact(frontdesk, FRONTDESK_DRAFT_SKILL_SPEC_REF, skill_spec)
            else:
                artifact = write_frontdesk_artifact(frontdesk, FRONTDESK_DRAFT_SKILL_SPEC_REF, report.draft_skill_spec)
            artifact_refs["draft_skill_spec"] = artifact.path
        except (OSError, ValueError, SchemaValidationError, TypeError) as exc:
            failures.append(
                _failure_detail(
                    "invalid_draft_skill_spec",
                    str(exc),
                    ref=FRONTDESK_DRAFT_SKILL_SPEC_REF,
                    exception_type=type(exc).__name__,
                )
            )
    elif ready_for_audit:
        failures.append(
            _failure_detail(
                "missing_draft_skill_spec",
                "ready_for_audit elicitation report did not include draft_skill_spec",
                ref=FRONTDESK_DRAFT_SKILL_SPEC_REF,
            )
        )

    if report.draft_acceptance_criteria:
        try:
            normalized_criteria = [
                _normalize_acceptance_criterion_payload(criterion, index=index)
                if isinstance(criterion, Mapping)
                else criterion
                for index, criterion in enumerate(report.draft_acceptance_criteria, start=1)
            ]
            criteria = AcceptanceCriteriaSet.from_dict(
                {
                    "criteria": normalized_criteria,
                    "job_id": frontdesk.job_id,
                }
            )
            artifact = write_acceptance_criteria(frontdesk, criteria)
            artifact_refs["acceptance_criteria"] = artifact.path
        except (OSError, ValueError, SchemaValidationError, TypeError) as exc:
            failures.append(
                _failure_detail(
                    "invalid_acceptance_criteria",
                    str(exc),
                    ref=FRONTDESK_ACCEPTANCE_CRITERIA_REF,
                    exception_type=type(exc).__name__,
                )
            )
    elif ready_for_audit:
        failures.append(
            _failure_detail(
                "missing_acceptance_criteria",
                "ready_for_audit elicitation report did not include draft_acceptance_criteria",
                ref=FRONTDESK_ACCEPTANCE_CRITERIA_REF,
            )
        )

    if failures and ready_for_audit:
        failure_ref = _write_loop_failure(
            frontdesk,
            round_index=round_index,
            failure_type="draft_materialization_failed",
            message="ready_for_audit report had missing or invalid draft artifacts",
            details={"failures": failures},
            artifact_refs={
                "elicitation_report": f"frontdesk/elicitation_report_{round_index:03d}.json",
                **artifact_refs,
            },
        )
        return _MaterializationResult(artifact_refs=artifact_refs, failure_ref=failure_ref)
    return _MaterializationResult(artifact_refs=artifact_refs)


def _materialize_core_need_and_solution_plan(
    frontdesk: FrontDeskWorkspace,
    *,
    report: ElicitationReport,
    round_index: int,
) -> _MaterializationResult:
    artifact_refs: dict[str, str] = {}
    failures: list[dict[str, JsonValue]] = []
    try:
        known = report.known_fields
        target_user = _string_from_known_fields(known, "target_user", "user", "audience") or "the requesting user"
        desired_outcome = (
            _string_from_known_fields(known, "desired_outcome", "outcome")
            or _string_from_known_fields(known, "output")
            or report.current_understanding
        )
        brief = CoreNeedBrief(
            problem_statement=report.current_understanding,
            target_user=target_user,
            usage_moment=_string_from_known_fields(known, "usage_moment", "workflow") or "when the user invokes the Skill",
            desired_outcome=desired_outcome,
            success_signal=_acceptance_success_signal(report.draft_acceptance_criteria),
            current_workaround=_string_from_known_fields(known, "current_workaround") or "",
            non_goals=[str(item) for item in report.draft_skill_spec.get("non_trigger_scenarios", [])]
            if isinstance(report.draft_skill_spec.get("non_trigger_scenarios"), list)
            else [],
            assumptions=list(report.assumptions),
            risk_flags=list(report.risk_flags),
            confidence_score=0.80 if not report.missing_fields else 0.65,
            source_turn_ids=_source_turn_ids_from_criteria(report.draft_acceptance_criteria),
        )
        core_report = CoreNeedDiscoveryReport(
            readiness="core_need_ready",
            current_understanding=report.current_understanding,
            core_need_brief=brief,
            decision_ledger_ref=FRONTDESK_DECISION_LEDGER_REF,
            summary_ref="frontdesk/core_need_summary.md",
            round_index=round_index,
        )
        core_report_ref = FRONTDESK_CORE_NEED_REPORT_REF_TEMPLATE.format(sequence=round_index)
        artifact_refs["core_need_report"] = write_frontdesk_artifact(frontdesk, core_report_ref, core_report).path
        artifact_refs["core_need_brief"] = write_frontdesk_artifact(frontdesk, FRONTDESK_CORE_NEED_BRIEF_REF, brief).path
        artifact_refs["decision_ledger"] = write_frontdesk_artifact(
            frontdesk,
            FRONTDESK_DECISION_LEDGER_REF,
            {
                "schema_version": "skillfoundry.frontdesk_decision_ledger.v1",
                "round_index": round_index,
                "decisions": [
                    {
                        "decision": "core_need_ready",
                        "reason": "Elicitation report declared ready_for_audit; Front Desk converted it into a user-reviewable solution plan.",
                        "source_ref": f"frontdesk/elicitation_report_{round_index:03d}.json",
                        "created_at": utc_now(),
                    }
                ],
            },
        ).path
        proposed_name = str(report.draft_skill_spec.get("title") or report.draft_skill_spec.get("name") or "Proposed Skill")
        plan = SolutionPlan(
            plan_id=f"solution-plan-{round_index:03d}",
            core_need_brief_ref=FRONTDESK_CORE_NEED_BRIEF_REF,
            summary=report.current_understanding,
            proposed_skill_name=proposed_name,
            target_user=brief.target_user,
            user_problem=brief.problem_statement,
            desired_outcome=brief.desired_outcome,
            approach=_solution_approach_from_draft(report.draft_skill_spec),
            implementation_outline=_implementation_outline_from_draft(report.draft_skill_spec),
            key_decisions=_key_decisions_from_report(report),
            acceptance_summary=_acceptance_summaries(report.draft_acceptance_criteria),
            risks=list(report.risk_flags),
            open_confirmation_items=list(report.missing_fields[:3]),
            status="awaiting_user_review",
            draft_skill_spec_ref=FRONTDESK_DRAFT_SKILL_SPEC_REF,
            acceptance_criteria_ref=FRONTDESK_ACCEPTANCE_CRITERIA_REF,
            markdown_ref=FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF,
        )
        artifact_refs["solution_plan"] = write_frontdesk_artifact(frontdesk, FRONTDESK_SOLUTION_PLAN_REF, plan).path
        artifact_refs["solution_plan_markdown"] = write_frontdesk_artifact(
            frontdesk,
            FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF,
            _solution_plan_markdown(plan, brief),
        ).path
        write_frontdesk_artifact(frontdesk, "core_need_summary.md", _core_need_summary_markdown(brief))
    except (OSError, ValueError, SchemaValidationError, TypeError) as exc:
        failures.append(
            _failure_detail(
                "solution_plan_materialization_failed",
                str(exc),
                ref=FRONTDESK_SOLUTION_PLAN_REF,
                exception_type=type(exc).__name__,
            )
        )

    if failures:
        failure_ref = _write_loop_failure(
            frontdesk,
            round_index=round_index,
            failure_type="solution_plan_materialization_failed",
            message="ready_for_audit report could not be converted into core need and solution plan artifacts",
            details={"failures": failures},
            artifact_refs={
                "elicitation_report": f"frontdesk/elicitation_report_{round_index:03d}.json",
                **artifact_refs,
            },
        )
        return _MaterializationResult(artifact_refs=artifact_refs, failure_ref=failure_ref)
    return _MaterializationResult(artifact_refs=artifact_refs)


def _elicitation_report_from_goal_harness_plan(
    *,
    core_report: CoreNeedDiscoveryReport,
    core_brief: CoreNeedBrief,
    plan: SolutionPlan,
    draft_skill_spec: SkillSpec,
    acceptance_criteria: AcceptanceCriteriaSet,
    round_index: int,
) -> ElicitationReport:
    return ElicitationReport(
        readiness_guess="ready_for_audit",
        current_understanding=plan.summary or core_report.current_understanding or core_brief.problem_statement,
        known_fields={
            "core_need": {
                "problem_statement": core_brief.problem_statement,
                "target_user": core_brief.target_user,
                "usage_moment": core_brief.usage_moment,
                "desired_outcome": core_brief.desired_outcome,
                "success_signal": core_brief.success_signal,
            },
            "solution_plan": {
                "ref": FRONTDESK_SOLUTION_PLAN_REF,
                "proposed_skill_name": plan.proposed_skill_name,
                "status": plan.status,
            },
            "contextforge_runtime": {
                "core_need_runtime_result_ref": FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF,
                "solution_plan_runtime_result_ref": FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF,
            },
        },
        missing_fields=[],
        risk_flags=_dedupe_strings([*core_brief.risk_flags, *plan.risks]),
        next_questions=[],
        draft_skill_spec=draft_skill_spec.to_dict(),
        draft_acceptance_criteria=[criterion.to_dict() for criterion in acceptance_criteria.criteria],
        assumptions=_dedupe_strings(
            [
                *core_brief.assumptions,
                "Core need and solution plan were produced through Front Desk Goal Harness runtime artifacts.",
                "Raw Front Desk conversation remained forbidden provenance for the planning nodes.",
            ]
        ),
        conversation_ref="frontdesk/conversation.jsonl",
        round_index=round_index,
    )


def _skill_spec_from_draft_payload(payload: Mapping[str, Any]) -> SkillSpec:
    return SkillSpec.from_dict(_normalize_skill_spec_payload(payload))


def _slugify_skill_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_.-]+", "-", value.lower()).strip("-._")
    if not slug:
        raise SchemaValidationError("draft skill spec name cannot be converted to a skill_id")
    return slug[:80]


def _string_from_known_fields(known_fields: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = known_fields.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Mapping):
            for nested_value in value.values():
                if isinstance(nested_value, str) and nested_value.strip():
                    return nested_value.strip()
    return None


def _acceptance_success_signal(criteria: list[dict[str, JsonValue]]) -> str:
    summaries = _acceptance_summaries(criteria)
    if summaries:
        return summaries[0]
    return "The generated Skill satisfies the reviewed solution plan without using unstated inputs."


def _source_turn_ids_from_criteria(criteria: list[dict[str, JsonValue]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for criterion in criteria:
        values = criterion.get("source_turn_ids")
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, str) and item.strip() and item not in seen:
                seen.add(item)
                result.append(item)
    return result


def _solution_approach_from_draft(draft: Mapping[str, Any]) -> str:
    constraints = draft.get("constraints")
    if isinstance(constraints, list) and constraints:
        return "Implement a local Codex Skill that follows the frozen spec and these constraints: " + "; ".join(
            str(item) for item in constraints if str(item).strip()
        )
    description = draft.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    return "Implement a local Codex Skill from the reviewed plan and acceptance criteria."


def _technical_route_from_draft(draft: Mapping[str, Any]) -> str:
    description = " ".join(str(draft.get(key) or "") for key in ("description", "title", "skill_id")).lower()
    required_inputs = draft.get("required_inputs")
    constraints = draft.get("constraints")
    combined = description + " " + " ".join(str(item).lower() for item in required_inputs if isinstance(required_inputs, list))
    combined += " " + " ".join(str(item).lower() for item in constraints if isinstance(constraints, list))
    if any(term in combined for term in ("api", "external", "network", "database")):
        return "script_required_or_human_review"
    if any(term in combined for term in ("search", "retrieve", "knowledge base", "document corpus", "rag")):
        return "rag"
    return "prompt_only_local_skill"


def _implementation_outline_from_draft(draft: Mapping[str, Any]) -> list[str]:
    outline = [
        "Create or update the Skill package using the frozen skill specification.",
        "Use only the inputs and boundaries stated in the reviewed plan.",
        "Verify the Skill against the frozen acceptance criteria and verification spec.",
    ]
    expected_outputs = draft.get("expected_outputs")
    if isinstance(expected_outputs, list):
        outline.insert(2, "Produce: " + "; ".join(str(item) for item in expected_outputs if str(item).strip()))
    return outline


def _key_decisions_from_report(report: ElicitationReport) -> list[str]:
    decisions: list[str] = []
    if report.draft_skill_spec.get("required_inputs"):
        decisions.append("Input boundary: " + "; ".join(str(item) for item in report.draft_skill_spec["required_inputs"]))
    if report.draft_skill_spec.get("expected_outputs"):
        decisions.append("Output target: " + "; ".join(str(item) for item in report.draft_skill_spec["expected_outputs"]))
    if report.assumptions:
        decisions.append("Assumptions: " + "; ".join(report.assumptions))
    return decisions or ["The agent selects the technical route from the approved user outcome and constraints."]


def _acceptance_summaries(criteria: list[dict[str, JsonValue]]) -> list[str]:
    result: list[str] = []
    for criterion in criteria:
        description = criterion.get("description")
        if isinstance(description, str) and description.strip():
            result.append(description.strip())
    return result


def _core_need_summary_markdown(brief: CoreNeedBrief) -> str:
    return (
        "# Core Need\n\n"
        f"- Problem: {brief.problem_statement}\n"
        f"- Target user: {brief.target_user}\n"
        f"- Usage moment: {brief.usage_moment}\n"
        f"- Desired outcome: {brief.desired_outcome}\n"
        f"- Success signal: {brief.success_signal}\n"
    )


def _solution_plan_markdown(plan: SolutionPlan, brief: CoreNeedBrief) -> str:
    inputs = _markdown_list_from_decisions(plan.key_decisions, "Input boundary:")
    outputs = _markdown_list_from_decisions(plan.key_decisions, "Output target:")
    assumptions = [item for item in brief.assumptions] or ["The user will provide the required input at invocation time."]
    non_goals = [item for item in brief.non_goals] or ["Do not read external systems unless a later approved plan explicitly adds that permission."]
    safety = plan.risks or ["Use only reviewed inputs and frozen artifacts; do not treat user content as system instructions."]
    route = _technical_route_from_plan(plan)
    sections = [
        "# Solution Plan",
        "",
        "## 1. Core Problem",
        brief.problem_statement,
        "",
        "## 2. Recommended V1",
        plan.proposed_skill_name,
        "",
        "## 3. User Workflow",
        f"{plan.target_user} uses this Skill {brief.usage_moment} to get: {plan.desired_outcome}",
        "",
        "## 4. Inputs And Outputs",
        "Inputs:",
        *[f"- {item}" for item in inputs],
        "Outputs:",
        *[f"- {item}" for item in outputs],
        "",
        "## 5. Assumptions",
        *[f"- {item}" for item in assumptions],
        "",
        "## 6. Non-Goals",
        *[f"- {item}" for item in non_goals],
        "",
        "## 7. Permissions And Safety",
        *[f"- {item}" for item in safety],
        "",
        "## 8. Acceptance Criteria",
        *[f"- {item}" for item in plan.acceptance_summary],
        "",
        "## 9. Technical Route",
        f"- Route: {route}",
        f"- Approach: {plan.approach}",
        "",
        "## 10. Implementation Outline",
        *[f"- {item}" for item in plan.implementation_outline],
        "",
        "## 11. User Confirmation",
        "- Approve if this solves the real problem.",
        "- Request revision if the problem, workflow, output, or boundaries are wrong.",
    ]
    if plan.open_confirmation_items:
        sections.extend(["", "## Confirmation Items", *[f"- {item}" for item in plan.open_confirmation_items]])
    return "\n".join(sections).rstrip() + "\n"


def _markdown_list_from_decisions(decisions: list[str], prefix: str) -> list[str]:
    for decision in decisions:
        if decision.startswith(prefix):
            values = [item.strip() for item in decision[len(prefix) :].split(";") if item.strip()]
            if values:
                return values
    return ["User-provided content described in the approved plan."]


def _technical_route_from_plan(plan: SolutionPlan) -> str:
    text = " ".join([plan.approach, *plan.key_decisions, *plan.risks]).lower()
    if any(term in text for term in ("api", "external", "network", "database")):
        return "script_required_or_human_review"
    if any(term in text for term in ("search", "retrieve", "knowledge base", "document corpus", "rag")):
        return "rag"
    return "prompt_only_local_skill"


def _failure_detail(
    code: str,
    message: str,
    *,
    ref: str,
    exception_type: str | None = None,
) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {"code": code, "message": message, "ref": ref}
    if exception_type is not None:
        payload["exception_type"] = exception_type
    return payload


def _write_round_risk_report(
    frontdesk: FrontDeskWorkspace,
    *,
    round_index: int,
    elicitation_report: Any,
    audit_report: Any,
    feasibility_report: Any,
) -> None:
    risk_flags: list[str] = []
    if elicitation_report is not None:
        risk_flags.extend(str(flag) for flag in getattr(elicitation_report, "risk_flags", []) if str(flag).strip())
    if audit_report is not None:
        risk_flags.extend(str(item) for item in getattr(audit_report, "unsafe_assumptions", []) if str(item).strip())
    if feasibility_report is not None:
        risk_flags.extend(str(item) for item in getattr(feasibility_report, "risks", []) if str(item).strip())

    write_frontdesk_artifact(
        frontdesk,
        "risk_report.json",
        {
            "schema_version": "skillfoundry.frontdesk_risk_report.v1",
            "round_index": round_index,
            "redaction_status": "complete",
            "risk_flags": _dedupe_strings(risk_flags),
            "data_sensitivity": "internal",
            "provider_usage": {
                "usage_available": False,
                "usage_unavailable_reason": (
                    "Front Desk aggregate provider usage is not yet available at the risk gate; "
                    "individual owned model call usage or usage-unavailable reasons are recorded by ContextForge."
                ),
            },
        },
    )


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _copy_state_for_next_planning_round(state: FrontDeskState) -> FrontDeskState:
    result = FrontDeskState(
        job_id=state.job_id,
        stage="plan_solution",
        frontdesk_phase="solution_planning",
        clarification_round=state.clarification_round,
        core_need_round=state.core_need_round,
        plan_revision_count=state.plan_revision_count,
        readiness="plan_revision_requested",
        latest_core_need_report_ref=state.latest_core_need_report_ref,
        core_need_brief_ref=state.core_need_brief_ref,
        decision_ledger_ref=state.decision_ledger_ref,
        solution_plan_ref=state.solution_plan_ref,
        solution_plan_markdown_ref=state.solution_plan_markdown_ref,
        latest_plan_review_ref=state.latest_plan_review_ref,
        latest_elicitation_report_ref=state.latest_elicitation_report_ref,
        latest_audit_report_ref=state.latest_audit_report_ref,
        skill_spec_ref=state.skill_spec_ref,
        acceptance_criteria_ref=state.acceptance_criteria_ref,
        verification_spec_ref=state.verification_spec_ref,
        next_action="elicit",
        human_review_required=False,
        frontdesk_budget_ref=state.frontdesk_budget_ref,
        risk_report_ref=state.risk_report_ref,
        freeze_gate_result_ref=state.freeze_gate_result_ref,
        freeze_manifest_ref=state.freeze_manifest_ref,
        acceptance_coverage_plan_ref=state.acceptance_coverage_plan_ref,
    )
    result.validate()
    return result


def _state_from_freeze_result(
    current_state: FrontDeskState,
    *,
    job_id: str,
    round_index: int,
    elicitation_report_ref: str,
    audit_report_ref: str,
    freeze_decision: str,
    freeze_gate_result_ref: str,
    freeze_manifest_ref: str | None,
    frozen_artifact_refs: Mapping[str, str],
    config: FrontDeskConfig,
) -> FrontDeskState:
    if freeze_decision == FREEZE_GATE_DECISION_FREEZE:
        state = FrontDeskState(
            job_id=job_id,
            stage="route_to_build",
            frontdesk_phase="complete",
            clarification_round=round_index,
            core_need_round=current_state.core_need_round,
            plan_revision_count=current_state.plan_revision_count,
            readiness="frozen",
            latest_core_need_report_ref=current_state.latest_core_need_report_ref,
            core_need_brief_ref=current_state.core_need_brief_ref,
            decision_ledger_ref=current_state.decision_ledger_ref,
            solution_plan_ref=current_state.solution_plan_ref,
            solution_plan_markdown_ref=current_state.solution_plan_markdown_ref,
            latest_plan_review_ref=current_state.latest_plan_review_ref,
            latest_elicitation_report_ref=elicitation_report_ref,
            latest_audit_report_ref=audit_report_ref,
            skill_spec_ref=frozen_artifact_refs.get("skill_spec", ROOT_SKILL_SPEC_REF),
            acceptance_criteria_ref=frozen_artifact_refs.get("acceptance_criteria", ROOT_ACCEPTANCE_CRITERIA_REF),
            verification_spec_ref=frozen_artifact_refs.get("verification_spec", ROOT_VERIFICATION_SPEC_REF),
            next_action="route_to_build",
            human_review_required=False,
            frontdesk_budget_ref=current_state.frontdesk_budget_ref,
            risk_report_ref=current_state.risk_report_ref,
            freeze_gate_result_ref=freeze_gate_result_ref,
            freeze_manifest_ref=freeze_manifest_ref or FREEZE_MANIFEST_REF,
            acceptance_coverage_plan_ref=current_state.acceptance_coverage_plan_ref,
        )
    elif freeze_decision == FREEZE_GATE_DECISION_HUMAN_REVIEW_REQUIRED:
        state = _human_review_state(
            current_state,
            stage="human_review",
            clarification_round=round_index,
            latest_elicitation_report_ref=elicitation_report_ref,
            latest_audit_report_ref=audit_report_ref,
            freeze_gate_result_ref=freeze_gate_result_ref,
            freeze_manifest_ref=freeze_manifest_ref,
        )
    elif freeze_decision == FREEZE_GATE_DECISION_REJECT:
        state = FrontDeskState(
            job_id=job_id,
            stage="complete",
            frontdesk_phase="failed",
            clarification_round=round_index,
            core_need_round=current_state.core_need_round,
            plan_revision_count=current_state.plan_revision_count,
            readiness="rejected",
            latest_core_need_report_ref=current_state.latest_core_need_report_ref,
            core_need_brief_ref=current_state.core_need_brief_ref,
            decision_ledger_ref=current_state.decision_ledger_ref,
            solution_plan_ref=current_state.solution_plan_ref,
            solution_plan_markdown_ref=current_state.solution_plan_markdown_ref,
            latest_plan_review_ref=current_state.latest_plan_review_ref,
            latest_elicitation_report_ref=elicitation_report_ref,
            latest_audit_report_ref=audit_report_ref,
            next_action="reject",
            human_review_required=False,
            frontdesk_budget_ref=current_state.frontdesk_budget_ref,
            risk_report_ref=current_state.risk_report_ref,
            freeze_gate_result_ref=freeze_gate_result_ref,
            freeze_manifest_ref=freeze_manifest_ref,
            acceptance_coverage_plan_ref=current_state.acceptance_coverage_plan_ref,
        )
    elif freeze_decision == FREEZE_GATE_DECISION_ASK_USER:
        if round_index >= config.max_clarification_rounds:
            state = _human_review_state(
                current_state,
                stage="human_review",
                clarification_round=round_index,
                latest_elicitation_report_ref=elicitation_report_ref,
                latest_audit_report_ref=audit_report_ref,
                freeze_gate_result_ref=freeze_gate_result_ref,
                freeze_manifest_ref=freeze_manifest_ref,
            )
        else:
            state = FrontDeskState(
                job_id=job_id,
                stage="ask_user",
                frontdesk_phase="core_need_discovery",
                clarification_round=round_index,
                core_need_round=current_state.core_need_round,
                plan_revision_count=current_state.plan_revision_count,
                readiness="needs_clarification",
                latest_core_need_report_ref=current_state.latest_core_need_report_ref,
                core_need_brief_ref=current_state.core_need_brief_ref,
                decision_ledger_ref=current_state.decision_ledger_ref,
                solution_plan_ref=current_state.solution_plan_ref,
                solution_plan_markdown_ref=current_state.solution_plan_markdown_ref,
                latest_plan_review_ref=current_state.latest_plan_review_ref,
                latest_elicitation_report_ref=elicitation_report_ref,
                latest_audit_report_ref=audit_report_ref,
                next_action="ask_user",
                human_review_required=False,
                frontdesk_budget_ref=current_state.frontdesk_budget_ref,
                risk_report_ref=current_state.risk_report_ref,
                freeze_gate_result_ref=freeze_gate_result_ref,
                freeze_manifest_ref=freeze_manifest_ref,
                acceptance_coverage_plan_ref=current_state.acceptance_coverage_plan_ref,
            )
    else:
        state = _failed_state(
            current_state,
            clarification_round=round_index,
            latest_elicitation_report_ref=elicitation_report_ref,
            latest_audit_report_ref=audit_report_ref,
            freeze_gate_result_ref=freeze_gate_result_ref,
            freeze_manifest_ref=freeze_manifest_ref,
        )
    state.validate()
    return state


def _human_review_state(
    state: FrontDeskState,
    *,
    stage: str,
    clarification_round: int,
    latest_elicitation_report_ref: str | None = None,
    latest_audit_report_ref: str | None = None,
    freeze_gate_result_ref: str | None = None,
    freeze_manifest_ref: str | None = None,
) -> FrontDeskState:
    result = FrontDeskState(
        job_id=state.job_id,
        stage=stage,
        frontdesk_phase="failed" if stage == "human_review" else state.frontdesk_phase,
        clarification_round=clarification_round,
        core_need_round=state.core_need_round,
        plan_revision_count=state.plan_revision_count,
        readiness="human_review_required",
        latest_core_need_report_ref=state.latest_core_need_report_ref,
        core_need_brief_ref=state.core_need_brief_ref,
        decision_ledger_ref=state.decision_ledger_ref,
        solution_plan_ref=state.solution_plan_ref,
        solution_plan_markdown_ref=state.solution_plan_markdown_ref,
        latest_plan_review_ref=state.latest_plan_review_ref,
        latest_elicitation_report_ref=latest_elicitation_report_ref or state.latest_elicitation_report_ref,
        latest_audit_report_ref=latest_audit_report_ref or state.latest_audit_report_ref,
        skill_spec_ref=state.skill_spec_ref,
        acceptance_criteria_ref=state.acceptance_criteria_ref,
        verification_spec_ref=state.verification_spec_ref,
        next_action="human_review",
        human_review_required=True,
        frontdesk_budget_ref=state.frontdesk_budget_ref,
        risk_report_ref=state.risk_report_ref,
        freeze_gate_result_ref=freeze_gate_result_ref or state.freeze_gate_result_ref,
        freeze_manifest_ref=freeze_manifest_ref or state.freeze_manifest_ref,
        acceptance_coverage_plan_ref=state.acceptance_coverage_plan_ref,
    )
    result.validate()
    return result


def _failed_state(
    state: FrontDeskState,
    *,
    clarification_round: int,
    latest_elicitation_report_ref: str | None,
    latest_audit_report_ref: str | None,
    freeze_gate_result_ref: str | None = None,
    freeze_manifest_ref: str | None = None,
) -> FrontDeskState:
    result = FrontDeskState(
        job_id=state.job_id,
        stage="failed",
        frontdesk_phase="failed",
        clarification_round=clarification_round,
        core_need_round=state.core_need_round,
        plan_revision_count=state.plan_revision_count,
        readiness="failed",
        latest_core_need_report_ref=state.latest_core_need_report_ref,
        core_need_brief_ref=state.core_need_brief_ref,
        decision_ledger_ref=state.decision_ledger_ref,
        solution_plan_ref=state.solution_plan_ref,
        solution_plan_markdown_ref=state.solution_plan_markdown_ref,
        latest_plan_review_ref=state.latest_plan_review_ref,
        latest_elicitation_report_ref=latest_elicitation_report_ref,
        latest_audit_report_ref=latest_audit_report_ref,
        skill_spec_ref=state.skill_spec_ref,
        acceptance_criteria_ref=state.acceptance_criteria_ref,
        verification_spec_ref=state.verification_spec_ref,
        next_action="fail_closed",
        human_review_required=False,
        frontdesk_budget_ref=state.frontdesk_budget_ref,
        risk_report_ref=state.risk_report_ref,
        freeze_gate_result_ref=freeze_gate_result_ref or state.freeze_gate_result_ref,
        freeze_manifest_ref=freeze_manifest_ref or state.freeze_manifest_ref,
        acceptance_coverage_plan_ref=state.acceptance_coverage_plan_ref,
    )
    result.validate()
    return result


def _retry_elicit_state(state: FrontDeskState) -> FrontDeskState:
    result = FrontDeskState(
        job_id=state.job_id,
        stage="elicit",
        frontdesk_phase=state.frontdesk_phase,
        clarification_round=state.clarification_round,
        core_need_round=state.core_need_round,
        plan_revision_count=state.plan_revision_count,
        readiness="needs_clarification",
        latest_core_need_report_ref=state.latest_core_need_report_ref,
        core_need_brief_ref=state.core_need_brief_ref,
        decision_ledger_ref=state.decision_ledger_ref,
        solution_plan_ref=state.solution_plan_ref,
        solution_plan_markdown_ref=state.solution_plan_markdown_ref,
        latest_plan_review_ref=state.latest_plan_review_ref,
        latest_elicitation_report_ref=state.latest_elicitation_report_ref,
        latest_audit_report_ref=state.latest_audit_report_ref,
        skill_spec_ref=state.skill_spec_ref,
        acceptance_criteria_ref=state.acceptance_criteria_ref,
        verification_spec_ref=state.verification_spec_ref,
        next_action="elicit",
        human_review_required=False,
        frontdesk_budget_ref=state.frontdesk_budget_ref,
        risk_report_ref=state.risk_report_ref,
        freeze_gate_result_ref=state.freeze_gate_result_ref,
        freeze_manifest_ref=state.freeze_manifest_ref,
        acceptance_coverage_plan_ref=state.acceptance_coverage_plan_ref,
    )
    result.validate()
    return result


def _is_transient_model_failure(failure: Mapping[str, Any] | None) -> bool:
    if not isinstance(failure, Mapping):
        return False
    failure_type = str(failure.get("failure_type") or "")
    if failure_type not in {"provider_error", "context_call_failed"}:
        return False
    details = failure.get("details")
    details_map = details if isinstance(details, Mapping) else {}
    error_type = str(details_map.get("error_type") or details_map.get("exception_type") or "").lower()
    message = str(failure.get("message") or "").lower()
    if "timeout" in error_type or "timed out" in message or "timeout" in message:
        return True
    if (
        "bad gateway" in message
        or "reconnecting" in message
        or "unexpected status 502" in message
        or "unexpected status 503" in message
        or "unexpected status 504" in message
        or re.search(r"\b50[234]\b", message) is not None
    ):
        return True
    return bool(details_map.get("retryable"))


def _report_index_from_ref(ref: str | None) -> int | None:
    if not ref:
        return None
    match = re.search(r"_(\d{3})\.json$", ref)
    if not match:
        return None
    return int(match.group(1))


def _failure_result(state: FrontDeskState, *, round_index: int, failure_ref: str | None) -> FrontDeskLoopResult:
    return FrontDeskLoopResult(
        state=state,
        round_index=round_index,
        status=FRONTDESK_LOOP_STATUS_FAIL_CLOSED,
        elicitation_report_ref=state.latest_elicitation_report_ref,
        audit_report_ref=state.latest_audit_report_ref,
        freeze_gate_result_ref=state.freeze_gate_result_ref,
        freeze_manifest_ref=state.freeze_manifest_ref,
        failure_ref=failure_ref,
    )


def _artifact_refs_from_state(state: FrontDeskState) -> dict[str, str]:
    refs = {
        "latest_core_need_report": state.latest_core_need_report_ref,
        "core_need_brief": state.core_need_brief_ref,
        "decision_ledger": state.decision_ledger_ref,
        "solution_plan": state.solution_plan_ref,
        "solution_plan_markdown": state.solution_plan_markdown_ref,
        "latest_plan_review": state.latest_plan_review_ref,
        "latest_elicitation_report": state.latest_elicitation_report_ref,
        "latest_audit_report": state.latest_audit_report_ref,
        "skill_spec": state.skill_spec_ref,
        "acceptance_criteria": state.acceptance_criteria_ref,
        "verification_spec": state.verification_spec_ref,
        "frontdesk_budget": state.frontdesk_budget_ref,
        "risk_report": state.risk_report_ref,
        "freeze_gate_result": state.freeze_gate_result_ref,
        "freeze_manifest": state.freeze_manifest_ref,
        "acceptance_coverage_plan": state.acceptance_coverage_plan_ref,
    }
    return {key: value for key, value in refs.items() if value is not None}


def _write_loop_failure(
    frontdesk: FrontDeskWorkspace,
    *,
    round_index: int,
    failure_type: str,
    message: str,
    details: Mapping[str, Any] | None = None,
    artifact_refs: Mapping[str, Any] | None = None,
) -> str | None:
    sequence = round_index if isinstance(round_index, int) and round_index > 0 else 1
    payload = ensure_json_compatible(
        {
            "schema_version": FRONTDESK_LOOP_FAILURE_SCHEMA_VERSION,
            "status": FRONTDESK_LOOP_STATUS_FAIL_CLOSED,
            "failure_type": failure_type,
            "message": message,
            "job_id": frontdesk.job_id,
            "round_index": sequence,
            "frontdesk_artifact_refs": {
                key: value
                for key, value in dict(artifact_refs or {}).items()
                if isinstance(value, str) and value
            },
            "details": ensure_json_compatible(dict(details or {})),
            "created_at": utc_now(),
        }
    )
    try:
        artifact = write_frontdesk_artifact(
            frontdesk,
            FRONTDESK_LOOP_FAILURE_REF_TEMPLATE.format(sequence=sequence),
            payload,
        )
        return artifact.path
    except Exception:
        return None
