from __future__ import annotations

import json

from contextforge import ContextLedger

import skillfoundry
from skillfoundry import (
    AcceptanceCriteriaSet,
    FRONTDESK_ACCEPTANCE_CRITERIA_REF,
    FRONTDESK_CORE_NEED_BRIEF_REF,
    FRONTDESK_CORE_NEED_REPORT_REF,
    FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF,
    FRONTDESK_CORE_NEED_RUNTIME_STATE_REF,
    FRONTDESK_DRAFT_SKILL_SPEC_REF,
    FRONTDESK_FEASIBILITY_REPORT_REF,
    FRONTDESK_GOAL_RUNTIME_LEDGER_REF,
    FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION,
    FRONTDESK_PLAN_REVIEW_REF,
    FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF,
    FRONTDESK_SOLUTION_PLAN_REF,
    FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF,
    FRONTDESK_SOLUTION_PLAN_RUNTIME_STATE_REF,
    FRONTDESK_SPEC_AUDIT_FAILURE_REF,
    FRONTDESK_SPEC_AUDIT_REPORT_REF,
    FRONTDESK_SPEC_AUDIT_RUNTIME_RESULT_REF,
    FRONTDESK_SPEC_AUDIT_RUNTIME_STATE_REF,
    FRONTDESK_V2_GOAL_CONTRACT_REF,
    CORE_NEED_DISCOVERY_NODE_ID,
    SOLUTION_PLANNER_NODE_ID,
    SPEC_AUDITOR_NODE_ID,
    ConversationTurn,
    PlanReviewRecord,
    initialize_frontdesk_workspace,
    initialize_job_workspace,
    sha256_file,
    write_frontdesk_artifact,
    run_frontdesk_core_need_goal_harness,
    run_frontdesk_solution_planner_goal_harness,
    run_frontdesk_spec_auditor_goal_harness,
)


CREATED_AT = "2026-05-22T00:00:00Z"


def _frontdesk_workspace(tmp_path, *, marker: str = "RAW_FRONTDESK_MARKER", seed_solution_plan: bool = True):
    workspace = initialize_job_workspace(tmp_path / "runs", "frontdesk-goal-runtime")
    frontdesk = initialize_frontdesk_workspace(workspace)
    frontdesk.append_conversation_turn(
        ConversationTurn(
            turn_id="turn-001",
            role="user",
            content=f"Please build a skill. {marker}",
        )
    )
    write_frontdesk_artifact(
        frontdesk,
        "clarification_summary.md",
        "# Clarification Summary\n\nThe user needs a governed skill requirement.\n",
    )
    write_frontdesk_artifact(
        frontdesk,
        "risk_report.json",
        {
            "schema_version": "skillfoundry.frontdesk_risk_report.v1",
            "risk_flags": [],
            "redaction_status": "complete",
            "provider_usage": {
                "usage_available": False,
                "usage_unavailable_reason": "Offline Front Desk fixture does not call a provider.",
            },
        },
    )
    if seed_solution_plan:
        write_frontdesk_artifact(
            frontdesk,
            "solution_plan.json",
            {
                "schema_version": "skillfoundry.solution_plan.v1",
                "plan_id": "plan-001",
                "status": "approved",
                "summary": "Build a governed local skill.",
            },
        )
    return workspace, frontdesk


def test_frontdesk_goal_runtime_api_is_exported() -> None:
    assert skillfoundry.run_frontdesk_core_need_goal_harness is run_frontdesk_core_need_goal_harness
    assert skillfoundry.run_frontdesk_solution_planner_goal_harness is run_frontdesk_solution_planner_goal_harness
    assert skillfoundry.run_frontdesk_spec_auditor_goal_harness is run_frontdesk_spec_auditor_goal_harness
    assert skillfoundry.FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION == FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION


