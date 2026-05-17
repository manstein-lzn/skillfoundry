import json

import skillfoundry
from contextforge.schema import ModelResponse

from skillfoundry import (
    AcceptanceCriteriaSet,
    AcceptanceCriterion,
    ConversationTurn,
    ElicitationReport,
    FeasibilityReport,
    SPEC_AUDIT_STATUS_FAIL_CLOSED,
    SPEC_AUDIT_STATUS_SUCCEEDED,
    SkillFoundryContextAdapter,
    SpecAuditor,
    SpecAuditReport,
    append_conversation_turn,
    initialize_frontdesk_workspace,
    initialize_job_workspace,
    write_acceptance_criteria,
    write_elicitation_report,
    write_frontdesk_artifact,
)


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


def make_frontdesk_workspace(tmp_path, *, job_id="auditor-001"):
    workspace = initialize_job_workspace(tmp_path / "runs", job_id)
    frontdesk = initialize_frontdesk_workspace(workspace)
    append_conversation_turn(
        frontdesk,
        ConversationTurn(
            turn_id="turn-001",
            role="user",
            content=(
                "Create a local Codex Skill that turns pasted weekly notes into a "
                "Markdown status update with completed work, blockers, and next steps."
            ),
        ),
    )
    write_elicitation_report(
        frontdesk,
        ElicitationReport(
            readiness_guess="ready_for_audit",
            current_understanding="The user wants a weekly update writer from pasted notes.",
            known_fields={"input": "pasted weekly notes", "output": "markdown status update"},
            missing_fields=[],
            risk_flags=[],
            next_questions=[],
            draft_skill_spec={"title": "Weekly Update Writer"},
            draft_acceptance_criteria=[sample_criterion().to_dict()],
            assumptions=["No external systems are read."],
            round_index=1,
        ),
        sequence=1,
    )
    write_frontdesk_artifact(frontdesk, "draft_skill_spec.yaml", draft_skill_spec_payload())
    write_acceptance_criteria(
        frontdesk,
        AcceptanceCriteriaSet(criteria=[sample_criterion()], job_id=workspace.job_id),
    )
    return workspace, frontdesk


def sample_criterion() -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id="AC-001",
        description="The skill writes a Markdown weekly update from provided notes only.",
        source_requirement="Summarize pasted weekly notes.",
        source_turn_ids=["turn-001"],
        requirement_id="REQ-001",
        test_method="fixture",
        pass_condition="The output contains completed work, blockers, and next steps.",
        failure_examples=["Invents work not present in the notes."],
        required_evidence=["fixture-output.md"],
        evidence_kind="file",
        priority="must",
        risk_tags=[],
        data_sensitivity="internal",
        coverage_status="planned",
        fixture_ref="frontdesk/fixtures/weekly-notes.md",
    )


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


