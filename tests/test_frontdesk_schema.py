import math

import pytest

from skillfoundry.frontdesk_schema import (
    AcceptanceCriteriaSet,
    AcceptanceCriterion,
    ConversationTurn,
    CoreNeedBrief,
    CoreNeedDiscoveryReport,
    CoreNeedQuestion,
    ElicitationReport,
    FeasibilityReport,
    FreezeManifest,
    FrontDeskConfig,
    FrontDeskState,
    PlanReviewRecord,
    SolutionPlan,
    SpecAuditReport,
    StructuredQuestion,
)
from skillfoundry.schema import SchemaValidationError, utc_now


HASH_A = "a" * 64
HASH_B = "b" * 64


def sample_question(question_id: str = "Q-001") -> StructuredQuestion:
    return StructuredQuestion(
        question_id=question_id,
        text="What input source should the skill summarize?",
        missing_field_path="input.source",
        reason="The builder needs an explicit data boundary.",
        priority="must",
        answer_type="enum",
        blocks_build=True,
        options=["manual_text", "git_log", "ticket_export"],
    )


def sample_criterion(criterion_id: str = "AC-001") -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id=criterion_id,
        description="The skill writes a weekly summary from the provided input only.",
        source_requirement="Summarize team work from user-provided weekly notes.",
        source_turn_ids=["turn-001"],
        requirement_id="REQ-001",
        test_method="fixture",
        pass_condition="The output contains completed work, blockers, and next steps.",
        failure_examples=["Invents work that is not present in the fixture."],
        required_evidence=["fixture-summary-output.md"],
        evidence_kind="file",
        priority="must",
        risk_tags=["input_boundary"],
        data_sensitivity="internal",
        coverage_status="planned",
        fixture_ref="frontdesk/fixtures/weekly-notes.md",
    )


def sample_objects():
    question = sample_question()
    criterion = sample_criterion()
    core_need_brief = CoreNeedBrief(
        problem_statement="Weekly updates take too long to draft manually.",
        target_user="engineering manager",
        usage_moment="Friday status reporting",
        desired_outcome="Markdown status update from pasted notes.",
        success_signal="The update includes completed work, blockers, and next steps.",
        confidence_score=0.9,
        source_turn_ids=["turn-001"],
    )
    return [
        ConversationTurn(
            turn_id="turn-001",
            role="user",
            content="I need a skill that drafts team weekly updates.",
            created_at=utc_now(),
            metadata={"source": "test"},
        ),
        question,
        ElicitationReport(
            readiness_guess="needs_clarification",
            current_understanding="The user wants weekly update drafting.",
            known_fields={"output": {"format": "markdown"}},
            missing_fields=["input.source"],
            risk_flags=["privacy_boundary_unknown"],
            next_questions=[question],
            draft_skill_spec={"title": "Weekly Update Writer"},
            draft_acceptance_criteria=[criterion.to_dict()],
            assumptions=["The user will provide the source notes."],
            conversation_ref="frontdesk/conversation.jsonl",
            round_index=1,
        ),
        core_need_brief,
        CoreNeedQuestion(
            question_id="CNQ-001",
            text="What makes the current weekly update workflow painful?",
            reason="The agent needs the core pain before planning a solution.",
        ),
        CoreNeedDiscoveryReport(
            readiness="core_need_ready",
            current_understanding="The user wants faster weekly update drafting.",
            core_need_brief=core_need_brief,
            decision_ledger_ref="frontdesk/decision_ledger.json",
            summary_ref="frontdesk/core_need_summary.md",
            round_index=1,
        ),
        SolutionPlan(
            plan_id="solution-plan-001",
            core_need_brief_ref="frontdesk/core_need_brief.json",
            summary="Build a weekly update writer from pasted notes.",
            proposed_skill_name="Weekly Update Writer",
            target_user="engineering manager",
            user_problem="Weekly updates take too long to draft manually.",
            desired_outcome="Markdown status update from pasted notes.",
            approach="Create a local Codex Skill from provided notes only.",
            implementation_outline=["Read pasted notes.", "Write the Markdown update."],
            key_decisions=["No external systems are read."],
            acceptance_summary=["The update includes completed work, blockers, and next steps."],
            status="awaiting_user_review",
        ),
        PlanReviewRecord(
            review_id="plan-review-001",
            solution_plan_ref="frontdesk/solution_plan.json",
            decision="approve",
            reviewer_id="user-1",
            reviewer_role="requesting_user",
            reason="This matches the intended workflow.",
            source_hash=HASH_A,
        ),
        criterion,
        AcceptanceCriteriaSet(criteria=[criterion], criteria_set_id="acs-001", job_id="job-1"),
        FeasibilityReport(
            decision="feasible",
            feasibility_score=0.82,
            risk_score=0.2,
            routing_recommendation="codex_worker",
            required_capabilities=["markdown_generation"],
            missing_capabilities=[],
            constraints=["No external data access."],
            risks=["Sensitive names may appear in input."],
            assumptions=["Input is user-provided."],
            human_review_reasons=[],
            report_ref="frontdesk/feasibility_report.json",
        ),
        SpecAuditReport(
            decision="approved",
            clarity_score=0.9,
            feasibility_score=0.85,
            testability_score=0.88,
            risk_score=0.15,
            missing_requirements=[],
            unsafe_assumptions=[],
            required_followup_questions=[],
            spec_patch_suggestions=["State that no external systems are read."],
            routing_recommendation="codex_worker",
            approval_rationale="The draft is clear, feasible, and testable.",
            elicitation_report_ref="frontdesk/elicitation_report_001.json",
            feasibility_report_ref="frontdesk/feasibility_report.json",
        ),
        FreezeManifest(
            conversation_summary_hash=HASH_A,
            conversation_turn_range=[1, 2],
            elicitation_report_ref="frontdesk/elicitation_report_001.json",
            spec_audit_report_ref="frontdesk/spec_audit_report_001.json",
            skill_spec_ref="skill_spec.yaml",
            acceptance_criteria_ref="acceptance_criteria.yaml",
            verification_spec_ref="verification_spec.yaml",
            worker_input_ref="worker_input.md",
            build_contract_ref="build_contract.yaml",
            artifact_hashes={"frontdesk/clarification_summary.md": HASH_B},
            freeze_gate_result_ref="frontdesk/freeze_gate_result.json",
        ),
        FrontDeskState(
            job_id="job-1",
            stage="await_user_plan_review",
            frontdesk_phase="user_review",
            clarification_round=1,
            core_need_round=1,
            readiness="awaiting_plan_review",
            latest_core_need_report_ref="frontdesk/core_need_report_001.json",
            core_need_brief_ref="frontdesk/core_need_brief.json",
            decision_ledger_ref="frontdesk/decision_ledger.json",
            solution_plan_ref="frontdesk/solution_plan.json",
            solution_plan_markdown_ref="frontdesk/solution_plan.md",
            latest_elicitation_report_ref="frontdesk/elicitation_report_001.json",
            latest_audit_report_ref="frontdesk/spec_audit_report_001.json",
            next_action="await_user_plan_review",
        ),
        FrontDeskConfig(),
    ]


