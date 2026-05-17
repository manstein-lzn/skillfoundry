import json

import pytest
from contextforge.schema import ModelResponse

import skillfoundry
from skillfoundry import (
    AcceptanceCriteriaSet,
    ConversationTurn,
    FRONTDESK_LOOP_STATUS_FAIL_CLOSED,
    FRONTDESK_LOOP_STATUS_HUMAN_REVIEW,
    FRONTDESK_LOOP_STATUS_ROUTE_TO_BUILD,
    FrontDeskConfig,
    FrontDeskLoop,
    FrontDeskLoopResult,
    FrontDeskState,
    SchemaValidationError,
    append_conversation_turn,
    initialize_frontdesk_workspace,
    initialize_job_workspace,
    run_frontdesk_round,
)
from skillfoundry.frontdesk import RequirementsElicitor, SpecAuditor


class ScriptedModelClient:
    def __init__(self, *, payload=None, text=None, exception=None):
        self.payload = payload
        self.text = text
        self.exception = exception
        self.invocations = []

    def invoke(self, messages, model, params, tools=None):
        self.invocations.append(
            {
                "messages": messages,
                "model": model,
                "params": params,
                "tools": tools,
            }
        )
        if self.exception is not None:
            raise self.exception
        response_text = self.text
        if response_text is None:
            response_text = json.dumps(self.payload, sort_keys=True)
        return (
            ModelResponse(
                text=response_text,
                raw_response_artifact_ref=None,
                finish_reason="stop",
                metadata={"scripted": True},
            ),
            None,
            None,
        )


def make_frontdesk_workspace(tmp_path, *, job_id="frontdesk-loop-001", config=None, user_content=None):
    workspace = initialize_job_workspace(tmp_path / "runs", job_id)
    frontdesk = initialize_frontdesk_workspace(workspace, config=config)
    append_conversation_turn(
        frontdesk,
        ConversationTurn(
            turn_id="turn-001",
            role="user",
            content=user_content
            or (
                "Create a local Codex Skill that turns pasted weekly notes into a Markdown "
                "status update for my internal team."
            ),
        ),
    )
    return workspace, frontdesk


def draft_skill_spec_payload():
    return {
        "skill_id": "weekly-update-writer",
        "title": "Weekly Update Writer",
        "description": "Create internal weekly updates from pasted notes.",
        "trigger_scenarios": ["The user asks to turn pasted weekly notes into a team update."],
        "non_trigger_scenarios": ["The request requires reading external systems."],
        "required_inputs": ["Pasted weekly notes."],
        "expected_outputs": ["Markdown status update with completed work, blockers, and next steps."],
        "constraints": ["Use only provided notes.", "Do not read external systems."],
        "acceptance_criteria": ["Output includes completed work, blockers, and next steps."],
        "reference_materials": [],
        "security_notes": ["No external data access is permitted."],
    }


def acceptance_criterion_payload(**overrides):
    payload = {
        "id": "AC-001",
        "description": "The skill writes a Markdown weekly update from provided notes only.",
        "source_requirement": "Summarize pasted weekly notes.",
        "source_turn_ids": ["turn-001"],
        "requirement_id": "REQ-001",
        "test_method": "fixture",
        "pass_condition": "The output contains completed work, blockers, and next steps.",
        "failure_examples": ["Invents work not present in the notes."],
        "required_evidence": ["fixture-output.md"],
        "evidence_kind": "file",
        "priority": "must",
        "risk_tags": [],
        "data_sensitivity": "internal",
        "coverage_status": "planned",
        "fixture_ref": "frontdesk/fixtures/weekly-notes.md",
    }
    payload.update(overrides)
    return payload


def needs_clarification_payload():
    return {
        "readiness_guess": "needs_clarification",
        "current_understanding": "The user wants a reporting-related skill, but key inputs are missing.",
        "known_fields": {"domain": "reporting"},
        "missing_fields": ["input.source"],
        "risk_flags": ["input_boundary_unknown"],
        "next_questions": [
            {
                "question_id": "Q-001",
                "text": "What source material should the skill use?",
                "missing_field_path": "input.source",
                "reason": "The builder needs a concrete input boundary.",
                "priority": "must",
                "answer_type": "free_text",
                "blocks_build": True,
            }
        ],
        "draft_skill_spec": {"name": "report-helper", "description": "Draft reporting output from user input."},
        "draft_acceptance_criteria": [
            {
                "id": "AC-001",
                "description": "The skill only uses the input source selected by the user.",
            }
        ],
        "assumptions": ["The user will provide source material."],
    }