def test_frontdesk_core_need_runs_through_goal_harness_without_raw_conversation(tmp_path) -> None:
    marker = "RAW_CONVERSATION_SHOULD_NOT_ENTER_FRONTDESK_PROMPT"
    workspace, frontdesk = _frontdesk_workspace(tmp_path, marker=marker, seed_solution_plan=False)

    result = run_frontdesk_core_need_goal_harness(frontdesk, created_at=CREATED_AT)

    assert workspace.resolve_path(FRONTDESK_V2_GOAL_CONTRACT_REF, must_exist=True).is_file()
    assert workspace.resolve_path(FRONTDESK_GOAL_RUNTIME_LEDGER_REF, must_exist=True).is_file()
    assert workspace.resolve_path(FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF, must_exist=True).is_file()
    assert workspace.resolve_path(FRONTDESK_CORE_NEED_RUNTIME_STATE_REF, must_exist=True).is_file()
    assert workspace.resolve_path(FRONTDESK_CORE_NEED_BRIEF_REF, must_exist=True).is_file()
    assert workspace.resolve_path(FRONTDESK_CORE_NEED_REPORT_REF, must_exist=True).is_file()

    assert result.harness_result.worker_run.worker_kind == "fake_model"
    assert result.harness_result.worker_run.status == "completed"
    assert result.goal_run.status == "completed"
    assert result.goal_run.checkpoint_ids
    assert result.runtime_state["contextforge"]["checkpoint_ids"] == result.goal_run.checkpoint_ids
    assert result.runtime_result["usage"]["usage_available"] is False
    assert result.runtime_result["usage"]["usage_unavailable_reason"] == (
        "Front Desk deterministic Goal Harness fixture does not call a provider."
    )

    ledger = ContextLedger.connect(workspace.resolve_path(FRONTDESK_GOAL_RUNTIME_LEDGER_REF, must_exist=True))
    try:
        context_view = ledger.get_context_view(result.harness_result.compiled_context.context_view.context_view_id)
        prompt_view, _blocks = ledger.get_prompt_view(result.harness_result.compiled_context.prompt_view.id)
        assert ledger.get_prompt_cache_plan(result.harness_result.compiled_context.cache_plan.cache_plan_id)
        assert ledger.get_worker_run(result.harness_result.worker_run.worker_run_id)
        assert ledger.get_goal_run_record(result.goal_run.goal_run_id)

        included = set(context_view.included_item_ids)
        forbidden = set(context_view.forbidden_item_ids)
        assert f"{workspace.job_id}:frontdesk_clarification_summary" in included
        assert f"{workspace.job_id}:frontdesk_risk_report" in included
        assert f"{workspace.job_id}:frontdesk_budget" in included
        assert f"{workspace.job_id}:raw_frontdesk_conversation" in forbidden
        assert f"{workspace.job_id}:raw_frontdesk_conversation" not in included
        rendered_prompt = "\n".join(message.content for message in prompt_view.messages)
    finally:
        ledger.close()

    state_text = json.dumps(result.runtime_state, sort_keys=True)
    result_text = json.dumps(result.runtime_result, sort_keys=True)
    assert marker not in rendered_prompt
    assert marker not in state_text
    assert marker not in result_text
    assert "conversation.jsonl" not in state_text
    assert result.runtime_state["raw_conversation_included"] is False
    assert result.runtime_result["trust_boundaries"]["raw_conversation_included"] is False


def test_frontdesk_core_need_worker_output_is_governed_refs_only(tmp_path) -> None:
    workspace, frontdesk = _frontdesk_workspace(tmp_path, seed_solution_plan=False)

    result = run_frontdesk_core_need_goal_harness(frontdesk, created_at=CREATED_AT)

    report = json.loads(workspace.resolve_path(FRONTDESK_CORE_NEED_REPORT_REF, must_exist=True).read_text())
    brief = json.loads(workspace.resolve_path(FRONTDESK_CORE_NEED_BRIEF_REF, must_exist=True).read_text())
    assert report["readiness"] == "core_need_ready"
    assert report["core_need_brief"]["problem_statement"] == brief["problem_statement"]
    assert result.harness_result.worker_run.metadata["worker_self_report_is_not_acceptance"] is True
    assert result.harness_result.worker_run.metadata["raw_conversation_included"] is False
    assert result.runtime_result["refs"]["core_need_brief"] == FRONTDESK_CORE_NEED_BRIEF_REF
    assert result.runtime_result["refs"]["core_need_report"] == FRONTDESK_CORE_NEED_REPORT_REF
    assert "core_need_brief" in result.runtime_result["hashes"]
    assert "core_need_report" in result.runtime_result["hashes"]
    assert result.runtime_state["stage"] == CORE_NEED_DISCOVERY_NODE_ID


