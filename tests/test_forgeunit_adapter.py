from __future__ import annotations

import json
from pathlib import Path
import sys

import yaml

from forgeunit import validate_task_pack_or_raise
import skillfoundry.forgeunit_adapter as forgeunit_adapter
from skillfoundry.forgeunit_adapter import (
    FORGEUNIT_ADAPTER_VERSION,
    FORGEUNIT_BOUNDARY_VERIFICATION_REF,
    FORGEUNIT_FINAL_REPORT_REF,
    FORGEUNIT_PILOT_GRAPH_STATE_REF,
    FORGEUNIT_REGISTRY_DECISION_REF,
    FORGEUNIT_REGISTRY_ENTRY_REF,
    FORGEUNIT_REPAIR_ATTEMPT_ID,
    FORGEUNIT_REPAIR_GRAPH_STATE_REF,
    FORGEUNIT_REPAIR_PACKET_REF,
    FORGEUNIT_SUMMARY_REF,
    FORGEUNIT_TASK_YAML_REF,
    FORGEUNIT_VERIFICATION_RESULT_REF,
    build_forgeunit_codex_exec_node,
    materialize_forgeunit_task_pack,
    run_forgeunit_codex_exec_node,
    run_forgeunit_command_bridge_pilot_graph,
    run_forgeunit_pilot_graph,
    run_forgeunit_repair_pilot_graph,
)
from skillfoundry.graph_v2 import V2Stage, V2Status, validate_v2_graph_state
from skillfoundry.registry import LocalSkillRegistry
from skillfoundry.schema import sha256_file
from skillfoundry.workspace import initialize_job_workspace


VALID_FORGEUNIT_SKILL = """---
name: forgeunit-command-bridge-skill
description: Deterministic ForgeUnit command bridge fixture.
---

# ForgeUnit Command Bridge Skill

## Overview
This skill is a deterministic fixture package produced by the ForgeUnit command bridge pilot.

## When To Use
Use this fixture when testing the ForgeUnit command bridge path into SkillFoundry verifier and registry gates.

## When Not To Use
Do not use this fixture for live Codex calls, production skill authoring, or user-facing package generation.

## Inputs
Provide the frozen SkillFoundry skill spec, verification spec, build contract, and worker input refs.

## Outputs
Return a package/SKILL.md file plus boundary evidence refs for deterministic verifier registration.

## Workflow
1. Read the frozen refs.
2. Write the skill package.
3. Write boundary evidence.
4. Let SkillFoundry verifier and registry decide acceptance.

## Safety
Keep raw prompts, raw transcripts, and package bodies out of LangGraph state.
"""


INVALID_FORGEUNIT_SKILL = """---
name: forgeunit-repair-fixture
description: Intentionally incomplete fixture.
---

# ForgeUnit Repair Fixture

## Overview
This package is ForgeUnit-boundary valid but SkillFoundry-verifier invalid.
"""


