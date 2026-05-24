import json

import pytest

import skillfoundry
from skillfoundry import (
    AcceptanceCriteriaSet,
    AcceptanceCriterion,
    BUILD_NODE_CONTRACT_REF,
    CONTRACT_MANIFEST_REF,
    ConversationTurn,
    ElicitationReport,
    FeasibilityReport,
    FREEZE_GATE_DECISION_ASK_USER,
    FREEZE_GATE_DECISION_FREEZE,
    FREEZE_GATE_DECISION_HUMAN_REVIEW_REQUIRED,
    GOAL_CONTRACT_REF,
    FrontDeskFreezeGate,
    LockedInputTamperError,
    PlanReviewRecord,
    SolutionPlan,
    SpecAuditReport,
    VERIFICATION_GATE_REF,
    append_conversation_turn,
    initialize_frontdesk_workspace,
    initialize_job_workspace,
    sha256_file,
    write_acceptance_criteria,
    write_elicitation_report,
    write_feasibility_report,
    write_frontdesk_artifact,
    write_spec_audit_report,
)
from skillfoundry.context import SkillFoundryContextAdapter
from skillfoundry.schema import BuildContract, SkillSpec, VerificationSpec


def make_freezable_frontdesk_workspace(
    tmp_path,
    *,
    job_id="freeze-001",
    criterion=None,
    audit_report=None,
    feasibility_report=None,
    elicitation_report=None,
    draft_skill_spec=None,
    risk_report=None,
):
    workspace = initialize_job_workspace(tmp_path / "runs", job_id)
    frontdesk = initialize_frontdesk_workspace(workspace)
    write_frontdesk_artifact(
        frontdesk,
        "risk_report.json",
        risk_report
        or {
            "schema_version": "skillfoundry.frontdesk_risk_report.v1",
            "risk_flags": [],
            "redaction_status": "complete",
            "data_sensitivity": "internal",
            "provider_usage": {
                "usage_available": False,
                "usage_unavailable_reason": "Fixture frontdesk run does not expose aggregate provider usage.",
            },
        },
    )
    append_conversation_turn(
        frontdesk,
        ConversationTurn(
            turn_id="turn-001",
            role="user",
            content=(
                "Create a local Codex Skill that turns pasted weekly notes into a "
                "Markdown status update for my internal team."
            ),
        ),
    )
    criterion = criterion or sample_criterion()
    write_elicitation_report(
        frontdesk,
        elicitation_report
        or ElicitationReport(
            readiness_guess="ready_for_audit",
            current_understanding="The user wants a weekly update writer from pasted notes.",
            known_fields={"input": "pasted weekly notes", "output": "markdown status update"},
            missing_fields=[],
            risk_flags=[],
            next_questions=[],
            draft_skill_spec=draft_skill_spec_payload(),
            draft_acceptance_criteria=[criterion.to_dict()],
            assumptions=["No external systems are read."],
            round_index=1,
        ),
        sequence=1,
    )
    write_frontdesk_artifact(frontdesk, "draft_skill_spec.yaml", draft_skill_spec or draft_skill_spec_payload())
    write_acceptance_criteria(frontdesk, AcceptanceCriteriaSet(criteria=[criterion], job_id=workspace.job_id))
    write_spec_audit_report(
        frontdesk,
        audit_report or approved_audit_report(),
        sequence=1,
    )
    write_feasibility_report(
        frontdesk,
        feasibility_report or feasible_report(),
    )
    write_frontdesk_artifact(
        frontdesk,
        "core_need_brief.json",
        {
            "schema_version": "skillfoundry.core_need_brief.v1",
            "problem_statement": "The user wants a weekly update writer from pasted notes.",
            "target_user": "internal team member",
            "usage_moment": "when preparing a weekly status update",
            "desired_outcome": "a Markdown status update with completed work, blockers, and next steps",
            "success_signal": "The output contains completed work, blockers, and next steps.",
            "confidence_score": 0.9,
        },
    )
    plan = SolutionPlan(
        plan_id="solution-plan-001",
        core_need_brief_ref="frontdesk/core_need_brief.json",
        summary="The user wants a weekly update writer from pasted notes.",
        proposed_skill_name="Weekly Update Writer",
        target_user="internal team member",
        user_problem="Manual weekly status writing is repetitive.",
        desired_outcome="Markdown weekly update.",
        approach="Create a local Codex Skill from pasted notes only.",
        implementation_outline=["Read pasted notes.", "Write Markdown status update.", "Verify against fixture output."],
        key_decisions=["No external systems are read."],
        acceptance_summary=["The output contains completed work, blockers, and next steps."],
        risks=[],
        open_confirmation_items=[],
        status="awaiting_user_review",
    )
    write_frontdesk_artifact(frontdesk, "solution_plan.json", plan)
    write_frontdesk_artifact(frontdesk, "solution_plan.md", "# Solution Plan\n\nWeekly Update Writer\n")
    plan_hash = sha256_file(workspace.resolve_path("frontdesk/solution_plan.json", must_exist=True))
    write_frontdesk_artifact(
        frontdesk,
        "plan_review_001.json",
        PlanReviewRecord(
            review_id="plan-review-001",
            solution_plan_ref="frontdesk/solution_plan.json",
            decision="approve",
            reviewer_id="test-user",
            reviewer_role="requesting_user",
            reason="Approved for freeze.",
            source_hash=plan_hash,
        ),
    )
    return workspace, frontdesk