def test_frontdesk_solution_planner_runs_after_core_need_without_raw_conversation(tmp_path) -> None:
    marker = "RAW_CONVERSATION_SHOULD_NOT_ENTER_SOLUTION_PLANNER_PROMPT"
    workspace, frontdesk = _frontdesk_workspace(tmp_path, marker=marker)
    run_frontdesk_core_need_goal_harness(frontdesk, created_at=CREATED_AT)

    result = run_frontdesk_solution_planner_goal_harness(frontdesk, created_at=CREATED_AT)

    assert workspace.resolve_path(FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF, must_exist=True).is_file()
    assert workspace.resolve_path(FRONTDESK_SOLUTION_PLAN_RUNTIME_STATE_REF, must_exist=True).is_file()
    assert workspace.resolve_path(FRONTDESK_SOLUTION_PLAN_REF, must_exist=True).is_file()
    assert workspace.resolve_path(FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF, must_exist=True).is_file()
    assert workspace.resolve_path(FRONTDESK_DRAFT_SKILL_SPEC_REF, must_exist=True).is_file()
    assert workspace.resolve_path(FRONTDESK_ACCEPTANCE_CRITERIA_REF, must_exist=True).is_file()

    assert result.harness_result.worker_run.worker_kind == "fake_model"
    assert result.harness_result.worker_run.status == "completed"
    assert result.goal_run.status == "completed"
    assert result.runtime_state["stage"] == SOLUTION_PLANNER_NODE_ID
    assert result.runtime_state["refs"]["core_need_brief"] == FRONTDESK_CORE_NEED_BRIEF_REF
    assert result.runtime_state["refs"]["solution_plan"] == FRONTDESK_SOLUTION_PLAN_REF
    assert result.runtime_result["usage"]["usage_available"] is False
    assert result.runtime_result["trust_boundaries"]["raw_conversation_included"] is False

    ledger = ContextLedger.connect(workspace.resolve_path(FRONTDESK_GOAL_RUNTIME_LEDGER_REF, must_exist=True))
    try:
        context_view = ledger.get_context_view(result.harness_result.compiled_context.context_view.context_view_id)
        prompt_view, _blocks = ledger.get_prompt_view(result.harness_result.compiled_context.prompt_view.id)
        included = set(context_view.included_item_ids)
        forbidden = set(context_view.forbidden_item_ids)
        assert f"{workspace.job_id}:{SOLUTION_PLANNER_NODE_ID}:frontdesk_core_need_brief" in included
        assert f"{workspace.job_id}:{SOLUTION_PLANNER_NODE_ID}:raw_frontdesk_conversation" in forbidden
        assert f"{workspace.job_id}:{SOLUTION_PLANNER_NODE_ID}:raw_frontdesk_conversation" not in included
        rendered_prompt = "\n".join(message.content for message in prompt_view.messages)
    finally:
        ledger.close()

    state_text = json.dumps(result.runtime_state, sort_keys=True)
    result_text = json.dumps(result.runtime_result, sort_keys=True)
    core_need_text = workspace.resolve_path(FRONTDESK_CORE_NEED_BRIEF_REF, must_exist=True).read_text(encoding="utf-8")
    assert "governed skill requirement" in core_need_text
    assert marker not in rendered_prompt
    assert marker not in state_text
    assert marker not in result_text
    assert "conversation.jsonl" not in state_text
    assert "conversation.jsonl" not in result_text