def _write_fake_codex_exec_command(
    workspace_root: Path,
    *,
    skill_text: str = VALID_FORGEUNIT_SKILL,
    script_name: str = "fake_codex_exec.py",
) -> Path:
    script = workspace_root / script_name
    script.write_text(
        f"""
from pathlib import Path
import json
import os
import sys

_ = sys.stdin.read()
task_dir = Path(os.environ["FORGEUNIT_TASK_DIR"])
worker_result = Path(os.environ["FORGEUNIT_WORKER_RESULT"])
unit_id = os.environ["FORGEUNIT_UNIT"]

(task_dir / "package").mkdir(exist_ok=True)
(task_dir / "evidence").mkdir(exist_ok=True)
(task_dir / "package" / "SKILL.md").write_text({skill_text!r}, encoding="utf-8")
(task_dir / "evidence" / "transcript.md").write_text(
    "deterministic command bridge transcript pointer\\n",
    encoding="utf-8",
)
(task_dir / "evidence" / "manifest.json").write_text(json.dumps({{
    "schema": "forgeunit.worker_evidence_manifest",
    "version": "0.6",
    "unit_id": unit_id,
    "status": "completed",
    "output_artifacts": [
        {{"path": "package/SKILL.md", "kind": "codex_skill", "summary": "fixture skill package"}}
    ],
    "evidence_artifacts": [
        {{"path": "evidence/transcript.md", "kind": "transcript", "summary": "fixture transcript"}}
    ],
    "changed_files": ["package/SKILL.md", "evidence/transcript.md", "evidence/manifest.json"],
    "commands": [{{"command": "fake codex exec", "exit_code": 0, "summary": "fixture command passed"}}],
    "usage": None,
    "usage_unavailable_reason": "external_worker_no_provider_telemetry"
}}, indent=2), encoding="utf-8")
worker_result.write_text(json.dumps({{
    "status": "completed",
    "output_artifacts": [
        {{"path": "package/SKILL.md", "kind": "codex_skill", "summary": "fixture skill package"}}
    ],
    "boundary_evidence": [
        {{"path": "evidence/transcript.md", "kind": "transcript", "summary": "fixture transcript"}},
        {{"path": "evidence/manifest.json", "kind": "worker_evidence_manifest", "summary": "manifest"}}
    ],
    "changed_files": ["package/SKILL.md", "evidence/transcript.md", "evidence/manifest.json"],
    "usage": None,
    "usage_unavailable_reason": "external_worker_no_provider_telemetry"
}}, indent=2), encoding="utf-8")
""".strip(),
        encoding="utf-8",
    )
    return script


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


