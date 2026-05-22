from __future__ import annotations

import json
from pathlib import Path

from contextforge import ContextLedger

from skillfoundry.contracts import BUILD_NODE_CONTRACT_REF, GOAL_CONTRACT_REF, VERIFICATION_GATE_REF
from skillfoundry.goal_runtime import (
    GOAL_RUNTIME_LEDGER_REF,
    GOAL_RUNTIME_RESULT_REF,
    GOAL_RUNTIME_STATE_REF,
    run_offline_goal_harness,
)
from skillfoundry.workers_v2 import WORKERS_V2_VERSION
from skillfoundry.workspace import initialize_job_workspace


CREATED_AT = "2026-05-22T00:00:00Z"


def test_offline_goal_harness_pass_records_context_cache_worker_verification_and_state(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "slice-pass")

    result = run_offline_goal_harness(workspace, verification_mode="pass", created_at=CREATED_AT)

    assert workspace.resolve_path(GOAL_CONTRACT_REF, must_exist=True).is_file()
    assert workspace.resolve_path(BUILD_NODE_CONTRACT_REF, must_exist=True).is_file()
    assert workspace.resolve_path(VERIFICATION_GATE_REF, must_exist=True).is_file()
    assert workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF, must_exist=True).is_file()
    assert workspace.resolve_path(GOAL_RUNTIME_RESULT_REF, must_exist=True).is_file()
    assert workspace.resolve_path(GOAL_RUNTIME_STATE_REF, must_exist=True).is_file()
    assert workspace.resolve_path("package/SKILL.md", must_exist=True).is_file()
    assert workspace.resolve_path("verifier/verification_result.json", must_exist=True).is_file()
    assert workspace.resolve_path("qa/acceptance_coverage_result.json", must_exist=True).is_file()

    ledger = ContextLedger.connect(workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF, must_exist=True))
    try:
        assert ledger.get_context_view(result.harness_result.compiled_context.context_view.context_view_id)
        assert ledger.get_prompt_cache_plan(result.harness_result.compiled_context.cache_plan.cache_plan_id)
        assert ledger.get_worker_run(result.harness_result.worker_run.worker_run_id) == result.harness_result.worker_run
        assert ledger.get_verification_result(result.verification_result.verification_result_id) == result.verification_result
        assert ledger.get_goal_run_record(result.goal_run.goal_run_id) == result.goal_run
        checkpoints = ledger.query_checkpoints(goal_run_id=result.goal_run.goal_run_id)
        assert {checkpoint.checkpoint_id for checkpoint in checkpoints} == set(result.goal_run.checkpoint_ids)
    finally:
        ledger.close()

    context_view = result.harness_result.compiled_context.context_view
    assert {
        "slice-pass:skill_spec",
        "slice-pass:acceptance_criteria",
        "slice-pass:verification_gate",
        "slice-pass:build_contract",
    }.issubset(set(context_view.included_item_ids))
    assert result.harness_result.compiled_context.cache_plan.cache_epoch_id == (
        result.contracts.build_node_contract.cache_policy.cache_epoch_id
    )
    assert result.harness_result.worker_run.worker_kind == "fake_model"
    assert result.harness_result.worker_run.metadata["workers_v2"] == WORKERS_V2_VERSION
    assert result.harness_result.worker_run.metadata["worker_self_report_is_not_acceptance"] is True
    assert result.harness_result.worker_run.metadata["changed_files"] == [
        "package/SKILL.md",
        "attempts/fake_worker_report.json",
        "attempts/fake_worker_transcript.log",
    ]
    assert result.verification_result.status == "passed"
    assert result.goal_run.status == "completed"
    assert result.goal_run.decision == "complete"
    assert result.goal_run.checkpoint_ids
    assert result.graph_state["contextforge"]["last_checkpoint_id"] == result.goal_run.checkpoint_ids[-1]
    assert result.graph_state["contextforge"]["checkpoint_ids"] == result.goal_run.checkpoint_ids
    assert result.graph_state["contextforge"]["next_route"] == "registry_gate"


def test_offline_goal_harness_failed_verification_routes_to_repair(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "slice-fail")

    result = run_offline_goal_harness(
        workspace,
        verification_mode="fail_missing_coverage",
        created_at=CREATED_AT,
    )

    assert result.harness_result.worker_run.status == "completed"
    assert result.verification_result.status == "failed"
    assert result.goal_run.status == "failed"
    assert result.goal_run.decision == "repair"
    assert result.graph_state["contextforge"]["next_route"] == "repair_goal_node"
    assert result.graph_state["next_route"] == "repair_goal_node"


def test_offline_goal_harness_forbids_raw_frontdesk_conversation_from_prompt_and_state(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "slice-raw")
    frontdesk_dir = workspace.root / "frontdesk"
    frontdesk_dir.mkdir()
    marker = "RAW_CONVERSATION_SHOULD_NOT_APPEAR_IN_PROMPT_OR_STATE"
    (frontdesk_dir / "conversation.jsonl").write_text(marker, encoding="utf-8")

    result = run_offline_goal_harness(workspace, verification_mode="pass", created_at=CREATED_AT)

    context_view = result.harness_result.compiled_context.context_view
    rendered_prompt = "\n".join(
        message.content for message in result.harness_result.compiled_context.prompt_view.messages
    )
    state_text = json.dumps(result.graph_state, sort_keys=True)
    runtime_text = json.dumps(result.runtime_result, sort_keys=True)

    assert "slice-raw:raw_frontdesk_conversation" in context_view.forbidden_item_ids
    assert "slice-raw:raw_frontdesk_conversation" not in context_view.included_item_ids
    assert marker not in rendered_prompt
    assert marker not in state_text
    assert marker not in runtime_text
    assert "frontdesk/conversation.jsonl" in result.contracts.manifest["excluded_artifacts"]


def test_goal_harness_state_is_refs_and_ids_only(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "slice-state")

    result = run_offline_goal_harness(workspace, verification_mode="pass", created_at=CREATED_AT)

    state = result.graph_state
    state_text = json.dumps(state, sort_keys=True)

    assert state["refs"] == {
        "goal_contract": GOAL_CONTRACT_REF,
        "build_node_contract": BUILD_NODE_CONTRACT_REF,
        "verification_gate": VERIFICATION_GATE_REF,
        "contract_manifest": "contextforge/contract_manifest.json",
        "ledger": GOAL_RUNTIME_LEDGER_REF,
        "runtime_result": GOAL_RUNTIME_RESULT_REF,
    }
    assert "SkillFoundry WP1 placeholder skill" not in state_text
    assert "Current intent:" not in state_text
    assert "Generated Review Assistant" not in state_text
    assert result.graph_state["contextforge"]["last_goal_run_id"] == result.goal_run.goal_run_id
    assert result.graph_state["contextforge"]["last_worker_run_id"] == result.harness_result.worker_run.worker_run_id