def sample_criterion(**overrides) -> AcceptanceCriterion:
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
    return AcceptanceCriterion(**payload)


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


def approved_audit_report(**overrides) -> SpecAuditReport:
    payload = {
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
        "elicitation_report_ref": "frontdesk/elicitation_report_001.json",
        "feasibility_report_ref": "frontdesk/feasibility_report.json",
    }
    payload.update(overrides)
    return SpecAuditReport(**payload)


def feasible_report(**overrides) -> FeasibilityReport:
    payload = {
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
        "report_ref": "frontdesk/feasibility_report.json",
    }
    payload.update(overrides)
    return FeasibilityReport(**payload)


def read_json(workspace, ref):
    return json.loads(workspace.resolve_path(ref, must_exist=True).read_text(encoding="utf-8"))


def reason_codes(result):
    return {reason["code"] for reason in result.blocking_reasons}


def root_hashes(workspace):
    refs = ["skill_spec.yaml", "verification_spec.yaml", "worker_input.md", "build_contract.yaml"]
    return {ref: sha256_file(workspace.resolve_path(ref, must_exist=True)) for ref in refs}


def test_frontdesk_freeze_gate_api_is_exported():
    assert skillfoundry.FrontDeskFreezeGate is FrontDeskFreezeGate
    assert skillfoundry.FREEZE_GATE_DECISION_FREEZE == FREEZE_GATE_DECISION_FREEZE


