from __future__ import annotations

import json
from pathlib import Path

from contextforge import ContextLedger

from skillfoundry import (
    GOAL_RUNTIME_LEDGER_REF,
    GOAL_RUNTIME_RESULT_REF,
    V2Route,
    V2Stage,
    V2Status,
    build_offline_goal_harness_node,
    compile_skillfoundry_v2_graph,
    validate_v2_graph_state,
)
from skillfoundry.goal_runtime import run_offline_goal_harness
from skillfoundry.workspace import initialize_job_workspace


CREATED_AT = "2026-05-22T00:00:00Z"


def test_v2_graph_runs_offline_goal_harness_node_and_routes_success(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    workspace = initialize_job_workspace(runs_root, "graph-runtime-pass")
    graph = compile_skillfoundry_v2_graph(
        build_node_callable=build_offline_goal_harness_node(
            runs_root,
            verification_mode="pass",
            created_at=CREATED_AT,
        )
    )

    result = graph.invoke({"job_id": workspace.job_id, "attempt_limit": 2})

    validate_v2_graph_state(result)
    assert result["stage"] == V2Stage.EMIT_REPORT.value
    assert result["status"] == V2Status.REPORT_EMITTED.value
    assert result["contextforge"]["last_verification_status"] == "passed"
    assert result["contextforge"]["last_goal_decision"] == "complete"
    assert result["contextforge"]["next_route"] == V2Route.REGISTRY_GATE.value
    assert result["refs"]["ledger"] == GOAL_RUNTIME_LEDGER_REF
    assert result["refs"]["runtime_result"] == GOAL_RUNTIME_RESULT_REF
    assert result["refs"]["registry_entry"] == "registry/entry.json"
    assert workspace.resolve_path("package/SKILL.md", must_exist=True).is_file()

    ledger = ContextLedger.connect(workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF, must_exist=True))
    try:
        assert ledger.get_goal_run_record(result["contextforge"]["last_goal_run_id"])
        assert ledger.get_worker_run(result["contextforge"]["last_worker_run_id"])
        assert ledger.get_verification_result(result["contextforge"]["last_verification_result_id"])
    finally:
        ledger.close()


def test_v2_graph_runs_offline_goal_harness_node_and_routes_failed_verification_to_repair(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    workspace = initialize_job_workspace(runs_root, "graph-runtime-fail")
    graph = compile_skillfoundry_v2_graph(
        build_node_callable=build_offline_goal_harness_node(
            runs_root,
            verification_mode="fail_missing_coverage",
            created_at=CREATED_AT,
        )
    )

    result = graph.invoke({"job_id": workspace.job_id, "attempt_limit": 2})

    validate_v2_graph_state(result)
    assert result["stage"] == V2Stage.REPAIR_GOAL_NODE.value
    assert result["status"] == V2Status.REPAIR_PLANNED.value
    assert result["contextforge"]["last_verification_status"] == "failed"
    assert result["contextforge"]["last_goal_decision"] == "repair"
    assert result["contextforge"]["next_route"] == V2Route.REPAIR_GOAL_NODE.value
    assert result["refs"]["repair_instructions"] == "attempts/002/repair_instructions.md"


def test_verification_status_overrides_conflicting_next_route() -> None:
    state = {
        "job_id": "route-conflict",
        "attempt_count": 1,
        "attempt_limit": 2,
        "next_route": V2Route.REGISTRY_GATE.value,
        "contextforge": {
            "last_verification_status": "failed",
            "next_route": V2Route.REGISTRY_GATE.value,
        },
    }

    graph = compile_skillfoundry_v2_graph()
    result = graph.invoke(state)

    assert result["stage"] == V2Stage.REPAIR_GOAL_NODE.value
    assert result["contextforge"]["last_verification_status"] == "failed"


def test_v2_graph_offline_runtime_state_remains_refs_only_with_raw_conversation_present(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    workspace = initialize_job_workspace(runs_root, "graph-runtime-raw")
    frontdesk_dir = workspace.root / "frontdesk"
    frontdesk_dir.mkdir()
    marker = "RAW_CONVERSATION_SHOULD_NOT_APPEAR_IN_GRAPH_STATE"
    (frontdesk_dir / "conversation.jsonl").write_text(marker, encoding="utf-8")
    graph = compile_skillfoundry_v2_graph(
        build_node_callable=build_offline_goal_harness_node(
            runs_root,
            verification_mode="pass",
            created_at=CREATED_AT,
        )
    )

    result = graph.invoke({"job_id": workspace.job_id, "attempt_limit": 2})
    state_text = json.dumps(result, sort_keys=True)
    runtime_result = json.loads(workspace.resolve_path(GOAL_RUNTIME_RESULT_REF, must_exist=True).read_text())

    validate_v2_graph_state(result)
    assert marker not in state_text
    assert marker not in json.dumps(runtime_result, sort_keys=True)
    assert "prompt" not in result["contextforge"]
    assert "worker_transcript" not in state_text
    assert result["refs"]["ledger"] == GOAL_RUNTIME_LEDGER_REF


def test_imported_runtime_symbol_remains_available_for_direct_slice_use(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "direct-runtime")

    direct = run_offline_goal_harness(workspace, verification_mode="pass", created_at=CREATED_AT)

    assert direct.graph_state["contextforge"]["last_verification_status"] == "passed"