def test_forgeunit_command_bridge_pilot_verifies_and_registers_offline_package(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    workspace = initialize_job_workspace(
        runs_root,
        "forgeunit-command-001",
        worker_input="private command bridge request body must remain in file refs only",
    )
    script = _write_fake_codex_exec_command(workspace.root)

    result = run_forgeunit_command_bridge_pilot_graph(
        runs_root,
        workspace.job_id,
        registry_path=registry_path,
        command=f"{sys.executable} {script.name}",
        version="forgeunit-command-bridge-pilot",
        created_at="2026-05-23T00:00:00Z",
    )
    serialized_state = json.dumps(result)
    verification = json.loads(workspace.resolve_path(FORGEUNIT_VERIFICATION_RESULT_REF, must_exist=True).read_text())
    registry_entry_snapshot = json.loads(
        workspace.resolve_path(FORGEUNIT_REGISTRY_ENTRY_REF, must_exist=True).read_text()
    )
    registry_decision = json.loads(workspace.resolve_path(FORGEUNIT_REGISTRY_DECISION_REF, must_exist=True).read_text())
    entry = LocalSkillRegistry(registry_path).get("forgeunit-command-001-skill", "forgeunit-command-bridge-pilot")
    registry_report = LocalSkillRegistry(registry_path).verify_entry(entry)

    validate_v2_graph_state(result)
    assert result["stage"] == V2Stage.EMIT_REPORT.value
    assert result["status"] == V2Status.REPORT_EMITTED.value
    assert result["human_review_required"] is False
    assert result["refs"]["skillfoundry_verification_result"] == FORGEUNIT_VERIFICATION_RESULT_REF
    assert result["refs"]["registry_entry"] == FORGEUNIT_REGISTRY_ENTRY_REF
    assert result["refs"]["registry_decision"] == FORGEUNIT_REGISTRY_DECISION_REF
    assert result["refs"]["final_report"] == FORGEUNIT_FINAL_REPORT_REF
    assert result["contextforge"]["last_verification_status"] == "passed"
    assert result["contextforge"]["registry_approved"] is True
    assert verification["passed"] is True
    assert registry_decision["decision"] == "registered"
    assert registry_entry_snapshot["verification_report"]["valid"] is True
    assert registry_report.valid is True
    assert (
        workspace.resolve_path("package/SKILL.md", must_exist=True).read_text(encoding="utf-8")
        == VALID_FORGEUNIT_SKILL
    )
    assert workspace.resolve_path("attempts/001/input_manifest.json", must_exist=True).is_file()
    assert workspace.resolve_path("attempts/001/execution_report.json", must_exist=True).is_file()
    assert workspace.resolve_path("attempts/001/worker_transcript.log", must_exist=True).is_file()
    assert workspace.resolve_path("attempts/001/output_diff.patch", must_exist=True).is_file()
    assert workspace.resolve_path(FORGEUNIT_PILOT_GRAPH_STATE_REF, must_exist=True).is_file()
    assert "human_review_request" not in result["refs"]
    assert "private command bridge request body" not in serialized_state
    assert "ForgeUnit Command Bridge Skill" not in serialized_state
    assert "deterministic command bridge transcript" not in serialized_state
    assert "raw_prompt" not in serialized_state
    assert "raw_transcript" not in serialized_state
    assert "package_content" not in serialized_state


def test_acceptance_coverage_rerun_refreshes_artifact_manifest_hash(tmp_path: Path, monkeypatch) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "forgeunit-coverage-refresh")
    workspace.resolve_path("acceptance_criteria.yaml").write_text("criteria: []\n", encoding="utf-8")
    workspace.resolve_path("qa").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("qa/acceptance_coverage_plan.json").write_text('{"old": "plan"}\n', encoding="utf-8")
    workspace.resolve_path("qa/acceptance_coverage_result.json").write_text(
        '{"old": "result"}\n',
        encoding="utf-8",
    )
    forgeunit_adapter._upsert_manifest_records(
        workspace,
        ["qa/acceptance_coverage_plan.json", "qa/acceptance_coverage_result.json"],
        created_by="test",
    )
    old_result_hash = sha256_file(workspace.resolve_path("qa/acceptance_coverage_result.json", must_exist=True))

    class FakePlanner:
        def plan(self, workspace):
            workspace.resolve_path("qa/acceptance_coverage_plan.json").write_text(
                '{"new": "plan"}\n',
                encoding="utf-8",
            )
            return object()

    class FakeCoverageResult:
        passed = True

    class FakeEvaluator:
        def evaluate(self, workspace, *, plan):
            workspace.resolve_path("qa/acceptance_coverage_result.json").write_text(
                '{"new": "result"}\n',
                encoding="utf-8",
            )
            return FakeCoverageResult()

    monkeypatch.setattr(forgeunit_adapter, "AcceptanceCriteriaPlanner", FakePlanner)
    monkeypatch.setattr(forgeunit_adapter, "AcceptanceCoverageEvaluator", FakeEvaluator)
    state = {
        "schema_version": "skillfoundry.graph_v2_state.v1",
        "job_id": workspace.job_id,
        "stage": V2Stage.VERIFY.value,
        "status": V2Status.VERIFIED.value,
        "attempt_count": 1,
        "attempt_limit": 1,
        "refs": {},
        "hashes": {},
        "contextforge": {},
        "human_review_required": False,
        "next_route": "continue",
    }

    next_state = forgeunit_adapter._maybe_write_acceptance_coverage(workspace, state)

    new_result_hash = sha256_file(workspace.resolve_path("qa/acceptance_coverage_result.json", must_exist=True))
    manifest_record = next(
        record for record in workspace.read_manifest().artifacts if record.path == "qa/acceptance_coverage_result.json"
    )
    assert new_result_hash != old_result_hash
    assert manifest_record.sha256 == new_result_hash
    assert next_state["hashes"]["acceptance_coverage_result"] == new_result_hash


def test_existing_verifier_outputs_refresh_artifact_manifest_hash(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "forgeunit-verifier-refresh")
    verifier_ref = "verifier/verification_result.json"
    workspace.resolve_path(verifier_ref).write_text('{"old": "verifier"}\n', encoding="utf-8")
    forgeunit_adapter._upsert_manifest_records(workspace, [verifier_ref], created_by="test")
    old_hash = sha256_file(workspace.resolve_path(verifier_ref, must_exist=True))

    workspace.resolve_path(verifier_ref).write_text('{"new": "verifier"}\n', encoding="utf-8")
    forgeunit_adapter._upsert_existing_manifest_records(
        workspace,
        [verifier_ref, "verifier/missing.json"],
        created_by="test-refresh",
    )

    new_hash = sha256_file(workspace.resolve_path(verifier_ref, must_exist=True))
    manifest_record = next(record for record in workspace.read_manifest().artifacts if record.path == verifier_ref)
    assert new_hash != old_hash
    assert manifest_record.sha256 == new_hash
    assert manifest_record.created_by == "test-refresh"