@pytest.mark.parametrize("obj", sample_objects())
def test_frontdesk_schema_json_round_trip(obj):
    loaded = obj.__class__.from_json(obj.to_json())
    assert loaded.to_dict() == obj.to_dict()


@pytest.mark.parametrize("obj", sample_objects())
def test_frontdesk_schema_yaml_round_trip(obj):
    loaded = obj.__class__.from_yaml(obj.to_yaml())
    assert loaded.to_dict() == obj.to_dict()


@pytest.mark.parametrize("obj", sample_objects())
def test_frontdesk_schema_unknown_fields_fail(obj):
    payload = obj.to_dict()
    payload["unexpected"] = True
    with pytest.raises(SchemaValidationError):
        obj.__class__.from_dict(payload)


@pytest.mark.parametrize(
    "obj",
    [
        ConversationTurn(turn_id="turn-001", role="developer", content="bad role"),
        StructuredQuestion(question_id="Q-001", text="Question?", missing_field_path="x", reason="test", priority="urgent"),
        AcceptanceCriterion(id="AC-001", description="Criterion.", test_method="unit_test"),
        FeasibilityReport(decision="maybe"),
        SpecAuditReport(routing_recommendation="guess"),
        FrontDeskState(job_id="job-1", next_action="build_now"),
    ],
)
def test_frontdesk_schema_invalid_enum_values_fail(obj):
    with pytest.raises(SchemaValidationError):
        obj.to_dict()


@pytest.mark.parametrize(
    "obj",
    [
        FeasibilityReport(feasibility_score=1.1),
        SpecAuditReport(clarity_score=math.inf),
        SpecAuditReport(testability_score=-0.01),
        FrontDeskConfig(min_clarity_score=1.01),
    ],
)
def test_frontdesk_schema_invalid_score_values_fail(obj):
    with pytest.raises(SchemaValidationError):
        obj.to_dict()


def test_acceptance_criteria_duplicate_ids_fail():
    criteria = AcceptanceCriteriaSet(criteria=[sample_criterion("AC-001"), sample_criterion("AC-001")])

    with pytest.raises(SchemaValidationError):
        criteria.to_dict()


def test_frontdesk_state_rejects_raw_conversation_and_model_output_fields():
    valid = FrontDeskState(job_id="job-1", latest_elicitation_report_ref="frontdesk/elicitation_report_001.json")
    payload = valid.to_dict()
    assert "conversation" not in payload
    assert "raw_model_output" not in payload
    assert payload["latest_elicitation_report_ref"] == "frontdesk/elicitation_report_001.json"

    with pytest.raises(SchemaValidationError):
        FrontDeskState.from_dict({**payload, "conversation": [{"role": "user", "content": "raw"}]})
    with pytest.raises(SchemaValidationError):
        FrontDeskState.from_dict({**payload, "raw_model_output": {"text": "raw"}})


def test_freeze_manifest_validates_hashes_and_artifact_refs():
    manifest = sample_objects()[7]
    payload = manifest.to_dict()
    payload["conversation_summary_hash"] = "not-a-hash"
    with pytest.raises(SchemaValidationError):
        FreezeManifest.from_dict(payload)

    payload = manifest.to_dict()
    payload["elicitation_report_ref"] = "../escape.json"
    with pytest.raises(SchemaValidationError):
        FreezeManifest.from_dict(payload)

    payload = manifest.to_dict()
    payload["artifact_hashes"] = {"frontdesk/report.json": "bad"}
    with pytest.raises(SchemaValidationError):
        FreezeManifest.from_dict(payload)