def test_frontdesk_solution_planner_output_is_user_review_draft_not_acceptance(tmp_path) -> None:
    workspace, frontdesk = _frontdesk_workspace(tmp_path)
    run_frontdesk_core_need_goal_harness(frontdesk, created_at=CREATED_AT)

    result = run_frontdesk_solution_planner_goal_harness(frontdesk, created_at=CREATED_AT)

    solution_plan = json.loads(workspace.resolve_path(FRONTDESK_SOLUTION_PLAN_REF, must_exist=True).read_text())
    acceptance = workspace.resolve_path(FRONTDESK_ACCEPTANCE_CRITERIA_REF, must_exist=True).read_text()
    draft_spec = workspace.resolve_path(FRONTDESK_DRAFT_SKILL_SPEC_REF, must_exist=True).read_text()

    assert solution_plan["status"] == "awaiting_user_review"
    assert solution_plan["core_need_brief_ref"] == FRONTDESK_CORE_NEED_BRIEF_REF
    assert solution_plan["draft_skill_spec_ref"] == FRONTDESK_DRAFT_SKILL_SPEC_REF
    assert solution_plan["acceptance_criteria_ref"] == FRONTDESK_ACCEPTANCE_CRITERIA_REF
    assert "Raw conversation is forbidden provenance only." in draft_spec
    assert "Builder context must be based on frozen governed artifacts" in acceptance
    criteria = AcceptanceCriteriaSet.read_yaml_file(
        workspace.resolve_path(FRONTDESK_ACCEPTANCE_CRITERIA_REF, must_exist=True)
    )
    assert [criterion.verifier_check_id for criterion in criteria.criteria] == [
        "package_skill_md_present",
        "contextforge_raw_frontdesk_conversation_excluded",
    ]
    assert result.harness_result.worker_run.metadata["worker_self_report_is_not_acceptance"] is True
    assert result.harness_result.worker_run.metadata["raw_conversation_included"] is False
    assert result.runtime_result["refs"]["solution_plan"] == FRONTDESK_SOLUTION_PLAN_REF
    assert "solution_plan" in result.runtime_result["hashes"]
    assert "acceptance_criteria" in result.runtime_result["hashes"]


def _approved_solution_plan(frontdesk, *, plan_review_ref: str = FRONTDESK_PLAN_REVIEW_REF) -> None:
    payload = json.loads(frontdesk.workspace.resolve_path(FRONTDESK_SOLUTION_PLAN_REF, must_exist=True).read_text())
    payload["status"] = "approved"
    write_frontdesk_artifact(frontdesk, FRONTDESK_SOLUTION_PLAN_REF, payload)
    write_frontdesk_artifact(
        frontdesk,
        plan_review_ref,
        PlanReviewRecord(
            review_id=plan_review_ref.removeprefix("frontdesk/").removesuffix(".json").replace("_", "-"),
            solution_plan_ref=FRONTDESK_SOLUTION_PLAN_REF,
            decision="approve",
            reviewer_id="test-user",
            reviewer_role="requesting_user",
            reason="The plan matches the intended workflow.",
            source_hash=sha256_file(frontdesk.workspace.resolve_path(FRONTDESK_SOLUTION_PLAN_REF, must_exist=True)),
            created_at=CREATED_AT,
        ),
    )