def test_forgeunit_repair_pilot_registers_initial_success_without_repair(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    workspace = initialize_job_workspace(
        runs_root,
        "forgeunit-repair-initial-success",
        worker_input="private initial success repair bridge request must remain in file refs only",
    )
    build_script = _write_fake_codex_exec_command(
        workspace.root,
        skill_text=VALID_FORGEUNIT_SKILL,
        script_name="fake_initial_success_codex_exec.py",
    )
    unused_repair_script = _write_fake_codex_exec_command(
        workspace.root,
        skill_text=INVALID_FORGEUNIT_SKILL,
        script_name="fake_unused_repair_codex_exec.py",
    )

    result = run_forgeunit_repair_pilot_graph(
        runs_root,
        workspace.job_id,
        registry_path=registry_path,
        build_command=f"{sys.executable} {build_script.name}",
        repair_command=f"{sys.executable} {unused_repair_script.name}",
        version="forgeunit-repair-initial-success",
        created_at="2026-05-23T00:00:00Z",
    )
    serialized_state = json.dumps(result)
    first_verification = json.loads(
        workspace.resolve_path("attempts/001/verification_result.json", must_exist=True).read_text()
    )
    entry = LocalSkillRegistry(registry_path).get(
        "forgeunit-repair-initial-success-skill",
        "forgeunit-repair-initial-success",
    )
    registry_report = LocalSkillRegistry(registry_path).verify_entry(entry)

    validate_v2_graph_state(result)
    assert result["stage"] == V2Stage.EMIT_REPORT.value
    assert result["status"] == V2Status.REPORT_EMITTED.value
    assert result["human_review_required"] is False
    assert result["refs"]["forgeunit_initial_verification_result"] == "attempts/001/verification_result.json"
    assert "forgeunit_repair_packet" not in result["refs"]
    assert "forgeunit_repair_verification_result" not in result["refs"]
    assert result["refs"]["registry_decision"] == FORGEUNIT_REGISTRY_DECISION_REF
    assert result["refs"]["final_report"] == FORGEUNIT_FINAL_REPORT_REF
    assert result["contextforge"]["last_verification_status"] == "passed"
    assert result["contextforge"]["registry_approved"] is True
    assert result["contextforge"]["forgeunit_repair_status"] == "initial_verified_no_repair"
    assert first_verification["passed"] is True
    assert not workspace.resolve_path("attempts/002").exists()
    assert not workspace.resolve_path(FORGEUNIT_REPAIR_PACKET_REF).exists()
    assert registry_report.valid is True
    assert "private initial success repair bridge request" not in serialized_state
    assert "ForgeUnit Command Bridge Skill" not in serialized_state
    assert "ForgeUnit Repair Fixture" not in serialized_state


def test_forgeunit_repair_pilot_repairs_failed_verifier_package_and_registers(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    workspace = initialize_job_workspace(
        runs_root,
        "forgeunit-repair-001",
        worker_input="private repair command bridge request body must remain in file refs only",
    )
    bad_script = _write_fake_codex_exec_command(
        workspace.root,
        skill_text=INVALID_FORGEUNIT_SKILL,
        script_name="fake_bad_codex_exec.py",
    )
    repair_script = _write_fake_codex_exec_command(
        workspace.root,
        skill_text=VALID_FORGEUNIT_SKILL,
        script_name="fake_repair_codex_exec.py",
    )

    result = run_forgeunit_repair_pilot_graph(
        runs_root,
        workspace.job_id,
        registry_path=registry_path,
        build_command=f"{sys.executable} {bad_script.name}",
        repair_command=f"{sys.executable} {repair_script.name}",
        version="forgeunit-repair-pilot",
        created_at="2026-05-23T00:00:00Z",
    )
    serialized_state = json.dumps(result)
    first_verification = json.loads(
        workspace.resolve_path("attempts/001/verification_result.json", must_exist=True).read_text()
    )
    second_verification = json.loads(
        workspace.resolve_path("attempts/002/verification_result.json", must_exist=True).read_text()
    )
    repair_packet = json.loads(workspace.resolve_path(FORGEUNIT_REPAIR_PACKET_REF, must_exist=True).read_text())
    registry_decision = json.loads(workspace.resolve_path(FORGEUNIT_REGISTRY_DECISION_REF, must_exist=True).read_text())
    registry_entry_snapshot = json.loads(
        workspace.resolve_path(FORGEUNIT_REGISTRY_ENTRY_REF, must_exist=True).read_text()
    )
    entry = LocalSkillRegistry(registry_path).get("forgeunit-repair-001-skill", "forgeunit-repair-pilot")
    registry_report = LocalSkillRegistry(registry_path).verify_entry(entry)

    validate_v2_graph_state(result)
    assert result["stage"] == V2Stage.EMIT_REPORT.value
    assert result["status"] == V2Status.REPORT_EMITTED.value
    assert result["human_review_required"] is False
    assert result["refs"]["forgeunit_repair_packet"] == FORGEUNIT_REPAIR_PACKET_REF
    assert result["refs"]["forgeunit_initial_verification_result"] == "attempts/001/verification_result.json"
    assert result["refs"]["forgeunit_repair_verification_result"] == "attempts/002/verification_result.json"
    assert result["refs"]["forgeunit_repair_graph_state"] == FORGEUNIT_REPAIR_GRAPH_STATE_REF
    assert result["refs"]["registry_entry"] == FORGEUNIT_REGISTRY_ENTRY_REF
    assert result["refs"]["registry_decision"] == FORGEUNIT_REGISTRY_DECISION_REF
    assert result["refs"]["final_report"] == FORGEUNIT_FINAL_REPORT_REF
    assert result["contextforge"]["last_verification_status"] == "passed"
    assert result["contextforge"]["registry_approved"] is True
    assert result["contextforge"]["forgeunit_repair_attempt_id"] == FORGEUNIT_REPAIR_ATTEMPT_ID
    assert result["contextforge"]["forgeunit_repair_status"] == "repaired_and_verified"
    assert first_verification["passed"] is False
    assert second_verification["passed"] is True
    assert repair_packet["failed_attempt_id"] == "001"
    assert repair_packet["repair_attempt_id"] == "002"
    assert repair_packet["verification_result_ref"] == "attempts/001/verification_result.json"
    assert repair_packet["failed_forgeunit_summary_ref"] == "attempts/001/forgeunit_summary.json"
    assert repair_packet["failure_count"] >= 1
    assert repair_packet["trust_boundaries"]["worker_self_report_is_not_acceptance"] is True
    assert repair_packet["trust_boundaries"]["raw_prompt_included"] is False
    assert repair_packet["trust_boundaries"]["raw_transcript_included"] is False
    assert repair_packet["trust_boundaries"]["package_body_included"] is False
    assert repair_packet["trust_boundaries"]["raw_worker_input_included"] is False
    assert registry_decision["decision"] == "registered"
    assert registry_decision["verification_result_ref"] == FORGEUNIT_VERIFICATION_RESULT_REF
    assert registry_entry_snapshot["verification_report"]["valid"] is True
    assert registry_report.valid is True
    assert workspace.resolve_path("attempts/001/forgeunit_summary.json", must_exist=True).is_file()
    assert workspace.resolve_path("attempts/002/forgeunit_summary.json", must_exist=True).is_file()
    assert workspace.resolve_path("attempts/002/input_manifest.json", must_exist=True).is_file()
    assert workspace.resolve_path("attempts/002/execution_report.json", must_exist=True).is_file()
    assert workspace.resolve_path("attempts/002/worker_transcript.log", must_exist=True).is_file()
    assert workspace.resolve_path("attempts/002/output_diff.patch", must_exist=True).is_file()
    assert workspace.resolve_path(FORGEUNIT_REPAIR_GRAPH_STATE_REF, must_exist=True).is_file()
    assert "private repair command bridge request body" not in serialized_state
    assert "ForgeUnit Command Bridge Skill" not in serialized_state
    assert "ForgeUnit Repair Fixture" not in serialized_state
    assert "deterministic command bridge transcript" not in serialized_state
    assert "raw_prompt" not in serialized_state
    assert "raw_transcript" not in serialized_state
    assert "package_content" not in serialized_state
