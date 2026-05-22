from __future__ import annotations

import json

from contextforge import ContextLedger

import skillfoundry
from skillfoundry import (
    FRONTDESK_ACCEPTANCE_CRITERIA_REF,
    FRONTDESK_CORE_NEED_BRIEF_REF,
    FRONTDESK_CORE_NEED_REPORT_REF,
    FRONTDESK_CORE_NEED_RUNTIME_RESULT_REF,
    FRONTDESK_CORE_NEED_RUNTIME_STATE_REF,
    FRONTDESK_DRAFT_SKILL_SPEC_REF,
    FRONTDESK_GOAL_RUNTIME_LEDGER_REF,
    FRONTDESK_GOAL_RUNTIME_SCHEMA_VERSION,
    FRONTDESK_SOLUTION_PLAN_MARKDOWN_REF,
    FRONTDESK_SOLUTION_PLAN_REF,
    FRONTDESK_SOLUTION_PLAN_RUNTIME_RESULT_REF,
    FRONTDESK_SOLUTION_PLAN_RUNTIME_STATE_REF,
    FRONTDESK_V2_GOAL_CONTRACT_REF,
    CORE_NEED_DISCOVERY_NODE_ID,
    SOLUTION_PLANNER_NODE_ID,
    ConversationTurn,
    initialize_frontdesk_workspace,
    initialize_job_workspace,
    write_frontdesk_artifact,
    run_frontdesk_core_need_goal_harness,
    run_frontdesk_solution_planner_goal_harness,
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
    assert "governed Codex Skill requirement" in rendered_prompt
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
    assert result.harness_result.worker_run.metadata["worker_self_report_is_not_acceptance"] is True
    assert result.harness_result.worker_run.metadata["raw_conversation_included"] is False
    assert result.runtime_result["refs"]["solution_plan"] == FRONTDESK_SOLUTION_PLAN_REF
    assert "solution_plan" in result.runtime_result["hashes"]
    assert "acceptance_criteria" in result.runtime_result["hashes"]
