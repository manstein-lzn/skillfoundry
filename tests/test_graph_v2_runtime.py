from __future__ import annotations

import json
from pathlib import Path
import shutil

from contextforge import ContextLedger, ModelResponse, WorkerRunResult
import pytest

from skillfoundry import (
    AcceptanceCriteriaSet,
    AcceptanceCriterion,
    CONTEXTFORGE_VERIFICATION_RESULT_REF,
    GOAL_RUNTIME_LEDGER_REF,
    GOAL_RUNTIME_RESULT_REF,
    LocalSkillRegistry,
    OWNED_LLM_WORKER_OUTPUT_SCHEMA_VERSION,
    OwnedLLMSkillBuilderWorker,
    RepairAttempt,
    VERIFIED_GOAL_RUNTIME_RESULT_REF,
    V2Route,
    V2Stage,
    V2StateValidationError,
    V2Status,
    build_offline_goal_harness_node,
    build_repair_goal_harness_node,
    build_verified_goal_harness_node,
    build_verified_repair_verification_node,
    build_verified_registry_gate_node,
    compile_skillfoundry_v2_graph,
    validate_v2_graph_state,
)
from skillfoundry.goal_runtime import run_offline_goal_harness
from skillfoundry.workspace import initialize_job_workspace


CREATED_AT = "2026-05-22T00:00:00Z"

GRAPH_OWNED_SKILL = """---
name: graph-owned-runtime-skill
description: Graph v2 owned worker runtime fixture.
---

# Graph Owned Runtime Skill

## Overview

This package is generated through the graph-routed owned LLM Goal Harness worker.

## When To Use

- Use when graph runtime selection needs an owned LLM worker fixture.

## When Not To Use

- Do not treat worker output as approval.

## Inputs

- Frozen graph build inputs.

## Outputs

- A package candidate.

## Workflow

- Use ContextForge prompt and cache boundaries.
- Return strict JSON package files.

## Safety

- Keep verifier and registry gates authoritative.
"""


class ScriptedGraphModelClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def invoke(self, messages, model, params, tools=None):
        self.calls.append({"messages": list(messages), "model": model, "params": dict(params), "tools": tools})
        payload = {
            "schema_version": OWNED_LLM_WORKER_OUTPUT_SCHEMA_VERSION,
            "skill_markdown": GRAPH_OWNED_SKILL,
            "reference_files": [{"path": "references/graph.md", "content": "# Graph\n\nOwned path.\n"}],
            "script_files": [],
            "test_files": [],
        }
        return (
            ModelResponse(
                text=json.dumps(payload, sort_keys=True),
                raw_response_artifact_ref=None,
                finish_reason="stop",
                metadata={"scripted_graph": True},
            ),
            None,
            None,
        )


class BrokenRepairWorker:
    name = "skillfoundry-broken-repair-worker"
    kind = "fake_model"

    def __init__(self, workspace) -> None:
        self.workspace = workspace

    def run(self, request) -> WorkerRunResult:
        ref = "package/SKILL.md"
        self.workspace.resolve_path(ref).write_text("# Broken Repair\n", encoding="utf-8")
        return WorkerRunResult(
            status="completed",
            worker_name=self.name,
            final_output_ref=ref,
            summary="Wrote an intentionally incomplete repair package.",
            failure_class=None,
            prompt_view_ids=[request.prompt_view.id],
            artifact_ids=[f"{self.workspace.job_id}:package:SKILL.md"],
            usage_summary={
                "provider": "offline",
                "model": "broken_repair_fixture",
                "usage_unavailable_reason": "test_fixture",
            },
            metadata={
                "artifact_refs": [ref],
                "changed_files": [ref],
                "attempted_changed_files": [ref],
                "worker_self_report_is_not_acceptance": True,
            },
        )


def _owned_graph_worker_factory(client: ScriptedGraphModelClient):
    return lambda workspace: OwnedLLMSkillBuilderWorker(workspace, client=client)


def _broken_repair_worker_factory():
    return lambda workspace: BrokenRepairWorker(workspace)