def test_frontdesk_spec_auditor_runs_after_approved_plan_without_raw_conversation(tmp_path) -> None:
    marker = "RAW_CONVERSATION_SHOULD_NOT_ENTER_SPEC_AUDITOR_PROMPT"
    workspace, frontdesk = _frontdesk_workspace(tmp_path, marker=marker, seed_solution_plan=False)
    run_frontdesk_core_need_goal_harness(frontdesk, created_at=CREATED_AT)
    run_frontdesk_solution_planner_goal_harness(frontdesk, created_at=CREATED_AT)
    _approved_solution_plan(frontdesk)

    result = run_frontdesk_spec_auditor_goal_harness(frontdesk, created_at=CREATED_AT)

    assert workspace.resolve_path(FRONTDESK_SPEC_AUDIT_RUNTIME_RESULT_REF, must_exist=True).is_file()
    assert workspace.resolve_path(FRONTDESK_SPEC_AUDIT_RUNTIME_STATE_REF, must_exist=True).is_file()
    assert workspace.resolve_path(FRONTDESK_SPEC_AUDIT_REPORT_REF, must_exist=True).is_file()
    assert workspace.resolve_path(FRONTDESK_FEASIBILITY_REPORT_REF, must_exist=True).is_file()
    assert result.harness_result.worker_run.worker_kind == "fake_model"
    assert result.harness_result.worker_run.status == "completed"
    assert result.goal_run.status == "completed"
    assert result.runtime_state["stage"] == SPEC_AUDITOR_NODE_ID
    assert result.runtime_state["refs"]["spec_audit_report"] == FRONTDESK_SPEC_AUDIT_REPORT_REF
    assert result.runtime_result["trust_boundaries"]["raw_conversation_included"] is False

    ledger = ContextLedger.connect(workspace.resolve_path(FRONTDESK_GOAL_RUNTIME_LEDGER_REF, must_exist=True))
    try:
        context_view = ledger.get_context_view(result.harness_result.compiled_context.context_view.context_view_id)
        prompt_view, _blocks = ledger.get_prompt_view(result.harness_result.compiled_context.prompt_view.id)
        included = set(context_view.included_item_ids)
        forbidden = set(context_view.forbidden_item_ids)
        assert f"{workspace.job_id}:{SPEC_AUDITOR_NODE_ID}:frontdesk_core_need_brief" in included
        assert f"{workspace.job_id}:{SPEC_AUDITOR_NODE_ID}:frontdesk_solution_plan" in included
        assert f"{workspace.job_id}:{SPEC_AUDITOR_NODE_ID}:frontdesk_plan_review" in included
        assert f"{workspace.job_id}:{SPEC_AUDITOR_NODE_ID}:frontdesk_draft_skill_spec" in included
        assert f"{workspace.job_id}:{SPEC_AUDITOR_NODE_ID}:frontdesk_acceptance_criteria" in included
        assert f"{workspace.job_id}:{SPEC_AUDITOR_NODE_ID}:raw_frontdesk_conversation" in forbidden
        assert f"{workspace.job_id}:{SPEC_AUDITOR_NODE_ID}:raw_frontdesk_conversation" not in included
        rendered_prompt = "\n".join(message.content for message in prompt_view.messages)
    finally:
        ledger.close()

    state_text = json.dumps(result.runtime_state, sort_keys=True)
    result_text = json.dumps(result.runtime_result, sort_keys=True)
    draft_spec_text = workspace.resolve_path(FRONTDESK_DRAFT_SKILL_SPEC_REF, must_exist=True).read_text(
        encoding="utf-8"
    )
    assert "requirement-skill" in draft_spec_text
    assert marker not in rendered_prompt
    assert marker not in state_text
    assert marker not in result_text
    assert "conversation.jsonl" not in state_text
    assert "conversation.jsonl" not in result_text


def test_frontdesk_spec_auditor_handles_pv001_sized_frontdesk_artifacts(tmp_path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "frontdesk-pv001-runtime")
    frontdesk = initialize_frontdesk_workspace(workspace)
    frontdesk.append_conversation_turn(
        ConversationTurn(
            turn_id="turn-001",
            role="user",
            content=(
                "Build a Codex skill called codexarium for maintaining a structured personal LLM wiki "
                "from local Codex collaboration history."
            ),
        )
    )
    pv001_request = (
        "Build a Codex skill called codexarium for maintaining a structured personal LLM wiki from local "
        "Codex collaboration history. It must act as a knowledge curator and personal research secretary, "
        "preserving durable ideas, decisions, principles, experiments, failures, open questions, project goals, "
        "and recurring work patterns. It must reject raw log mirroring, activity diaries, secret collection, "
        "and paraphrased chat dumps. It should write Obsidian-friendly Markdown with compact evidence references "
        "and may use small local helper tools for health checks and evidence bundle scanning."
    )
    write_frontdesk_artifact(
        frontdesk,
        "clarification_summary.md",
        "\n".join(
            [
                "# Clarification Summary",
                "",
                "## Current User Request",
                pv001_request,
                "",
                "## Privacy Boundary",
                "- Raw conversation is provenance only.",
            ]
        ),
    )
    write_frontdesk_artifact(
        frontdesk,
        "risk_report.json",
        {
            "schema_version": "skillfoundry.frontdesk_risk_report.v1",
            "risk_flags": [],
            "redaction_status": "complete",
            "provider_usage": {
                "usage_available": False,
                "usage_unavailable_reason": "Offline Front Desk fixture does not call a provider.",
            },
        },
    )

    run_frontdesk_core_need_goal_harness(frontdesk, created_at=CREATED_AT)
    run_frontdesk_solution_planner_goal_harness(frontdesk, created_at=CREATED_AT)
    _approved_solution_plan(frontdesk)

    result = run_frontdesk_spec_auditor_goal_harness(frontdesk, created_at=CREATED_AT)

    assert result.harness_result.worker_run.status == "completed"
    assert workspace.resolve_path(FRONTDESK_SPEC_AUDIT_REPORT_REF, must_exist=True).is_file()
    ledger = ContextLedger.connect(workspace.resolve_path(FRONTDESK_GOAL_RUNTIME_LEDGER_REF, must_exist=True))
    try:
        prompt_view, _blocks = ledger.get_prompt_view(result.harness_result.compiled_context.prompt_view.id)
        assert prompt_view.budget.budget_tokens == 24000
        assert f"{workspace.job_id}:{SPEC_AUDITOR_NODE_ID}:frontdesk_acceptance_criteria" in set(
            prompt_view.source_item_ids
        )
    finally:
        ledger.close()


