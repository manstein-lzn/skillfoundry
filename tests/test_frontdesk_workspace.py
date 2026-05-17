import pytest

from skillfoundry.frontdesk_schema import (
    AcceptanceCriteriaSet,
    AcceptanceCriterion,
    ConversationTurn,
    ElicitationReport,
    FeasibilityReport,
    FreezeManifest,
    SpecAuditReport,
    StructuredQuestion,
)
from skillfoundry.frontdesk_workspace import (
    DEFAULT_FRONTDESK_REFS,
    FRONTDESK_BUDGET_REF,
    FRONTDESK_CLARIFICATION_SUMMARY_REF,
    FRONTDESK_CONVERSATION_REF,
    FRONTDESK_DIR,
    FRONTDESK_RISK_REPORT_REF,
    append_conversation_turn,
    initialize_frontdesk_workspace,
    read_conversation_turns,
    write_acceptance_criteria,
    write_elicitation_report,
    write_feasibility_report,
    write_freeze_manifest,
    write_frontdesk_artifact,
    write_spec_audit_report,
)
from skillfoundry.schema import SchemaValidationError
from skillfoundry.security import PathSecurityError
from skillfoundry.workspace import LockedInputTamperError, initialize_job_workspace


HASH_A = "a" * 64
HASH_B = "b" * 64


def make_workspace(tmp_path):
    return initialize_job_workspace(tmp_path / "runs", "demo-001")


def sample_question() -> StructuredQuestion:
    return StructuredQuestion(
        question_id="Q-001",
        text="What source data should the skill use?",
        missing_field_path="input.source",
        reason="The data boundary must be explicit.",
    )


def sample_criterion() -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id="AC-001",
        description="The generated summary only uses provided input.",
        source_turn_ids=["turn-001"],
        requirement_id="REQ-001",
        test_method="fixture",
        required_evidence=["fixture-output.md"],
        evidence_kind="file",
        fixture_ref="frontdesk/fixtures/input.md",
    )


def test_initialize_frontdesk_workspace_creates_expected_files_and_manifest_records(tmp_path):
    workspace = make_workspace(tmp_path)
    frontdesk = initialize_frontdesk_workspace(workspace)

    assert frontdesk.root == workspace.resolve_path(FRONTDESK_DIR, must_exist=True)
    for relative_path in DEFAULT_FRONTDESK_REFS:
        assert workspace.resolve_path(relative_path, must_exist=True).is_file()

    assert workspace.resolve_path(FRONTDESK_CONVERSATION_REF, must_exist=True).read_text(encoding="utf-8") == ""
    assert workspace.resolve_path(FRONTDESK_CLARIFICATION_SUMMARY_REF, must_exist=True).read_text(encoding="utf-8")
    assert workspace.resolve_path(FRONTDESK_BUDGET_REF, must_exist=True).read_text(encoding="utf-8")
    assert workspace.resolve_path(FRONTDESK_RISK_REPORT_REF, must_exist=True).read_text(encoding="utf-8")

    manifest = workspace.read_manifest()
    frontdesk_records = [record for record in manifest.artifacts if record.path in DEFAULT_FRONTDESK_REFS]
    assert {record.path for record in frontdesk_records} == set(DEFAULT_FRONTDESK_REFS)
    assert all(record.kind == "frontdesk_artifact" for record in frontdesk_records)
    assert all(not record.locked for record in frontdesk_records)
    workspace.check_locked_inputs()


def test_append_conversation_turn_preserves_order_and_validates(tmp_path):
    workspace = make_workspace(tmp_path)
    initialize_frontdesk_workspace(workspace)

    append_conversation_turn(
        workspace,
        ConversationTurn(turn_id="turn-001", role="user", content="I need a weekly update skill."),
    )
    append_conversation_turn(
        workspace,
        ConversationTurn(turn_id="turn-002", role="assistant", content="What source data should it use?"),
    )

    turns = read_conversation_turns(workspace)
    assert [turn.turn_id for turn in turns] == ["turn-001", "turn-002"]
    assert [turn.role for turn in turns] == ["user", "assistant"]

    with pytest.raises(SchemaValidationError):
        append_conversation_turn(workspace, {"turn_id": "turn-003", "role": "builder", "content": "invalid"})
    assert [turn.turn_id for turn in read_conversation_turns(workspace)] == ["turn-001", "turn-002"]