def _criterion() -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id="AC-GRAPH-V2-001",
        description="The v2 graph produces a verified Skill package.",
        source_requirement="Route the verified Goal Harness runtime through LangGraph v2.",
        source_turn_ids=["turn-graph-v2"],
        requirement_id="REQ-GRAPH-V2-001",
        test_method="static",
        pass_condition="Verifier check package_skill_md_present passes.",
        failure_examples=["package/SKILL.md is missing."],
        required_evidence=[],
        evidence_kind="verifier_check",
        priority="must",
        risk_tags=[],
        data_sensitivity="internal",
        coverage_status="planned",
        verifier_check_id="package_skill_md_present",
    )


def _write_acceptance_criteria(workspace) -> None:
    AcceptanceCriteriaSet(criteria=[_criterion()], job_id=workspace.job_id).write_yaml_file(
        workspace.resolve_path("acceptance_criteria.yaml")
    )


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


def test_v2_graph_can_route_owned_llm_goal_harness_worker_without_prompt_leakage(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    workspace = initialize_job_workspace(runs_root, "graph-runtime-owned")
    client = ScriptedGraphModelClient()
    graph = compile_skillfoundry_v2_graph(
        build_node_callable=build_offline_goal_harness_node(
            runs_root,
            verification_mode="pass",
            created_at=CREATED_AT,
            worker_factory=_owned_graph_worker_factory(client),
        )
    )

    result = graph.invoke({"job_id": workspace.job_id, "attempt_limit": 2})

    validate_v2_graph_state(result)
    assert result["stage"] == V2Stage.EMIT_REPORT.value
    assert result["status"] == V2Status.REPORT_EMITTED.value
    assert result["contextforge"]["last_verification_status"] == "passed"
    assert workspace.resolve_path("package/SKILL.md", must_exist=True).is_file()
    assert workspace.resolve_path("package/references/graph.md", must_exist=True).is_file()
    assert client.calls

    state_text = json.dumps(result, sort_keys=True)
    assert "Graph Owned Runtime Skill" not in state_text
    assert "scripted_graph" not in state_text
    assert "raw_response" not in state_text

    ledger = ContextLedger.connect(workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF, must_exist=True))
    try:
        worker_run = ledger.get_worker_run(result["contextforge"]["last_worker_run_id"])
        assert worker_run.worker_kind == "llm"
        assert worker_run.model_call_ids
        assert ledger.get_model_call(worker_run.model_call_ids[0])
    finally:
        ledger.close()


def test_v2_graph_runs_verified_goal_harness_through_real_registry_gate(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    workspace = initialize_job_workspace(runs_root, "graph-runtime-verified")
    _write_acceptance_criteria(workspace)
    graph = compile_skillfoundry_v2_graph(
        build_node_callable=build_verified_goal_harness_node(
            runs_root,
            registry_path=registry_path,
            created_at=CREATED_AT,
        ),
        registry_gate_callable=build_verified_registry_gate_node(
            runs_root,
            registry_path=registry_path,
            created_at=CREATED_AT,
        ),
    )

    result = graph.invoke({"job_id": workspace.job_id, "attempt_limit": 2})

    validate_v2_graph_state(result)
    assert result["stage"] == V2Stage.EMIT_REPORT.value
    assert result["status"] == V2Status.REPORT_EMITTED.value
    assert result["refs"]["verified_runtime_result"] == VERIFIED_GOAL_RUNTIME_RESULT_REF
    assert result["refs"]["contextforge_verification_result"] == CONTEXTFORGE_VERIFICATION_RESULT_REF
    assert result["refs"]["final_report"] == "final_report.json"
    assert result["refs"]["registry_decision"] == "registry/decision.json"
    assert result["refs"]["registry_entry"] == "registry/entry.json"
    assert result["contextforge"]["last_verification_status"] == "passed"
    assert result["contextforge"]["last_goal_decision"] == "complete"
    assert result["contextforge"]["registry_approved"] is True
    assert result["contextforge"]["checkpoint_ids"]
    assert workspace.resolve_path("final_report.json", must_exist=True).is_file()
    assert workspace.resolve_path("registry/decision.json", must_exist=True).is_file()
    assert workspace.resolve_path("registry/entry.json", must_exist=True).is_file()

    final_report = json.loads(workspace.resolve_path("final_report.json", must_exist=True).read_text())
    assert final_report["final_status"] == "registered"
    entry = LocalSkillRegistry(registry_path).get(
        result["contextforge"]["registry_skill_id"],
        result["contextforge"]["registry_version"],
    )
    assert LocalSkillRegistry(registry_path).verify_entry(entry).valid is True

    ledger = ContextLedger.connect(workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF, must_exist=True))
    try:
        goal_run = ledger.get_goal_run_record(result["contextforge"]["last_goal_run_id"])
        assert goal_run.verification_result_id == result["contextforge"]["last_verification_result_id"]
        assert goal_run.checkpoint_ids == result["contextforge"]["checkpoint_ids"]
        assert len(ledger.query_checkpoints(goal_run_id=goal_run.goal_run_id)) >= 2
    finally:
        ledger.close()