def test_frontdesk_spec_auditor_writes_audit_refs_after_user_review_gate(tmp_path) -> None:
    workspace, frontdesk = _frontdesk_workspace(tmp_path, seed_solution_plan=False)
    run_frontdesk_core_need_goal_harness(frontdesk, created_at=CREATED_AT)
    run_frontdesk_solution_planner_goal_harness(frontdesk, created_at=CREATED_AT)
    _approved_solution_plan(frontdesk)

    result = run_frontdesk_spec_auditor_goal_harness(frontdesk, created_at=CREATED_AT)

    audit = json.loads(workspace.resolve_path(FRONTDESK_SPEC_AUDIT_REPORT_REF, must_exist=True).read_text())
    feasibility = json.loads(workspace.resolve_path(FRONTDESK_FEASIBILITY_REPORT_REF, must_exist=True).read_text())
    assert audit["decision"] == "approved"
    assert audit["feasibility_report_ref"] == FRONTDESK_FEASIBILITY_REPORT_REF
    assert audit["elicitation_report_ref"] == FRONTDESK_SOLUTION_PLAN_REF
    assert feasibility["decision"] == "feasible"
    assert feasibility["report_ref"] == FRONTDESK_FEASIBILITY_REPORT_REF
    assert result.harness_result.worker_run.metadata["worker_self_report_is_not_acceptance"] is True
    assert result.runtime_result["refs"]["spec_audit_report"] == FRONTDESK_SPEC_AUDIT_REPORT_REF
    assert result.runtime_result["refs"]["plan_review"] == FRONTDESK_PLAN_REVIEW_REF
    assert "spec_audit_report" in result.runtime_result["hashes"]
    assert "feasibility_report" in result.runtime_result["hashes"]
    assert "plan_review" in result.runtime_result["hashes"]


def test_frontdesk_spec_auditor_accepts_routed_plan_review_ref(tmp_path) -> None:
    custom_plan_review_ref = "frontdesk/plan_review_002.json"
    workspace, frontdesk = _frontdesk_workspace(tmp_path, seed_solution_plan=False)
    run_frontdesk_core_need_goal_harness(frontdesk, created_at=CREATED_AT)
    run_frontdesk_solution_planner_goal_harness(frontdesk, created_at=CREATED_AT)
    _approved_solution_plan(frontdesk, plan_review_ref=custom_plan_review_ref)

    result = run_frontdesk_spec_auditor_goal_harness(
        frontdesk,
        plan_review_ref=custom_plan_review_ref,
        created_at=CREATED_AT,
    )

    assert result.harness_result.worker_run.status == "completed"
    assert result.runtime_state["refs"]["plan_review"] == custom_plan_review_ref
    assert result.runtime_result["refs"]["plan_review"] == custom_plan_review_ref
    assert "plan_review" in result.runtime_result["hashes"]
    ledger = ContextLedger.connect(workspace.resolve_path(FRONTDESK_GOAL_RUNTIME_LEDGER_REF, must_exist=True))
    try:
        context_view = ledger.get_context_view(result.harness_result.compiled_context.context_view.context_view_id)
        included = set(context_view.included_item_ids)
        assert f"{workspace.job_id}:{SPEC_AUDITOR_NODE_ID}:frontdesk_plan_review" in included
        prompt_view, _blocks = ledger.get_prompt_view(result.harness_result.compiled_context.prompt_view.id)
        rendered_prompt = "\n".join(message.content for message in prompt_view.messages)
    finally:
        ledger.close()
    assert "plan-review-002" in rendered_prompt