def test_freeze_gate_freezes_approved_spec_and_writes_manifest_and_locked_records(tmp_path):
    workspace, frontdesk = make_freezable_frontdesk_workspace(tmp_path)

    result = FrontDeskFreezeGate().evaluate_and_freeze(frontdesk, round_index=1)

    assert result.decision == FREEZE_GATE_DECISION_FREEZE
    assert result.frozen is True
    assert result.blocking_reasons == []
    assert result.freeze_gate_result_ref == "frontdesk/freeze_gate_result.json"
    assert result.freeze_manifest_ref == "frontdesk/freeze_manifest.json"
    assert result.next_action == "route_to_build"

    for ref in (
        "frontdesk/budget.json",
        "frontdesk/risk_report.json",
        "frontdesk/core_need_brief.json",
        "frontdesk/solution_plan.json",
        "frontdesk/solution_plan.md",
        "frontdesk/plan_review_001.json",
        "skill_spec.yaml",
        "acceptance_criteria.yaml",
        "verification_spec.yaml",
        "worker_input.md",
        "build_contract.yaml",
        GOAL_CONTRACT_REF,
        BUILD_NODE_CONTRACT_REF,
        VERIFICATION_GATE_REF,
        CONTRACT_MANIFEST_REF,
        "frontdesk/freeze_gate_result.json",
        "frontdesk/freeze_manifest.json",
    ):
        assert workspace.resolve_path(ref, must_exist=True).is_file()

    gate_result = read_json(workspace, "frontdesk/freeze_gate_result.json")
    assert gate_result["decision"] == "freeze"
    assert gate_result["frozen_artifact_refs"]["acceptance_criteria"] == "acceptance_criteria.yaml"
    assert gate_result["frozen_artifact_refs"]["goal_contract"] == GOAL_CONTRACT_REF
    assert gate_result["frozen_artifact_refs"]["build_node_contract"] == BUILD_NODE_CONTRACT_REF
    assert gate_result["frozen_artifact_refs"]["verification_gate"] == VERIFICATION_GATE_REF
    assert gate_result["frozen_artifact_refs"]["contract_manifest"] == CONTRACT_MANIFEST_REF

    freeze_manifest = read_json(workspace, "frontdesk/freeze_manifest.json")
    assert freeze_manifest["elicitation_report_ref"] == "frontdesk/elicitation_report_001.json"
    assert freeze_manifest["spec_audit_report_ref"] == "frontdesk/spec_audit_report_001.json"
    for ref in (
        "frontdesk/budget.json",
        "frontdesk/risk_report.json",
        "frontdesk/core_need_brief.json",
        "frontdesk/solution_plan.json",
        "frontdesk/solution_plan.md",
        "frontdesk/plan_review_001.json",
        "skill_spec.yaml",
        "acceptance_criteria.yaml",
        "verification_spec.yaml",
        "worker_input.md",
        "build_contract.yaml",
        GOAL_CONTRACT_REF,
        BUILD_NODE_CONTRACT_REF,
        VERIFICATION_GATE_REF,
        CONTRACT_MANIFEST_REF,
    ):
        assert ref in freeze_manifest["artifact_hashes"]
        assert freeze_manifest["artifact_hashes"][ref] == sha256_file(workspace.resolve_path(ref, must_exist=True))

    contract_manifest = read_json(workspace, CONTRACT_MANIFEST_REF)
    goal_contract = read_json(workspace, GOAL_CONTRACT_REF)
    node_contract = read_json(workspace, BUILD_NODE_CONTRACT_REF)
    assert "frontdesk/conversation.jsonl" in contract_manifest["excluded_artifacts"]
    assert goal_contract["metadata"]["raw_conversation_included"] is False
    assert node_contract["metadata"]["raw_conversation_forbidden"] is True

    manifest = workspace.read_manifest()
    for ref in (
        "skill_spec.yaml",
        "acceptance_criteria.yaml",
        "verification_spec.yaml",
        "worker_input.md",
        "build_contract.yaml",
    ):
        record = manifest.record_for_path(ref)
        assert record is not None
        assert record.kind == "locked_input"
        assert record.locked is True
        assert record.sha256 == sha256_file(workspace.resolve_path(ref, must_exist=True))

    skill_spec = SkillSpec.read_yaml_file(workspace.resolve_path("skill_spec.yaml", must_exist=True))
    verification_spec = VerificationSpec.read_yaml_file(workspace.resolve_path("verification_spec.yaml", must_exist=True))
    build_contract = BuildContract.read_yaml_file(workspace.resolve_path("build_contract.yaml", must_exist=True))
    assert skill_spec.skill_id == "weekly-update-writer"
    assert "AC-001" in verification_spec.acceptance_criteria[0]
    assert build_contract.locked_input_hashes["acceptance_criteria.yaml"] == sha256_file(
        workspace.resolve_path("acceptance_criteria.yaml", must_exist=True)
    )

    workspace.check_locked_inputs()
    acceptance_path = workspace.resolve_path("acceptance_criteria.yaml", must_exist=True)
    acceptance_path.write_text(acceptance_path.read_text(encoding="utf-8") + "\ntamper\n", encoding="utf-8")
    with pytest.raises(LockedInputTamperError):
        workspace.check_locked_inputs()


def test_freeze_gate_blocks_when_auditor_not_approved_and_does_not_overwrite_root_inputs(tmp_path):
    audit = approved_audit_report(decision="needs_more_clarification")
    workspace, frontdesk = make_freezable_frontdesk_workspace(tmp_path, audit_report=audit)
    before = root_hashes(workspace)

    result = FrontDeskFreezeGate().evaluate_and_freeze(frontdesk, round_index=1)

    assert result.decision == FREEZE_GATE_DECISION_ASK_USER
    assert "audit_not_approved" in reason_codes(result)
    assert root_hashes(workspace) == before
    assert not workspace.resolve_path("frontdesk/freeze_manifest.json").exists()
    assert not (workspace.root / GOAL_CONTRACT_REF).exists()
    assert not (workspace.root / BUILD_NODE_CONTRACT_REF).exists()
    assert not (workspace.root / VERIFICATION_GATE_REF).exists()
    assert not (workspace.root / CONTRACT_MANIFEST_REF).exists()
    gate_result = read_json(workspace, "frontdesk/freeze_gate_result.json")
    assert gate_result["decision"] == "ask_user"
    assert gate_result["blocking_reasons"]