def ready_for_audit_payload(*, criteria=None, draft_skill_spec=None):
    return {
        "readiness_guess": "ready_for_audit",
        "current_understanding": (
            "The user wants a local Codex Skill that turns pasted weekly notes into a "
            "Markdown status update with completed work, blockers, and next steps."
        ),
        "known_fields": {
            "input": {"source": "pasted weekly notes", "format": "markdown"},
            "output": {"format": "markdown status update"},
            "audience": "internal team",
        },
        "missing_fields": [],
        "risk_flags": [],
        "next_questions": [],
        "draft_skill_spec": draft_skill_spec if draft_skill_spec is not None else draft_skill_spec_payload(),
        "draft_acceptance_criteria": criteria if criteria is not None else [acceptance_criterion_payload()],
        "assumptions": ["No external systems are read."],
    }


def approved_audit_payload(**overrides):
    audit = {
        "decision": "approved",
        "clarity_score": 0.94,
        "feasibility_score": 0.91,
        "testability_score": 0.9,
        "risk_score": 0.12,
        "missing_requirements": [],
        "unsafe_assumptions": [],
        "required_followup_questions": [],
        "spec_patch_suggestions": ["Keep the no-external-systems constraint in the frozen spec."],
        "routing_recommendation": "codex_worker",
        "approval_rationale": "The spec is clear, feasible, and testable.",
    }
    audit.update(overrides)
    return {
        "spec_audit_report": audit,
        "feasibility_report": {
            "decision": "feasible",
            "feasibility_score": 0.91,
            "risk_score": 0.12,
            "routing_recommendation": "codex_worker",
            "required_capabilities": ["markdown_generation"],
            "missing_capabilities": [],
            "constraints": ["No external systems."],
            "risks": [],
            "assumptions": ["Input notes are provided by the user."],
            "human_review_reasons": [],
        },
    }


def human_review_audit_payload():
    return {
        "spec_audit_report": {
            "decision": "human_review_required",
            "clarity_score": 0.94,
            "feasibility_score": 0.91,
            "testability_score": 0.9,
            "risk_score": 0.8,
            "missing_requirements": [],
            "unsafe_assumptions": ["The request may involve restricted data."],
            "required_followup_questions": [],
            "spec_patch_suggestions": [],
            "routing_recommendation": "human_review",
            "approval_rationale": "A human must approve the sensitive-data boundary.",
        },
        "feasibility_report": {
            "decision": "human_review_required",
            "feasibility_score": 0.91,
            "risk_score": 0.8,
            "routing_recommendation": "human_review",
            "required_capabilities": ["markdown_generation"],
            "missing_capabilities": [],
            "constraints": ["Potential restricted data."],
            "risks": ["Sensitive data boundary requires review."],
            "assumptions": [],
            "human_review_reasons": ["Sensitive data boundary requires review."],
        },
    }


def read_json(workspace, ref):
    return json.loads(workspace.resolve_path(ref, must_exist=True).read_text(encoding="utf-8"))


def test_frontdesk_loop_api_is_exported():
    assert skillfoundry.FrontDeskLoop is FrontDeskLoop
    assert skillfoundry.FrontDeskLoopResult is FrontDeskLoopResult
    assert skillfoundry.run_frontdesk_round is run_frontdesk_round


def test_fuzzy_need_routes_to_ask_user_without_audit_or_freeze(tmp_path):
    workspace, frontdesk = make_frontdesk_workspace(tmp_path)
    elicitor_client = ScriptedModelClient(payload=needs_clarification_payload())
    auditor_client = ScriptedModelClient(payload=approved_audit_payload())

    result = run_frontdesk_round(
        frontdesk,
        elicitor_client=elicitor_client,
        auditor_client=auditor_client,
    )

    assert result.state.readiness == "needs_clarification"
    assert result.state.next_action == "ask_user"
    assert result.state.clarification_round == 1
    assert result.elicitation_report_ref == "frontdesk/elicitation_report_001.json"
    assert result.audit_report_ref is None
    assert len(elicitor_client.invocations) == 1
    assert auditor_client.invocations == []
    assert not workspace.resolve_path("frontdesk/spec_audit_report_001.json").exists()
    assert not workspace.resolve_path("frontdesk/freeze_gate_result.json").exists()