def test_frontdesk_spec_auditor_fails_closed_before_solution_plan_approval(tmp_path) -> None:
    workspace, frontdesk = _frontdesk_workspace(tmp_path, seed_solution_plan=False)
    run_frontdesk_core_need_goal_harness(frontdesk, created_at=CREATED_AT)
    run_frontdesk_solution_planner_goal_harness(frontdesk, created_at=CREATED_AT)

    result = run_frontdesk_spec_auditor_goal_harness(frontdesk, created_at=CREATED_AT)

    failure = json.loads(workspace.resolve_path(FRONTDESK_SPEC_AUDIT_FAILURE_REF, must_exist=True).read_text())
    assert result.harness_result.worker_run.status == "failed"
    assert result.harness_result.worker_run.failure_class == "solution_plan_not_approved"
    assert result.goal_run.status == "failed"
    assert failure["failure_class"] == "solution_plan_not_approved"
    assert failure["details"]["solution_plan_status"] == "awaiting_user_review"
    assert failure["raw_conversation_included"] is False
    assert not workspace.resolve_path(FRONTDESK_SPEC_AUDIT_REPORT_REF).exists()
    assert not workspace.resolve_path(FRONTDESK_FEASIBILITY_REPORT_REF).exists()
    assert result.runtime_result["refs"]["spec_audit_failure"] == FRONTDESK_SPEC_AUDIT_FAILURE_REF
    assert "spec_audit_failure" in result.runtime_result["hashes"]


def test_frontdesk_spec_auditor_fails_closed_without_plan_review_record(tmp_path) -> None:
    workspace, frontdesk = _frontdesk_workspace(tmp_path, seed_solution_plan=False)
    run_frontdesk_core_need_goal_harness(frontdesk, created_at=CREATED_AT)
    run_frontdesk_solution_planner_goal_harness(frontdesk, created_at=CREATED_AT)
    payload = json.loads(workspace.resolve_path(FRONTDESK_SOLUTION_PLAN_REF, must_exist=True).read_text())
    payload["status"] = "approved"
    write_frontdesk_artifact(frontdesk, FRONTDESK_SOLUTION_PLAN_REF, payload)

    result = run_frontdesk_spec_auditor_goal_harness(frontdesk, created_at=CREATED_AT)

    failure = json.loads(workspace.resolve_path(FRONTDESK_SPEC_AUDIT_FAILURE_REF, must_exist=True).read_text())
    assert result.harness_result.worker_run.status == "failed"
    assert result.harness_result.worker_run.failure_class == "missing_or_invalid_plan_review"
    assert "plan_review_001.json" in failure["details"]["plan_review_error"]
    assert not workspace.resolve_path(FRONTDESK_SPEC_AUDIT_REPORT_REF).exists()
    assert not workspace.resolve_path(FRONTDESK_FEASIBILITY_REPORT_REF).exists()


def test_frontdesk_spec_auditor_fails_closed_on_plan_review_hash_mismatch(tmp_path) -> None:
    workspace, frontdesk = _frontdesk_workspace(tmp_path, seed_solution_plan=False)
    run_frontdesk_core_need_goal_harness(frontdesk, created_at=CREATED_AT)
    run_frontdesk_solution_planner_goal_harness(frontdesk, created_at=CREATED_AT)
    _approved_solution_plan(frontdesk)
    payload = json.loads(workspace.resolve_path(FRONTDESK_SOLUTION_PLAN_REF, must_exist=True).read_text())
    payload["summary"] = "The plan changed after user approval."
    write_frontdesk_artifact(frontdesk, FRONTDESK_SOLUTION_PLAN_REF, payload)

    result = run_frontdesk_spec_auditor_goal_harness(frontdesk, created_at=CREATED_AT)

    failure = json.loads(workspace.resolve_path(FRONTDESK_SPEC_AUDIT_FAILURE_REF, must_exist=True).read_text())
    assert result.harness_result.worker_run.status == "failed"
    assert result.harness_result.worker_run.failure_class == "plan_review_source_hash_mismatch"
    assert failure["failure_class"] == "plan_review_source_hash_mismatch"
    assert failure["details"]["plan_review_ref"] == FRONTDESK_PLAN_REVIEW_REF
    assert not workspace.resolve_path(FRONTDESK_SPEC_AUDIT_REPORT_REF).exists()
    assert not workspace.resolve_path(FRONTDESK_FEASIBILITY_REPORT_REF).exists()