def test_freeze_gate_blocks_without_approved_solution_plan_review(tmp_path):
    workspace, frontdesk = make_freezable_frontdesk_workspace(tmp_path)
    workspace.resolve_path("frontdesk/plan_review_001.json", must_exist=True).unlink()

    result = FrontDeskFreezeGate().evaluate_and_freeze(frontdesk, round_index=1)

    assert result.decision == FREEZE_GATE_DECISION_ASK_USER
    assert "missing_plan_review_record" in reason_codes(result)
    assert not workspace.resolve_path("frontdesk/freeze_manifest.json").exists()


def test_freeze_gate_blocks_when_score_thresholds_are_not_met(tmp_path):
    audit = approved_audit_report(clarity_score=0.6, testability_score=0.5)
    workspace, frontdesk = make_freezable_frontdesk_workspace(tmp_path, audit_report=audit)

    result = FrontDeskFreezeGate().evaluate_and_freeze(frontdesk, round_index=1)

    assert result.decision == FREEZE_GATE_DECISION_ASK_USER
    codes = reason_codes(result)
    assert "clarity_score_below_threshold" in codes
    assert "testability_score_below_threshold" in codes
    assert not workspace.resolve_path("frontdesk/freeze_manifest.json").exists()


def test_freeze_gate_blocks_when_must_criteria_lack_evidence(tmp_path):
    criterion = sample_criterion(required_evidence=[], fixture_ref=None, verifier_check_id=None)
    workspace, frontdesk = make_freezable_frontdesk_workspace(tmp_path, criterion=criterion)

    result = FrontDeskFreezeGate().evaluate_and_freeze(frontdesk, round_index=1)

    assert result.decision == FREEZE_GATE_DECISION_ASK_USER
    assert "must_criterion_missing_evidence" in reason_codes(result)
    assert not workspace.resolve_path("frontdesk/freeze_manifest.json").exists()


def test_freeze_gate_blocks_when_must_criterion_uses_only_llm_judge(tmp_path):
    criterion = sample_criterion(
        test_method="llm_judge",
        required_evidence=["model_judge"],
        evidence_kind="model_judge",
        fixture_ref=None,
        verifier_check_id=None,
    )
    workspace, frontdesk = make_freezable_frontdesk_workspace(tmp_path, criterion=criterion)

    result = FrontDeskFreezeGate().evaluate_and_freeze(frontdesk, round_index=1)

    assert result.decision == FREEZE_GATE_DECISION_ASK_USER
    assert "must_criterion_llm_judge_only" in reason_codes(result)
    assert not workspace.resolve_path("frontdesk/freeze_manifest.json").exists()


def test_freeze_gate_blocks_when_redaction_is_not_complete(tmp_path):
    workspace, frontdesk = make_freezable_frontdesk_workspace(
        tmp_path,
        risk_report={
            "schema_version": "skillfoundry.frontdesk_risk_report.v1",
            "risk_flags": [],
            "redaction_status": "not_started",
            "data_sensitivity": "internal",
        },
    )

    result = FrontDeskFreezeGate().evaluate_and_freeze(frontdesk, round_index=1)

    assert result.decision == FREEZE_GATE_DECISION_HUMAN_REVIEW_REQUIRED
    assert "redaction_not_complete" in reason_codes(result)
    assert not workspace.resolve_path("frontdesk/freeze_manifest.json").exists()


def test_freeze_gate_routes_confidential_data_without_policy_to_human_review(tmp_path):
    criterion = sample_criterion(data_sensitivity="confidential")
    workspace, frontdesk = make_freezable_frontdesk_workspace(tmp_path, criterion=criterion)

    result = FrontDeskFreezeGate().evaluate_and_freeze(frontdesk, round_index=1)

    assert result.decision == FREEZE_GATE_DECISION_HUMAN_REVIEW_REQUIRED
    assert "sensitive_data_requires_risk_policy" in reason_codes(result)
    assert not workspace.resolve_path("frontdesk/freeze_manifest.json").exists()


