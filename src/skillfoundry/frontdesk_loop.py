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
    FREEZE_GATE_DECISION_ASK_USER,
    FREEZE_GATE_DECISION_FREEZE,
    FREEZE_GATE_DECISION_HUMAN_REVIEW_REQUIRED,
    FREEZE_GATE_DECISION_REJECT,
    FRONTDESK_ACCEPTANCE_CRITERIA_REF,
    FRONTDESK_DRAFT_SKILL_SPEC_REF,
    FREEZE_MANIFEST_REF,
    ROOT_ACCEPTANCE_CRITERIA_REF,
    ROOT_SKILL_SPEC_REF,
    ROOT_VERIFICATION_SPEC_REF,
    SPEC_AUDIT_STATUS_FAIL_CLOSED,
    FrontDeskFreezeGate,
    RequirementsElicitor,
    SpecAuditor,
)
from .frontdesk_schema import AcceptanceCriteriaSet, FrontDeskConfig, FrontDeskState
from .frontdesk_workspace import (
    FRONTDESK_BUDGET_REF,
    FrontDeskWorkspace,
    write_acceptance_criteria,
    write_frontdesk_artifact,
)
from .schema import JsonValue, SchemaValidationError, SkillSpec, ensure_json_compatible, utc_now
from .workspace import JobWorkspace


FRONTDESK_LOOP_FAILURE_SCHEMA_VERSION = "skillfoundry.frontdesk_loop_failure.v1"
FRONTDESK_LOOP_FAILURE_REF_TEMPLATE = "frontdesk/frontdesk_loop_failure_{sequence:03d}.json"

FRONTDESK_LOOP_STATUS_ASK_USER = "ask_user"
FRONTDESK_LOOP_STATUS_ROUTE_TO_BUILD = "route_to_build"
FRONTDESK_LOOP_STATUS_HUMAN_REVIEW = "human_review"
FRONTDESK_LOOP_STATUS_REJECT = "reject"
FRONTDESK_LOOP_STATUS_FAIL_CLOSED = "fail_closed"

_TERMINAL_READINESS = frozenset({"frozen", "human_review_required", "rejected", "failed"})


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
        try:
            elicitation = self.elicitor.elicit(
                frontdesk,
                round_index=round_index,
                client=elicitor_client,
                config=config,
                provider="fake",
                model="skillfoundry-requirements-elicitor-fake",
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
            if round_index >= config.max_clarification_rounds:
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
                clarification_round=round_index,
                readiness="needs_clarification",
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

        try:
            audit = self.auditor.audit(
                frontdesk,
                round_index=round_index,
                client=auditor_client,
                config=config,
                provider="fake",
                model="skillfoundry-spec-auditor-fake",
                model_params=auditor_model_params,
            )
        except Exception as exc:
            failure_ref = _write_loop_failure(
                frontdesk,
                round_index=round_index,
                failure_type="auditor_exception",
                message=str(exc),
                details={"exception_type": type(exc).__name__},
                artifact_refs={
                    **_artifact_refs_from_state(current_state),
                    "elicitation_report": elicitation.report_ref,
                    **materialized.artifact_refs,
                },
            )
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
                failure_ref=failure_ref,
            )

        if audit.status == SPEC_AUDIT_STATUS_FAIL_CLOSED:
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
                failure_ref=audit.failure_ref,
            )

        if audit.audit_report_ref is None or audit.feasibility_report_ref is None:
            failure_ref = _write_loop_failure(
                frontdesk,
                round_index=round_index,
                failure_type="invalid_audit_result",
                message="auditor returned success without required report refs",
                artifact_refs={
                    **_artifact_refs_from_state(current_state),
                    "elicitation_report": elicitation.report_ref,
                    **materialized.artifact_refs,
                },
            )
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
                failure_ref=failure_ref,
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
                artifact_refs={
                    **_artifact_refs_from_state(current_state),
                    "elicitation_report": elicitation.report_ref,
                    "spec_audit_report": audit.audit_report_ref,
                    "feasibility_report": audit.feasibility_report_ref,
                    **materialized.artifact_refs,
                },
            )
            failed_state = _failed_state(
                current_state,
                clarification_round=round_index,
                latest_elicitation_report_ref=elicitation.report_ref,
                latest_audit_report_ref=audit.audit_report_ref,
            )
            return FrontDeskLoopResult(
                state=failed_state,
                round_index=round_index,
                status=FRONTDESK_LOOP_STATUS_FAIL_CLOSED,
                materialized_artifact_refs=materialized.artifact_refs,
                elicitation_report_ref=elicitation.report_ref,
                audit_report_ref=audit.audit_report_ref,
                feasibility_report_ref=audit.feasibility_report_ref,
                failure_ref=failure_ref,
            )

        next_state = _state_from_freeze_result(
            current_state,
            job_id=frontdesk.job_id,
            round_index=round_index,
            elicitation_report_ref=elicitation.report_ref,
            audit_report_ref=audit.audit_report_ref,
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
            materialized_artifact_refs=materialized.artifact_refs,
            frozen_artifact_refs=dict(freeze.frozen_artifact_refs),
            elicitation_report_ref=elicitation.report_ref,
            audit_report_ref=audit.audit_report_ref,
            feasibility_report_ref=audit.feasibility_report_ref,
            freeze_gate_result_ref=freeze.freeze_gate_result_ref,
            freeze_manifest_ref=freeze.freeze_manifest_ref,
        )


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
            clarification_round=0,
            readiness="new_conversation",
            next_action="elicit",
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
            criteria = AcceptanceCriteriaSet.from_dict(
                {
                    "criteria": report.draft_acceptance_criteria,
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


def _skill_spec_from_draft_payload(payload: Mapping[str, Any]) -> SkillSpec:
    data = dict(payload)
    name = data.pop("name", None)
    identifier = data.pop("id", None)
    if "title" not in data and isinstance(name, str):
        data["title"] = name
    if "skill_id" not in data:
        if isinstance(identifier, str) and identifier.strip():
            data["skill_id"] = identifier
        elif isinstance(name, str) and name.strip():
            data["skill_id"] = _slugify_skill_id(name)
    return SkillSpec.from_dict(data)


def _slugify_skill_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_.-]+", "-", value.lower()).strip("-._")
    if not slug:
        raise SchemaValidationError("draft skill spec name cannot be converted to a skill_id")
    return slug[:80]


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
            clarification_round=round_index,
            readiness="frozen",
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
            clarification_round=round_index,
            readiness="rejected",
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
                clarification_round=round_index,
                readiness="needs_clarification",
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
        clarification_round=clarification_round,
        readiness="human_review_required",
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
        clarification_round=clarification_round,
        readiness="failed",
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
