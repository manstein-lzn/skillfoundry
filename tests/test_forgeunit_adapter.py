from __future__ import annotations

import json
from pathlib import Path

import yaml

from forgeunit import validate_task_pack_or_raise
from skillfoundry.forgeunit_adapter import (
    FORGEUNIT_ADAPTER_VERSION,
    FORGEUNIT_BOUNDARY_VERIFICATION_REF,
    FORGEUNIT_PILOT_GRAPH_STATE_REF,
    FORGEUNIT_SUMMARY_REF,
    FORGEUNIT_TASK_YAML_REF,
    build_forgeunit_codex_exec_node,
    materialize_forgeunit_task_pack,
    run_forgeunit_codex_exec_node,
    run_forgeunit_pilot_graph,
)
from skillfoundry.graph_v2 import V2Stage, V2Status, validate_v2_graph_state
from skillfoundry.workspace import initialize_job_workspace


def test_materialize_forgeunit_task_pack_from_job_workspace(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    workspace = initialize_job_workspace(
        runs_root,
        "forgeunit-adapter-001",
        worker_input="private user requirement body must stay in files only",
    )

    result = materialize_forgeunit_task_pack(workspace)
    payload = yaml.safe_load((workspace.root / FORGEUNIT_TASK_YAML_REF).read_text(encoding="utf-8"))
    serialized = json.dumps(payload)

    validate_task_pack_or_raise(result.task_pack_dir)
    assert result.task_pack_dir == workspace.root
    assert result.task_yaml_ref == FORGEUNIT_TASK_YAML_REF
    assert len(result.task_yaml_hash) == 64
    assert payload["graph"] == "plan_execute_verify"
    assert payload["units"]["execute"]["worker"]["kind"] == "codex_boundary"
    assert payload["units"]["execute"]["worker"]["write_scope"] == ["package", "evidence"]
    assert payload["units"]["execute"]["expected_outputs"][0]["path"] == "package/SKILL.md"
    assert "private user requirement body" not in serialized


def test_forgeunit_codex_exec_node_dry_run_keeps_skillfoundry_state_refs_only(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    workspace = initialize_job_workspace(
        runs_root,
        "forgeunit-adapter-002",
        worker_input="private codex skill request body must not enter graph state",
    )

    node = build_forgeunit_codex_exec_node(runs_root, dry_run=True)
    state = node({"job_id": workspace.job_id, "attempt_limit": 2})
    serialized_state = json.dumps(state)

    validate_v2_graph_state(state)
    assert state["stage"] == V2Stage.BUILD_GOAL_NODE.value
    assert state["status"] == V2Status.BUILD_RECORDED.value
    assert state["refs"]["forgeunit_task_yaml"] == FORGEUNIT_TASK_YAML_REF
    assert state["refs"]["forgeunit_summary"] == FORGEUNIT_SUMMARY_REF
    assert state["refs"]["forgeunit_codex_exec_plan"].endswith("_codex_exec_dry_run.json")
    assert state["contextforge"]["forgeunit_adapter_version"] == FORGEUNIT_ADAPTER_VERSION
    assert state["contextforge"]["forgeunit_codex_exec_dry_run"] is True
    assert state["contextforge"]["forgeunit_worker_self_report_is_not_acceptance"] is True
    assert "private codex skill request body" not in serialized_state
    assert "raw_prompt" not in serialized_state
    assert "transcript" not in serialized_state


def test_run_forgeunit_codex_exec_node_writes_refs_only_summary(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(
        tmp_path / "runs",
        "forgeunit-adapter-003",
        worker_input="private summary body must remain outside summary",
    )

    result = run_forgeunit_codex_exec_node(workspace, dry_run=True)
    summary_path = workspace.root / result.summary_ref
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    serialized = json.dumps(summary)

    assert result.summary_ref == FORGEUNIT_SUMMARY_REF
    assert result.run_dir_ref.startswith(".forgeunit/runs/")
    assert result.dry_run_plan_ref is not None
    assert result.dry_run_plan_ref.endswith("_codex_exec_dry_run.json")
    assert summary["action"] == "codex_exec"
    assert summary["operation_status"] == "dry_run"
    assert "prompt" not in summary.get("adapter_result", {})
    assert "private summary body" not in serialized


def test_forgeunit_pilot_graph_routes_dry_run_to_human_review(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    workspace = initialize_job_workspace(
        runs_root,
        "forgeunit-pilot-001",
        worker_input="private pilot request body must not enter graph state or review request",
    )

    result = run_forgeunit_pilot_graph(
        runs_root,
        workspace.job_id,
        dry_run=True,
        created_at="2026-05-23T00:00:00Z",
    )
    serialized_state = json.dumps(result)
    review_request = json.loads(workspace.resolve_path("human_review/request.json", must_exist=True).read_text())
    boundary_verification = json.loads(
        workspace.resolve_path(FORGEUNIT_BOUNDARY_VERIFICATION_REF, must_exist=True).read_text()
    )
    serialized_review = json.dumps(review_request)

    validate_v2_graph_state(result)
    assert result["stage"] == V2Stage.HUMAN_REVIEW.value
    assert result["status"] == V2Status.HUMAN_REVIEW_REQUIRED.value
    assert result["human_review_required"] is True
    assert result["refs"]["forgeunit_boundary_verification"] == FORGEUNIT_BOUNDARY_VERIFICATION_REF
    assert result["refs"]["forgeunit_summary"] == FORGEUNIT_SUMMARY_REF
    assert result["refs"]["forgeunit_codex_exec_plan"].endswith("_codex_exec_dry_run.json")
    assert "registry_decision" not in result["refs"]
    assert "final_report" not in result["refs"]
    assert result["contextforge"]["last_verification_status"] == "human_acceptance_required"
    assert result["contextforge"]["forgeunit_boundary_status"] == "dry_run_plan_ready"
    assert result["contextforge"]["forgeunit_boundary_reason_code"] == "forgeunit_codex_exec_dry_run_boundary_pending"
    assert review_request["reason_code"] == "forgeunit_codex_exec_dry_run_boundary_pending"
    assert review_request["evidence_refs"]["forgeunit_summary"] == FORGEUNIT_SUMMARY_REF
    assert review_request["evidence_refs"]["forgeunit_boundary_verification"] == FORGEUNIT_BOUNDARY_VERIFICATION_REF
    assert boundary_verification["status"] == "human_acceptance_required"
    assert boundary_verification["trust_boundaries"]["dry_run_is_not_verification"] is True
    assert workspace.resolve_path(FORGEUNIT_PILOT_GRAPH_STATE_REF, must_exist=True).is_file()
    assert "private pilot request body" not in serialized_state
    assert "private pilot request body" not in serialized_review
    assert "raw_prompt" not in serialized_state
    assert review_request["trust_boundaries"]["raw_transcript_included"] is False
    assert review_request["trust_boundaries"]["raw_prompt_included"] is False