def test_freeze_gate_blocks_when_frontdesk_budget_evidence_is_exceeded(tmp_path):
    workspace, frontdesk = make_freezable_frontdesk_workspace(
        tmp_path,
        risk_report={
            "schema_version": "skillfoundry.frontdesk_risk_report.v1",
            "risk_flags": [],
            "redaction_status": "complete",
            "data_sensitivity": "internal",
            "provider_usage": {
                "usage_available": True,
                "model_call_count": 999,
                "total_tokens": 999_999,
                "cost_usd": 999.0,
            },
        },
    )

    result = FrontDeskFreezeGate().evaluate_and_freeze(frontdesk, round_index=1)

    assert result.decision == FREEZE_GATE_DECISION_HUMAN_REVIEW_REQUIRED
    codes = reason_codes(result)
    assert "frontdesk_model_call_budget_exceeded" in codes
    assert "frontdesk_token_budget_exceeded" not in codes
    assert "frontdesk_cost_budget_exceeded" in codes
    assert not workspace.resolve_path("frontdesk/freeze_manifest.json").exists()


def test_freeze_gate_blocks_when_explicit_frontdesk_token_budget_is_exceeded(tmp_path):
    workspace, frontdesk = make_freezable_frontdesk_workspace(
        tmp_path,
        risk_report={
            "schema_version": "skillfoundry.frontdesk_risk_report.v1",
            "risk_flags": [],
            "redaction_status": "complete",
            "data_sensitivity": "internal",
            "provider_usage": {
                "usage_available": True,
                "model_call_count": 1,
                "total_tokens": 101,
                "cost_usd": 0.0,
            },
        },
    )
    write_frontdesk_artifact(frontdesk, "budget.json", {"max_total_tokens": 100})

    result = FrontDeskFreezeGate().evaluate_and_freeze(frontdesk, round_index=1)

    assert result.decision == FREEZE_GATE_DECISION_HUMAN_REVIEW_REQUIRED
    codes = reason_codes(result)
    assert "frontdesk_token_budget_exceeded" in codes
    assert not workspace.resolve_path("frontdesk/freeze_manifest.json").exists()


def test_freeze_gate_blocks_when_usage_unavailable_reason_is_missing(tmp_path):
    workspace, frontdesk = make_freezable_frontdesk_workspace(
        tmp_path,
        risk_report={
            "schema_version": "skillfoundry.frontdesk_risk_report.v1",
            "risk_flags": [],
            "redaction_status": "complete",
            "data_sensitivity": "internal",
            "provider_usage": {
                "usage_available": False,
            },
        },
    )

    result = FrontDeskFreezeGate().evaluate_and_freeze(frontdesk, round_index=1)

    assert result.decision == FREEZE_GATE_DECISION_HUMAN_REVIEW_REQUIRED
    assert "frontdesk_usage_unavailable_reason_missing" in reason_codes(result)
    assert not workspace.resolve_path("frontdesk/freeze_manifest.json").exists()


def test_freeze_gate_sends_manual_must_criteria_to_human_review(tmp_path):
    criterion = sample_criterion(
        test_method="manual_check",
        required_evidence=["reviewer-note.md"],
        evidence_kind="human_note",
        manual_authority="qa-lead",
        fixture_ref=None,
    )
    workspace, frontdesk = make_freezable_frontdesk_workspace(tmp_path, criterion=criterion)

    result = FrontDeskFreezeGate().evaluate_and_freeze(frontdesk, round_index=1)

    assert result.decision == FREEZE_GATE_DECISION_HUMAN_REVIEW_REQUIRED
    assert "must_criterion_requires_human_review" in reason_codes(result)
    gate_result = read_json(workspace, "frontdesk/freeze_gate_result.json")
    assert gate_result["next_action"] == "human_review"
    assert not workspace.resolve_path("frontdesk/freeze_manifest.json").exists()


def test_freeze_gate_is_deterministic_and_does_not_call_model_clients(tmp_path, monkeypatch):
    workspace, frontdesk = make_freezable_frontdesk_workspace(tmp_path)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("FrontDeskFreezeGate must not call owned LLMs")

    monkeypatch.setattr(SkillFoundryContextAdapter, "call_owned_llm", fail_if_called)

    result = FrontDeskFreezeGate().evaluate_and_freeze(workspace, round_index=1)

    assert result.decision == FREEZE_GATE_DECISION_FREEZE