def test_clear_need_materializes_audits_and_freezes(tmp_path):
    workspace, frontdesk = make_frontdesk_workspace(tmp_path)
    result = run_frontdesk_round(
        workspace,
        elicitor_client=ScriptedModelClient(payload=ready_for_audit_payload()),
        auditor_client=ScriptedModelClient(payload=approved_audit_payload()),
    )

    assert result.status == FRONTDESK_LOOP_STATUS_ROUTE_TO_BUILD
    assert result.state.readiness == "frozen"
    assert result.state.next_action == "route_to_build"
    assert result.state.latest_elicitation_report_ref == "frontdesk/elicitation_report_001.json"
    assert result.state.latest_audit_report_ref == "frontdesk/spec_audit_report_001.json"
    assert result.state.skill_spec_ref == "skill_spec.yaml"
    assert result.state.acceptance_criteria_ref == "acceptance_criteria.yaml"
    assert result.state.verification_spec_ref == "verification_spec.yaml"
    assert result.state.freeze_gate_result_ref == "frontdesk/freeze_gate_result.json"
    assert result.state.freeze_manifest_ref == "frontdesk/freeze_manifest.json"
    assert result.materialized_artifact_refs == {
        "draft_skill_spec": "frontdesk/draft_skill_spec.yaml",
        "acceptance_criteria": "frontdesk/acceptance_criteria.yaml",
    }
    assert result.frozen_artifact_refs["skill_spec"] == "skill_spec.yaml"
    assert workspace.resolve_path("frontdesk/draft_skill_spec.yaml", must_exist=True).is_file()
    assert workspace.resolve_path("frontdesk/acceptance_criteria.yaml", must_exist=True).is_file()
    assert workspace.resolve_path("frontdesk/spec_audit_report_001.json", must_exist=True).is_file()
    assert workspace.resolve_path("frontdesk/freeze_gate_result.json", must_exist=True).is_file()
    assert workspace.resolve_path("frontdesk/freeze_manifest.json", must_exist=True).is_file()
    criteria = AcceptanceCriteriaSet.read_yaml_file(
        workspace.resolve_path("frontdesk/acceptance_criteria.yaml", must_exist=True)
    )
    assert criteria.job_id == workspace.job_id
    assert criteria.criteria[0].id == "AC-001"


def test_auditor_approved_but_freeze_gate_blocks_routes_to_ask_user(tmp_path):
    workspace, frontdesk = make_frontdesk_workspace(tmp_path)
    low_score_audit = approved_audit_payload(clarity_score=0.5)

    result = run_frontdesk_round(
        frontdesk,
        elicitor_client=ScriptedModelClient(payload=ready_for_audit_payload()),
        auditor_client=ScriptedModelClient(payload=low_score_audit),
    )

    assert result.state.readiness == "needs_clarification"
    assert result.state.next_action == "ask_user"
    assert result.state.freeze_gate_result_ref == "frontdesk/freeze_gate_result.json"
    assert result.frozen_artifact_refs == {}
    assert not workspace.resolve_path("frontdesk/freeze_manifest.json").exists()
    gate_result = read_json(workspace, "frontdesk/freeze_gate_result.json")
    assert gate_result["decision"] == "ask_user"
    assert {reason["code"] for reason in gate_result["blocking_reasons"]} == {"clarity_score_below_threshold"}


def test_high_risk_audit_routes_to_human_review(tmp_path):
    workspace, frontdesk = make_frontdesk_workspace(tmp_path)

    result = run_frontdesk_round(
        workspace,
        elicitor_client=ScriptedModelClient(payload=ready_for_audit_payload()),
        auditor_client=ScriptedModelClient(payload=human_review_audit_payload()),
    )

    assert result.status == FRONTDESK_LOOP_STATUS_HUMAN_REVIEW
    assert result.state.readiness == "human_review_required"
    assert result.state.next_action == "human_review"
    assert result.state.human_review_required is True
    assert result.state.freeze_gate_result_ref == "frontdesk/freeze_gate_result.json"
    gate_result = read_json(workspace, "frontdesk/freeze_gate_result.json")
    assert gate_result["decision"] == "human_review_required"
    assert not workspace.resolve_path("frontdesk/freeze_manifest.json").exists()