def test_frontdesk_artifact_writes_update_manifest(tmp_path):
    workspace = make_workspace(tmp_path)
    frontdesk = initialize_frontdesk_workspace(workspace)
    question = sample_question()
    criterion = sample_criterion()

    written = [
        write_elicitation_report(
            frontdesk,
            ElicitationReport(
                current_understanding="The user wants a weekly update writer.",
                next_questions=[question],
                missing_fields=["input.source"],
                risk_flags=["input_boundary_unknown"],
            ),
        ).path,
        write_spec_audit_report(
            workspace,
            SpecAuditReport(
                decision="needs_more_clarification",
                clarity_score=0.6,
                feasibility_score=0.8,
                testability_score=0.5,
                risk_score=0.2,
                required_followup_questions=[question],
                routing_recommendation="codex_worker",
            ),
        ).path,
        write_frontdesk_artifact(workspace, "draft_skill_spec.yaml", {"title": "Weekly Update Writer"}).path,
        write_acceptance_criteria(workspace, AcceptanceCriteriaSet(criteria=[criterion], job_id=workspace.job_id)).path,
        write_feasibility_report(
            workspace,
            FeasibilityReport(decision="feasible", feasibility_score=0.8, risk_score=0.2, routing_recommendation="codex_worker"),
        ).path,
        write_frontdesk_artifact(workspace, "freeze_gate_result.json", {"decision": "ask_user", "blocking_reasons": []}).path,
        write_freeze_manifest(
            workspace,
            FreezeManifest(
                conversation_summary_hash=HASH_A,
                conversation_turn_range=[1, 1],
                elicitation_report_ref="frontdesk/elicitation_report_001.json",
                spec_audit_report_ref="frontdesk/spec_audit_report_001.json",
                skill_spec_ref="skill_spec.yaml",
                acceptance_criteria_ref="acceptance_criteria.yaml",
                verification_spec_ref="verification_spec.yaml",
                worker_input_ref="worker_input.md",
                build_contract_ref="build_contract.yaml",
                artifact_hashes={"frontdesk/clarification_summary.md": HASH_B},
            ),
        ).path,
    ]

    manifest = workspace.read_manifest()
    manifest_paths = {record.path for record in manifest.artifacts}
    assert set(written).issubset(manifest_paths)
    for relative_path in written:
        record = manifest.record_for_path(relative_path)
        assert record is not None
        assert record.kind == "frontdesk_artifact"
        assert record.locked is False
        assert workspace.resolve_path(relative_path, must_exist=True).is_file()
    workspace.check_locked_inputs()


@pytest.mark.parametrize("bad_path", ["../escape.json", "/tmp/escape.json", "frontdesk/../escape.json"])
def test_frontdesk_path_traversal_is_rejected(tmp_path, bad_path):
    workspace = make_workspace(tmp_path)
    initialize_frontdesk_workspace(workspace)

    with pytest.raises(PathSecurityError):
        write_frontdesk_artifact(workspace, bad_path, {"bad": True})


def test_locked_input_checks_still_pass_after_frontdesk_initialization(tmp_path):
    workspace = make_workspace(tmp_path)
    initialize_frontdesk_workspace(workspace)

    workspace.check_locked_inputs()

    worker_input = workspace.resolve_path("worker_input.md", must_exist=True)
    worker_input.write_text(worker_input.read_text(encoding="utf-8") + "\nTampered.\n", encoding="utf-8")
    with pytest.raises(LockedInputTamperError):
        workspace.check_locked_inputs()