def test_verified_registry_gate_rejects_tampered_verified_runtime(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    workspace = initialize_job_workspace(runs_root, "graph-runtime-tamper")
    _write_acceptance_criteria(workspace)
    build_node = build_verified_goal_harness_node(
        runs_root,
        registry_path=registry_path,
        created_at=CREATED_AT,
    )
    state = build_node({"job_id": workspace.job_id, "attempt_limit": 2})
    verified_path = workspace.resolve_path(VERIFIED_GOAL_RUNTIME_RESULT_REF, must_exist=True)
    payload = json.loads(verified_path.read_text())
    payload["status"]["registry_approved"] = False
    verified_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")

    registry_gate = build_verified_registry_gate_node(
        runs_root,
        registry_path=registry_path,
        created_at=CREATED_AT,
    )
    with pytest.raises(V2StateValidationError, match="registry approval"):
        registry_gate(state)


def test_verified_registry_gate_rejects_cross_job_verified_runtime(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    source = initialize_job_workspace(runs_root, "graph-runtime-source")
    target = initialize_job_workspace(runs_root, "graph-runtime-target")
    _write_acceptance_criteria(source)
    build_node = build_verified_goal_harness_node(
        runs_root,
        registry_path=registry_path,
        created_at=CREATED_AT,
    )
    build_node({"job_id": source.job_id, "attempt_limit": 2})
    (target.root / "contextforge").mkdir(exist_ok=True)
    for ref in (
        VERIFIED_GOAL_RUNTIME_RESULT_REF,
        CONTEXTFORGE_VERIFICATION_RESULT_REF,
        "final_report.json",
    ):
        source_path = source.resolve_path(ref, must_exist=True)
        target_path = target.resolve_path(ref)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)

    registry_gate = build_verified_registry_gate_node(
        runs_root,
        registry_path=registry_path,
        created_at=CREATED_AT,
    )
    with pytest.raises(V2StateValidationError, match="job_id mismatch"):
        registry_gate({"job_id": target.job_id, "refs": {"verified_runtime_result": VERIFIED_GOAL_RUNTIME_RESULT_REF}})

    assert not (target.root / "registry" / "decision.json").exists()


def test_verified_graph_nodes_reject_unsafe_job_id_before_workspace_writes(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    registry_gate = build_verified_registry_gate_node(
        runs_root,
        registry_path=tmp_path / "registry.json",
        created_at=CREATED_AT,
    )

    with pytest.raises(V2StateValidationError, match="job_id"):
        registry_gate({"job_id": "../outside"})

    assert not (outside / "registry" / "decision.json").exists()


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


def test_v2_graph_runs_repair_goal_harness_node_after_failed_verification(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    workspace = initialize_job_workspace(runs_root, "graph-runtime-repair")
    frontdesk_dir = workspace.root / "frontdesk"
    frontdesk_dir.mkdir()
    raw_marker = "RAW_REPAIR_CONVERSATION_SHOULD_NOT_APPEAR"
    (frontdesk_dir / "conversation.jsonl").write_text(raw_marker, encoding="utf-8")
    graph = compile_skillfoundry_v2_graph(
        build_node_callable=build_offline_goal_harness_node(
            runs_root,
            verification_mode="fail_missing_coverage",
            created_at=CREATED_AT,
        ),
        repair_node_callable=build_repair_goal_harness_node(
            runs_root,
            created_at=CREATED_AT,
        ),
    )

    result = graph.invoke({"job_id": workspace.job_id, "attempt_limit": 2})

    validate_v2_graph_state(result)
    assert result["stage"] == V2Stage.REPAIR_GOAL_NODE.value
    assert result["status"] == V2Status.REPAIR_RECORDED.value
    assert result["attempt_count"] == 2
    assert result["refs"]["repair_instructions"] == "attempts/002/repair_instructions.md"
    assert result["refs"]["repair_attempt"] == "attempts/002/repair_attempt.json"
    assert result["refs"]["repair_runtime_result"] == "contextforge/repair_goal_runtime_result_002.json"
    assert result["contextforge"]["last_verification_status"] == "failed"
    assert result["contextforge"]["last_repair_attempt_id"] == "002"
    assert result["contextforge"]["repair_status"] == "completed"
    assert result["contextforge"]["worker_self_report_is_not_acceptance"] is True
    assert "registry_approved" not in result["contextforge"]

    repair_attempt = RepairAttempt.read_json_file(
        workspace.resolve_path("attempts/002/repair_attempt.json", must_exist=True)
    )
    assert repair_attempt.status == "completed"
    assert repair_attempt.based_on_result_id == result["contextforge"]["last_verification_result_id"]
    assert repair_attempt.repair_instructions_ref == "attempts/002/repair_instructions.md"
    assert "package/SKILL.md" in repair_attempt.output_refs
    assert workspace.resolve_path("attempts/002/execution_report.json", must_exist=True).is_file()
    assert workspace.resolve_path("contextforge/repair_goal_runtime_result_002.json", must_exist=True).is_file()

    state_text = json.dumps(result, sort_keys=True)
    repair_runtime_result = json.loads(
        workspace.resolve_path("contextforge/repair_goal_runtime_result_002.json", must_exist=True).read_text()
    )
    assert raw_marker not in state_text
    assert raw_marker not in json.dumps(repair_runtime_result, sort_keys=True)
    assert "prompt" not in result["contextforge"]
    assert "worker_transcript" not in state_text
    assert "Graph Runtime" not in state_text

    ledger = ContextLedger.connect(workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF, must_exist=True))
    try:
        assert ledger.get_goal_run_record(result["contextforge"]["last_repair_goal_run_id"])
        assert ledger.get_worker_run(result["contextforge"]["last_repair_worker_run_id"])
        context_view = ledger.get_context_view(result["contextforge"]["last_repair_context_view_id"])
    finally:
        ledger.close()
    assert f"{workspace.job_id}:verifier_failure:002" in context_view.included_item_ids
    assert f"{workspace.job_id}:raw_frontdesk_conversation" not in context_view.included_item_ids


def test_v2_graph_reverifies_and_registers_after_repair(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    workspace = initialize_job_workspace(runs_root, "graph-runtime-repair-register")
    _write_acceptance_criteria(workspace)
    graph = compile_skillfoundry_v2_graph(
        build_node_callable=build_offline_goal_harness_node(
            runs_root,
            verification_mode="fail_missing_coverage",
            created_at=CREATED_AT,
        ),
        verify_node_callable=build_verified_repair_verification_node(
            runs_root,
            registry_path=registry_path,
            created_at=CREATED_AT,
        ),
        repair_node_callable=build_repair_goal_harness_node(
            runs_root,
            created_at=CREATED_AT,
            continue_to_verification=True,
        ),
        registry_gate_callable=build_verified_registry_gate_node(
            runs_root,
            registry_path=registry_path,
            created_at=CREATED_AT,
        ),
    )

    result = graph.invoke({"job_id": workspace.job_id, "attempt_limit": 2})

    validate_v2_graph_state(result)
    assert result["stage"] == V2Stage.EMIT_REPORT.value
    assert result["status"] == V2Status.REPORT_EMITTED.value
    assert result["attempt_count"] == 2
    assert result["refs"]["repair_attempt"] == "attempts/002/repair_attempt.json"
    assert result["refs"]["verified_runtime_result"] == VERIFIED_GOAL_RUNTIME_RESULT_REF
    assert result["refs"]["registry_decision"] == "registry/decision.json"
    assert result["refs"]["registry_entry"] == "registry/entry.json"
    assert result["contextforge"]["last_repair_attempt_id"] == "002"
    assert result["contextforge"]["last_verification_status"] == "passed"
    assert result["contextforge"]["last_goal_decision"] == "complete"
    assert result["contextforge"]["registry_approved"] is True
    assert result["contextforge"]["worker_self_report_is_not_acceptance"] is True

    verified_runtime = json.loads(
        workspace.resolve_path(VERIFIED_GOAL_RUNTIME_RESULT_REF, must_exist=True).read_text()
    )
    assert verified_runtime["refs"]["worker_execution_report"] == "attempts/002/execution_report.json"
    assert verified_runtime["trust_boundaries"]["repair_worker_output_is_not_acceptance"] is True
    assert verified_runtime["status"]["registry_approved"] is True
    assert workspace.resolve_path("registry/decision.json", must_exist=True).is_file()
    assert workspace.resolve_path("final_report.json", must_exist=True).is_file()

    entry = LocalSkillRegistry(registry_path).get(
        result["contextforge"]["registry_skill_id"],
        result["contextforge"]["registry_version"],
    )
    assert entry.provenance["execution_report"]["attempt_id"] == "002"
    assert LocalSkillRegistry(registry_path).verify_entry(entry).valid is True

    ledger = ContextLedger.connect(workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF, must_exist=True))
    try:
        goal_run = ledger.get_goal_run_record(result["contextforge"]["last_repair_goal_run_id"])
        assert goal_run.verification_result_id == result["contextforge"]["last_verification_result_id"]
        assert goal_run.decision == "complete"
        assert len(ledger.query_checkpoints(goal_run_id=goal_run.goal_run_id)) >= 2
    finally:
        ledger.close()


def test_v2_graph_does_not_register_failed_repair_verification(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    workspace = initialize_job_workspace(runs_root, "graph-runtime-repair-still-fails")
    _write_acceptance_criteria(workspace)
    graph = compile_skillfoundry_v2_graph(
        build_node_callable=build_offline_goal_harness_node(
            runs_root,
            verification_mode="fail_missing_coverage",
            created_at=CREATED_AT,
        ),
        verify_node_callable=build_verified_repair_verification_node(
            runs_root,
            registry_path=registry_path,
            created_at=CREATED_AT,
        ),
        repair_node_callable=build_repair_goal_harness_node(
            runs_root,
            created_at=CREATED_AT,
            worker_factory=_broken_repair_worker_factory(),
            continue_to_verification=True,
        ),
        registry_gate_callable=build_verified_registry_gate_node(
            runs_root,
            registry_path=registry_path,
            created_at=CREATED_AT,
        ),
    )

    result = graph.invoke({"job_id": workspace.job_id, "attempt_limit": 2})

    validate_v2_graph_state(result)
    assert result["stage"] == V2Stage.HUMAN_REVIEW.value
    assert result["status"] == V2Status.HUMAN_REVIEW_REQUIRED.value
    assert result["attempt_count"] == 2
    assert result["contextforge"]["last_repair_attempt_id"] == "002"
    assert result["contextforge"]["last_verification_status"] == "failed"
    assert result["contextforge"]["registry_approved"] is False
    assert "registry_entry" not in result["refs"]
    assert "registry_decision" not in result["refs"]
    assert not registry_path.exists()
    assert not (workspace.root / "registry" / "decision.json").exists()

    verified_runtime = json.loads(
        workspace.resolve_path(VERIFIED_GOAL_RUNTIME_RESULT_REF, must_exist=True).read_text()
    )
    assert verified_runtime["status"]["registry_approved"] is False
    assert verified_runtime["status"]["contextforge_verification"] == "failed"
    assert "final_report" not in verified_runtime["refs"]


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