def test_round_limit_routes_to_human_review_without_model_calls(tmp_path):
    config = FrontDeskConfig(max_clarification_rounds=1)
    workspace, frontdesk = make_frontdesk_workspace(tmp_path, config=config)
    state = FrontDeskState(
        job_id=workspace.job_id,
        clarification_round=1,
        readiness="needs_clarification",
        latest_elicitation_report_ref="frontdesk/elicitation_report_001.json",
        next_action="elicit",
    )
    elicitor_client = ScriptedModelClient(payload=needs_clarification_payload())
    auditor_client = ScriptedModelClient(payload=approved_audit_payload())

    result = run_frontdesk_round(
        frontdesk,
        state=state,
        config=config,
        elicitor_client=elicitor_client,
        auditor_client=auditor_client,
    )

    assert result.status == FRONTDESK_LOOP_STATUS_HUMAN_REVIEW
    assert result.state.readiness == "human_review_required"
    assert result.state.next_action == "human_review"
    assert result.state.human_review_required is True
    assert result.failure_ref == "frontdesk/frontdesk_loop_failure_001.json"
    assert elicitor_client.invocations == []
    assert auditor_client.invocations == []
    failure = read_json(workspace, result.failure_ref)
    assert failure["failure_type"] == "max_clarification_rounds_reached"


def test_provider_schema_failure_fails_closed(tmp_path):
    workspace, frontdesk = make_frontdesk_workspace(tmp_path)

    result = run_frontdesk_round(
        workspace,
        elicitor_client=ScriptedModelClient(payload={"readiness_guess": "done"}),
        auditor_client=ScriptedModelClient(payload=approved_audit_payload()),
    )

    assert result.status == FRONTDESK_LOOP_STATUS_FAIL_CLOSED
    assert result.failed_closed is True
    assert result.state.readiness == "failed"
    assert result.state.next_action == "fail_closed"
    assert result.failure_ref == "frontdesk/elicitation_failure_001.json"
    assert not workspace.resolve_path("frontdesk/spec_audit_report_001.json").exists()


def test_ready_for_audit_with_missing_drafts_fails_closed(tmp_path):
    workspace, frontdesk = make_frontdesk_workspace(tmp_path)
    payload = ready_for_audit_payload()
    payload["draft_skill_spec"] = {}

    result = run_frontdesk_round(
        frontdesk,
        elicitor_client=ScriptedModelClient(payload=payload),
        auditor_client=ScriptedModelClient(payload=approved_audit_payload()),
    )

    assert result.status == FRONTDESK_LOOP_STATUS_FAIL_CLOSED
    assert result.state.readiness == "failed"
    assert result.failure_ref == "frontdesk/frontdesk_loop_failure_001.json"
    assert not workspace.resolve_path("frontdesk/spec_audit_report_001.json").exists()
    failure = read_json(workspace, result.failure_ref)
    assert failure["failure_type"] == "draft_materialization_failed"
    assert failure["details"]["failures"][0]["code"] == "missing_draft_skill_spec"


@pytest.mark.parametrize("raw_field", ["conversation", "raw_prompt", "raw_model_output"])
def test_loop_state_rejects_raw_fields(tmp_path, raw_field):
    workspace, frontdesk = make_frontdesk_workspace(tmp_path)
    payload = FrontDeskState(job_id=workspace.job_id).to_dict()
    payload[raw_field] = "raw"

    with pytest.raises(SchemaValidationError):
        run_frontdesk_round(
            frontdesk,
            state=payload,
            elicitor_client=ScriptedModelClient(payload=needs_clarification_payload()),
            auditor_client=ScriptedModelClient(payload=approved_audit_payload()),
        )


def test_loop_uses_injected_scripted_clients_only(tmp_path):
    _workspace, frontdesk = make_frontdesk_workspace(tmp_path)
    elicitor_client = ScriptedModelClient(payload=needs_clarification_payload())

    result = FrontDeskLoop().run_round(frontdesk, elicitor_client=elicitor_client)

    assert result.state.next_action == "ask_user"
    assert len(elicitor_client.invocations) == 1
    assert elicitor_client.invocations[0]["model"] == "skillfoundry-requirements-elicitor-fake"


def test_loop_does_not_store_raw_text_in_result_or_state(tmp_path):
    workspace, frontdesk = make_frontdesk_workspace(tmp_path)
    result = run_frontdesk_round(
        frontdesk,
        elicitor_client=ScriptedModelClient(payload=needs_clarification_payload()),
    )

    state_payload = result.state.to_dict()
    result_payload = result.to_dict()
    forbidden = {"conversation", "raw_prompt", "raw_model_output", "messages", "transcript"}
    assert forbidden.isdisjoint(state_payload)
    assert forbidden.isdisjoint(result_payload)
    assert state_payload["job_id"] == workspace.job_id