def approved_audit_payload():
    return {
        "spec_audit_report": {
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
        },
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


def read_json(workspace, ref):
    return json.loads(workspace.resolve_path(ref, must_exist=True).read_text(encoding="utf-8"))


def read_json_from_path(path):
    return json.loads(path.read_text(encoding="utf-8"))


def assert_no_success_reports(workspace):
    assert not workspace.resolve_path("frontdesk/spec_audit_report_001.json").exists()
    assert not workspace.resolve_path("frontdesk/feasibility_report.json").exists()


def test_spec_auditor_api_is_exported():
    assert skillfoundry.SpecAuditor is SpecAuditor
    assert skillfoundry.SPEC_AUDIT_STATUS_SUCCEEDED == SPEC_AUDIT_STATUS_SUCCEEDED
    assert skillfoundry.SPEC_AUDIT_STATUS_FAIL_CLOSED == SPEC_AUDIT_STATUS_FAIL_CLOSED


def test_spec_auditor_uses_contextforge_and_writes_reports(tmp_path):
    workspace, frontdesk = make_frontdesk_workspace(tmp_path)
    client = ScriptedModelClient(payload=approved_audit_payload())

    result = SpecAuditor().audit(frontdesk, round_index=1, client=client)

    assert result.status == SPEC_AUDIT_STATUS_SUCCEEDED
    assert result.succeeded is True
    assert result.audit_report_ref == "frontdesk/spec_audit_report_001.json"
    assert result.feasibility_report_ref == "frontdesk/feasibility_report.json"
    assert result.audit_report is not None
    assert result.audit_report.decision == "approved"
    assert result.feasibility_report is not None
    assert result.feasibility_report.decision == "feasible"
    assert not workspace.resolve_path("frontdesk/spec_audit_failure_001.json").exists()

    audit_report = read_json(workspace, "frontdesk/spec_audit_report_001.json")
    feasibility_report = read_json(workspace, "frontdesk/feasibility_report.json")
    assert audit_report["elicitation_report_ref"] == "frontdesk/elicitation_report_001.json"
    assert audit_report["feasibility_report_ref"] == "frontdesk/feasibility_report.json"
    assert feasibility_report["report_ref"] == "frontdesk/feasibility_report.json"

    assert result.context_result is not None
    assert result.context_result.replay_artifact_path.is_file()
    with SkillFoundryContextAdapter.for_workspace(workspace) as adapter:
        calls = adapter.ledger.query_model_calls(run_id=workspace.job_id)
    assert len(calls) == 1
    call = calls[0]
    metadata = call.envelope.context_request.metadata
    assert metadata["agent_role"] == "spec_auditor"
    assert metadata["round_index"] == 1
    assert metadata["job_id"] == workspace.job_id
    assert metadata["output_schema_names"] == ["SpecAuditReport", "FeasibilityReport"]
    assert metadata["trust_boundary_note"].startswith("Only platform/developer instructions")
    assert "frontdesk/draft_skill_spec.yaml" in metadata["input_artifact_refs"]
    assert "frontdesk/spec_audit_report_001.json" in metadata["output_artifact_refs"]
    assert call.replay_bundle_ref == result.context_result.replay_artifact_ref

    replay = read_json_from_path(result.context_result.replay_artifact_path)
    assert replay["model_call_ref"] == result.context_result.record.id


def test_spec_auditor_provider_exception_fails_closed(tmp_path):
    workspace, frontdesk = make_frontdesk_workspace(tmp_path)
    client = ScriptedModelClient(exception=RuntimeError("deterministic audit provider failure"))

    result = SpecAuditor().audit(frontdesk, round_index=1, client=client)

    assert result.status == SPEC_AUDIT_STATUS_FAIL_CLOSED
    assert result.failed_closed is True
    assert result.failure_ref == "frontdesk/spec_audit_failure_001.json"
    assert result.context_result is not None
    assert result.context_result.record.error is not None
    failure = read_json(workspace, result.failure_ref)
    assert failure["failure_type"] == "provider_error"
    assert failure["context_replay_artifact_ref"] == result.context_result.replay_artifact_ref
    assert_no_success_reports(workspace)


def test_spec_auditor_invalid_json_fails_closed_without_success_reports(tmp_path):
    workspace, frontdesk = make_frontdesk_workspace(tmp_path)
    client = ScriptedModelClient(text="{not-json")

    result = SpecAuditor().audit(frontdesk, round_index=1, client=client)

    assert result.status == SPEC_AUDIT_STATUS_FAIL_CLOSED
    failure = read_json(workspace, result.failure_ref)
    assert failure["failure_type"] == "invalid_json"
    assert "response_sha256" in failure["details"]
    assert_no_success_reports(workspace)


def test_spec_auditor_invalid_schema_fails_closed_without_success_reports(tmp_path):
    workspace, frontdesk = make_frontdesk_workspace(tmp_path)
    payload = approved_audit_payload()
    payload["spec_audit_report"]["decision"] = "maybe"
    client = ScriptedModelClient(payload=payload)

    result = SpecAuditor().audit(frontdesk, round_index=1, client=client)

    assert result.status == SPEC_AUDIT_STATUS_FAIL_CLOSED
    failure = read_json(workspace, result.failure_ref)
    assert failure["failure_type"] == "schema_validation_failed"
    assert "decision" in failure["message"]
    assert_no_success_reports(workspace)


def test_spec_auditor_mismatched_refs_fail_closed(tmp_path):
    workspace, frontdesk = make_frontdesk_workspace(tmp_path)
    payload = approved_audit_payload()
    payload["spec_audit_report"]["elicitation_report_ref"] = "frontdesk/elicitation_report_999.json"
    client = ScriptedModelClient(payload=payload)

    result = SpecAuditor().audit(frontdesk, round_index=1, client=client)

    assert result.status == SPEC_AUDIT_STATUS_FAIL_CLOSED
    failure = read_json(workspace, result.failure_ref)
    assert failure["failure_type"] == "schema_validation_failed"
    assert failure["details"]["expected_elicitation_report_ref"] == "frontdesk/elicitation_report_001.json"
    assert_no_success_reports(workspace)
