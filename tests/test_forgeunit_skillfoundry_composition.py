from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from forgeunit_skillfoundry import (
    EVIDENCE_SUMMARY_SCHEMA_VERSION,
    FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF,
    FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF,
    FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF,
    ForgeUnitSkillFoundryError,
    GRAPH_STATE_SCHEMA_VERSION,
    PRODUCT_STATE_SCHEMA_VERSION,
    SkillFactoryConfig,
    build_evidence_summary,
    build_product_state_payload,
    prepare_skill_factory_workspace,
    run_codex_skill_factory,
    run_skill_factory_graph,
)
from forgeunit_skillfoundry.testing import (
    INVALID_CODEX_SKILL,
    VALID_CODEX_SKILL,
    write_fake_codex_exec_command,
)
from skillfoundry.forgeunit_adapter import FORGEUNIT_REPAIR_PACKET_REF
from skillfoundry.graph_v2 import V2Route, V2Stage, V2Status, validate_v2_graph_state
from skillfoundry.registry import LocalSkillRegistry


def test_skill_factory_config_derives_mode_and_validates_inputs(tmp_path: Path) -> None:
    command_config = SkillFactoryConfig(
        runs_root=tmp_path / "runs",
        job_id="config-demo-001",
        registry_path=tmp_path / "registry.json",
        command="fake command",
    )
    repair_config = SkillFactoryConfig(
        runs_root=str(tmp_path / "runs"),
        job_id="config-demo-002",
        registry_path=str(tmp_path / "registry.json"),
        command="bad command",
        repair_command="repair command",
        attempt_limit=2,
    )

    assert command_config.mode == "command_bridge"
    assert command_config.runs_root == tmp_path / "runs"
    assert command_config.registry_path == tmp_path / "registry.json"
    assert repair_config.mode == "repair_command_bridge"
    assert repair_config.runs_root == tmp_path / "runs"

    with pytest.raises(ForgeUnitSkillFoundryError):
        SkillFactoryConfig(
            runs_root=tmp_path / "runs",
            job_id="../bad",
            registry_path=tmp_path / "registry.json",
            command="fake command",
        )
    with pytest.raises(ForgeUnitSkillFoundryError):
        SkillFactoryConfig(
            runs_root=tmp_path / "runs",
            job_id="config-demo-003",
            registry_path=tmp_path / "registry.json",
            command=" ",
        )
    with pytest.raises(ForgeUnitSkillFoundryError):
        SkillFactoryConfig(
            runs_root=tmp_path / "runs",
            job_id="config-demo-004",
            registry_path=tmp_path / "registry.json",
            command="bad command",
            repair_command="repair command",
            attempt_limit=1,
        )


def test_product_state_payload_is_refs_only_and_selective(tmp_path: Path) -> None:
    workspace = prepare_skill_factory_workspace(tmp_path / "runs", "state-demo-001")
    payload = build_product_state_payload(
        workspace,
        {
            "schema_version": "skillfoundry.graph_v2_state.v1",
            "job_id": workspace.job_id,
            "stage": V2Stage.EMIT_REPORT.value,
            "status": V2Status.REPORT_EMITTED.value,
            "attempt_count": 2,
            "attempt_limit": 2,
            "refs": {
                "adaptive_state": "adaptive/capability_state.json",
                "decision_ledger": "adaptive/decision_ledger.json",
                "final_report": "final_report.json",
                "latest_next_step_contract": "adaptive/next_step_contract_001.json",
                "latest_observation_report": "adaptive/observation_report_001.json",
                "latest_state_correction": "adaptive/state_correction_001.json",
                "registry_entry": "registry/entry.json",
                "ignored_internal_ref": "contextforge/internal.json",
            },
            "hashes": {},
            "contextforge": {
                "adaptive_latest_decision": "continue",
                "adaptive_latest_iteration": 1,
                "adaptive_latest_route": "final_verify",
                "adaptive_latest_verification_status": "passed",
                "last_verification_status": "passed",
                "registry_approved": True,
                "ignored_internal_status": "small-but-not-product-facing",
            },
            "human_review_required": False,
            "next_route": V2Route.CONTINUE.value,
        },
        mode="command_bridge",
        registry_path=tmp_path / "registry.json",
        created_at="2026-05-23T00:00:00Z",
    )
    serialized = json.dumps(payload)

    assert payload["schema_version"] == PRODUCT_STATE_SCHEMA_VERSION
    assert payload["refs"] == {
        "adaptive_state": "adaptive/capability_state.json",
        "decision_ledger": "adaptive/decision_ledger.json",
        "final_report": "final_report.json",
        "latest_next_step_contract": "adaptive/next_step_contract_001.json",
        "latest_observation_report": "adaptive/observation_report_001.json",
        "latest_state_correction": "adaptive/state_correction_001.json",
        "registry_entry": "registry/entry.json",
    }
    assert payload["adaptive_summary"] == {
        "latest_decision": "continue",
        "latest_iteration": 1,
        "latest_route": "final_verify",
        "latest_verification_status": "passed",
    }
    assert payload["contextforge"] == {
        "last_verification_status": "passed",
        "registry_approved": True,
    }
    assert payload["trust_boundaries"]["worker_self_report_is_not_acceptance"] is True
    assert payload["trust_boundaries"]["adaptive_artifact_bodies_included"] is False
    assert payload["trust_boundaries"]["raw_prompt_included"] is False
    assert "ignored_internal_ref" not in serialized
    assert "ignored_internal_status" not in serialized
    assert "raw prompt body" not in serialized
    assert "raw transcript body" not in serialized


def test_evidence_summary_payload_is_refs_only_and_attempt_aware(tmp_path: Path) -> None:
    workspace = prepare_skill_factory_workspace(tmp_path / "runs", "summary-demo-001")
    workspace.resolve_path("attempts/001").mkdir(parents=True, exist_ok=True)
    workspace.resolve_path("attempts/001/input_manifest.json").write_text("{}\n", encoding="utf-8")
    workspace.resolve_path("attempts/001/execution_report.json").write_text("{}\n", encoding="utf-8")

    payload = build_evidence_summary(
        workspace,
        {
            "schema_version": "skillfoundry.graph_v2_state.v1",
            "job_id": workspace.job_id,
            "stage": V2Stage.EMIT_REPORT.value,
            "status": V2Status.REPORT_EMITTED.value,
            "attempt_count": 1,
            "attempt_limit": 2,
            "refs": {
                "adaptive_state": "adaptive/capability_state.json",
                "decision_ledger": "adaptive/decision_ledger.json",
                "final_report": "final_report.json",
                "latest_next_step_contract": "adaptive/next_step_contract_001.json",
                "latest_observation_report": "adaptive/observation_report_001.json",
                "latest_state_correction": "adaptive/state_correction_001.json",
                "registry_decision": "registry/decision.json",
                "registry_entry": "registry/entry.json",
                "skillfoundry_verification_result": "verifier/verification_result.json",
                "ignored_internal_ref": "contextforge/internal.json",
            },
            "hashes": {},
            "contextforge": {
                "adaptive_latest_decision": "continue",
                "adaptive_latest_iteration": 2,
                "adaptive_latest_route": "closure",
                "adaptive_latest_verification_status": "passed",
                "last_verification_status": "passed",
                "registry_approved": True,
                "registry_skill_id": "summary-demo-001-skill",
                "registry_version": "summary-demo",
                "ignored_internal_status": "small-but-not-product-facing",
            },
            "human_review_required": False,
            "next_route": V2Route.CONTINUE.value,
        },
        mode="command_bridge",
        registry_path=tmp_path / "registry.json",
        created_at="2026-05-23T00:00:00Z",
    )
    serialized = json.dumps(payload)

    assert payload["schema_version"] == EVIDENCE_SUMMARY_SCHEMA_VERSION
    assert payload["verification"]["status"] == "passed"
    assert payload["verification"]["passed"] is True
    assert payload["adaptive_summary"] == {
        "latest_decision": "continue",
        "latest_iteration": 2,
        "latest_route": "closure",
        "latest_verification_status": "passed",
    }
    assert payload["registry"]["approved"] is True
    assert payload["registry"]["skill_id"] == "summary-demo-001-skill"
    assert payload["refs"]["adaptive_state"] == "adaptive/capability_state.json"
    assert payload["refs"]["latest_next_step_contract"] == "adaptive/next_step_contract_001.json"
    assert payload["refs"]["latest_observation_report"] == "adaptive/observation_report_001.json"
    assert payload["refs"]["latest_state_correction"] == "adaptive/state_correction_001.json"
    assert payload["refs"]["decision_ledger"] == "adaptive/decision_ledger.json"
    assert payload["refs"]["forgeunit_skillfoundry_summary"] == FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    assert payload["attempts"] == [
        {
            "attempt_id": "001",
            "input_manifest_ref": "attempts/001/input_manifest.json",
            "execution_report_ref": "attempts/001/execution_report.json",
        }
    ]
    assert payload["trust_boundaries"]["command_string_included"] is False
    assert "ignored_internal_ref" not in serialized
    assert "ignored_internal_status" not in serialized
    assert "raw prompt body" not in serialized
    assert "raw transcript body" not in serialized


def test_clean_composition_happy_path_registers_offline(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    workspace = prepare_skill_factory_workspace(
        runs_root,
        "clean-composition-001",
        worker_input="private clean composition happy path request must stay file-only",
    )
    script = write_fake_codex_exec_command(workspace.root)

    result = run_codex_skill_factory(
        runs_root,
        workspace.job_id,
        registry_path=registry_path,
        command=f"{sys.executable} {script.name}",
        version="clean-composition-happy",
        created_at="2026-05-23T00:00:00Z",
    )
    state = result.state
    serialized_state = json.dumps(state)
    product_state = json.loads(
        workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF, must_exist=True).read_text()
    )
    summary = json.loads(workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF, must_exist=True).read_text())
    entry = LocalSkillRegistry(registry_path).get("clean-composition-001-skill", "clean-composition-happy")
    registry_report = LocalSkillRegistry(registry_path).verify_entry(entry)

    validate_v2_graph_state(state)
    assert result.mode == "command_bridge"
    assert state["stage"] == V2Stage.EMIT_REPORT.value
    assert state["status"] == V2Status.REPORT_EMITTED.value
    assert state["refs"]["forgeunit_skillfoundry_product_state"] == FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF
    assert state["refs"]["forgeunit_skillfoundry_summary"] == FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    assert state["contextforge"]["forgeunit_skillfoundry_engine"] == "forgeunit"
    assert state["contextforge"]["forgeunit_skillfoundry_mode"] == "command_bridge"
    assert state["contextforge"]["forgeunit_skillfoundry_summary_ref"] == FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    assert state["contextforge"]["last_verification_status"] == "passed"
    assert state["contextforge"]["registry_approved"] is True
    assert product_state["engine"] == "forgeunit"
    assert product_state["mode"] == "command_bridge"
    assert product_state["trust_boundaries"]["worker_self_report_is_not_acceptance"] is True
    assert product_state["trust_boundaries"]["raw_prompt_included"] is False
    assert product_state["trust_boundaries"]["raw_transcript_included"] is False
    assert product_state["trust_boundaries"]["raw_worker_input_included"] is False
    assert product_state["trust_boundaries"]["package_body_included"] is False
    assert product_state["trust_boundaries"]["live_codex_required"] is False
    assert summary["schema_version"] == EVIDENCE_SUMMARY_SCHEMA_VERSION
    assert summary["verification"]["passed"] is True
    assert summary["registry"]["approved"] is True
    assert summary["refs"]["forgeunit_skillfoundry_summary"] == FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    assert registry_report.valid is True
    assert "private clean composition happy path request" not in serialized_state
    assert "ForgeUnit SkillFoundry Composition Skill" not in serialized_state
    assert "deterministic forgeunit skillfoundry transcript" not in serialized_state
    assert "raw_prompt" not in serialized_state
    assert "raw_transcript" not in serialized_state
    assert "package_content" not in serialized_state


def test_clean_langgraph_happy_path_registers_offline(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    workspace = prepare_skill_factory_workspace(
        runs_root,
        "clean-graph-001",
        worker_input="private clean graph happy path request must stay file-only",
    )
    script = write_fake_codex_exec_command(workspace.root)
    config = SkillFactoryConfig(
        runs_root=runs_root,
        job_id=workspace.job_id,
        registry_path=registry_path,
        command=f"{sys.executable} {script.name}",
        version="clean-graph-happy",
        created_at="2026-05-23T00:00:00Z",
    )

    result = run_skill_factory_graph(config)
    state = result.state
    serialized_state = json.dumps(state)
    graph_state = json.loads(
        workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF, must_exist=True).read_text()
    )
    product_state = json.loads(
        workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF, must_exist=True).read_text()
    )
    summary = json.loads(workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF, must_exist=True).read_text())
    entry = LocalSkillRegistry(registry_path).get("clean-graph-001-skill", "clean-graph-happy")
    registry_report = LocalSkillRegistry(registry_path).verify_entry(entry)

    validate_v2_graph_state(state)
    assert result.mode == "command_bridge"
    assert state["stage"] == V2Stage.EMIT_REPORT.value
    assert state["status"] == V2Status.REPORT_EMITTED.value
    assert state["refs"]["forgeunit_skillfoundry_graph_state"] == FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF
    assert state["refs"]["forgeunit_skillfoundry_product_state"] == FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF
    assert state["refs"]["forgeunit_skillfoundry_summary"] == FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    assert state["contextforge"]["forgeunit_skillfoundry_graph_node"] == "emit_product_report"
    assert state["contextforge"]["last_verification_status"] == "passed"
    assert state["contextforge"]["registry_approved"] is True
    assert graph_state["schema_version"] == GRAPH_STATE_SCHEMA_VERSION
    assert graph_state["mode"] == "command_bridge"
    assert graph_state["refs"]["forgeunit_skillfoundry_product_state"] == FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF
    assert graph_state["trust_boundaries"]["command_string_included"] is False
    assert product_state["mode"] == "command_bridge"
    assert summary["mode"] == "command_bridge"
    assert summary["refs"]["forgeunit_skillfoundry_graph_state"] == FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF
    assert summary["refs"]["forgeunit_skillfoundry_product_state"] == FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF
    assert summary["refs"]["forgeunit_skillfoundry_summary"] == FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    assert summary["attempts"][0]["attempt_id"] == "001"
    assert registry_report.valid is True
    assert "private clean graph happy path request" not in serialized_state
    assert "fake_codex_exec.py" not in serialized_state
    assert "ForgeUnit SkillFoundry Composition Skill" not in serialized_state
    assert "deterministic forgeunit skillfoundry transcript" not in serialized_state
    assert "raw_prompt" not in serialized_state
    assert "raw_transcript" not in serialized_state
    assert "package_content" not in serialized_state


def test_clean_composition_repair_path_registers_offline(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    workspace = prepare_skill_factory_workspace(
        runs_root,
        "clean-composition-002",
        worker_input="private clean composition repair path request must stay file-only",
    )
    bad_script = write_fake_codex_exec_command(
        workspace.root,
        skill_text=INVALID_CODEX_SKILL,
        script_name="fake_bad_codex_exec.py",
    )
    repair_script = write_fake_codex_exec_command(
        workspace.root,
        skill_text=VALID_CODEX_SKILL,
        script_name="fake_repair_codex_exec.py",
    )

    result = run_codex_skill_factory(
        runs_root,
        workspace.job_id,
        registry_path=registry_path,
        command=f"{sys.executable} {bad_script.name}",
        repair_command=f"{sys.executable} {repair_script.name}",
        version="clean-composition-repair",
        created_at="2026-05-23T00:00:00Z",
    )
    state = result.state
    serialized_state = json.dumps(state)
    product_state = json.loads(
        workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF, must_exist=True).read_text()
    )
    summary = json.loads(workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF, must_exist=True).read_text())
    first_verification = json.loads(
        workspace.resolve_path("attempts/001/verification_result.json", must_exist=True).read_text()
    )
    second_verification = json.loads(
        workspace.resolve_path("attempts/002/verification_result.json", must_exist=True).read_text()
    )
    repair_packet = json.loads(workspace.resolve_path(FORGEUNIT_REPAIR_PACKET_REF, must_exist=True).read_text())
    entry = LocalSkillRegistry(registry_path).get("clean-composition-002-skill", "clean-composition-repair")
    registry_report = LocalSkillRegistry(registry_path).verify_entry(entry)

    validate_v2_graph_state(state)
    assert result.mode == "repair_command_bridge"
    assert state["stage"] == V2Stage.EMIT_REPORT.value
    assert state["status"] == V2Status.REPORT_EMITTED.value
    assert state["refs"]["forgeunit_skillfoundry_product_state"] == FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF
    assert state["refs"]["forgeunit_skillfoundry_summary"] == FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    assert state["refs"]["forgeunit_repair_packet"] == FORGEUNIT_REPAIR_PACKET_REF
    assert state["contextforge"]["forgeunit_skillfoundry_mode"] == "repair_command_bridge"
    assert state["contextforge"]["forgeunit_repair_status"] == "repaired_and_verified"
    assert state["contextforge"]["last_verification_status"] == "passed"
    assert state["contextforge"]["registry_approved"] is True
    assert first_verification["passed"] is False
    assert second_verification["passed"] is True
    assert repair_packet["failed_attempt_id"] == "001"
    assert repair_packet["repair_attempt_id"] == "002"
    assert product_state["mode"] == "repair_command_bridge"
    assert product_state["refs"]["forgeunit_repair_packet"] == FORGEUNIT_REPAIR_PACKET_REF
    assert product_state["contextforge"]["forgeunit_repair_status"] == "repaired_and_verified"
    assert product_state["trust_boundaries"]["worker_self_report_is_not_acceptance"] is True
    assert summary["mode"] == "repair_command_bridge"
    assert summary["refs"]["forgeunit_repair_packet"] == FORGEUNIT_REPAIR_PACKET_REF
    assert summary["attempts"][0]["verification_result_ref"] == "attempts/001/verification_result.json"
    assert summary["attempts"][1]["verification_result_ref"] == "attempts/002/verification_result.json"
    assert registry_report.valid is True
    assert "private clean composition repair path request" not in serialized_state
    assert "ForgeUnit SkillFoundry Composition Skill" not in serialized_state
    assert "ForgeUnit SkillFoundry Invalid Fixture" not in serialized_state
    assert "deterministic forgeunit skillfoundry transcript" not in serialized_state
    assert "raw_prompt" not in serialized_state
    assert "raw_transcript" not in serialized_state
    assert "package_content" not in serialized_state


def test_clean_langgraph_repair_path_registers_offline(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    workspace = prepare_skill_factory_workspace(
        runs_root,
        "clean-graph-002",
        worker_input="private clean graph repair path request must stay file-only",
    )
    bad_script = write_fake_codex_exec_command(
        workspace.root,
        skill_text=INVALID_CODEX_SKILL,
        script_name="fake_bad_codex_exec.py",
    )
    repair_script = write_fake_codex_exec_command(
        workspace.root,
        skill_text=VALID_CODEX_SKILL,
        script_name="fake_repair_codex_exec.py",
    )
    config = SkillFactoryConfig(
        runs_root=runs_root,
        job_id=workspace.job_id,
        registry_path=registry_path,
        command=f"{sys.executable} {bad_script.name}",
        repair_command=f"{sys.executable} {repair_script.name}",
        version="clean-graph-repair",
        created_at="2026-05-23T00:00:00Z",
    )

    result = run_skill_factory_graph(config)
    state = result.state
    serialized_state = json.dumps(state)
    graph_state = json.loads(
        workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF, must_exist=True).read_text()
    )
    product_state = json.loads(
        workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF, must_exist=True).read_text()
    )
    summary = json.loads(workspace.resolve_path(FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF, must_exist=True).read_text())
    first_verification = json.loads(
        workspace.resolve_path("attempts/001/verification_result.json", must_exist=True).read_text()
    )
    second_verification = json.loads(
        workspace.resolve_path("attempts/002/verification_result.json", must_exist=True).read_text()
    )
    repair_packet = json.loads(workspace.resolve_path(FORGEUNIT_REPAIR_PACKET_REF, must_exist=True).read_text())
    entry = LocalSkillRegistry(registry_path).get("clean-graph-002-skill", "clean-graph-repair")
    registry_report = LocalSkillRegistry(registry_path).verify_entry(entry)

    validate_v2_graph_state(state)
    assert result.mode == "repair_command_bridge"
    assert state["stage"] == V2Stage.EMIT_REPORT.value
    assert state["status"] == V2Status.REPORT_EMITTED.value
    assert state["refs"]["forgeunit_skillfoundry_graph_state"] == FORGEUNIT_SKILLFOUNDRY_GRAPH_STATE_REF
    assert state["refs"]["forgeunit_skillfoundry_product_state"] == FORGEUNIT_SKILLFOUNDRY_PRODUCT_STATE_REF
    assert state["refs"]["forgeunit_skillfoundry_summary"] == FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    assert state["refs"]["forgeunit_repair_packet"] == FORGEUNIT_REPAIR_PACKET_REF
    assert state["contextforge"]["forgeunit_skillfoundry_graph_node"] == "emit_product_report"
    assert state["contextforge"]["forgeunit_repair_status"] == "repaired_and_verified"
    assert state["contextforge"]["last_verification_status"] == "passed"
    assert state["contextforge"]["registry_approved"] is True
    assert first_verification["passed"] is False
    assert second_verification["passed"] is True
    assert repair_packet["failed_attempt_id"] == "001"
    assert repair_packet["repair_attempt_id"] == "002"
    assert graph_state["schema_version"] == GRAPH_STATE_SCHEMA_VERSION
    assert graph_state["mode"] == "repair_command_bridge"
    assert graph_state["refs"]["forgeunit_repair_packet"] == FORGEUNIT_REPAIR_PACKET_REF
    assert graph_state["trust_boundaries"]["command_string_included"] is False
    assert product_state["mode"] == "repair_command_bridge"
    assert summary["mode"] == "repair_command_bridge"
    assert summary["registry"]["approved"] is True
    assert summary["verification"]["passed"] is True
    assert summary["refs"]["forgeunit_skillfoundry_summary"] == FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    assert registry_report.valid is True
    assert "private clean graph repair path request" not in serialized_state
    assert "fake_bad_codex_exec.py" not in serialized_state
    assert "fake_repair_codex_exec.py" not in serialized_state
    assert "ForgeUnit SkillFoundry Composition Skill" not in serialized_state
    assert "ForgeUnit SkillFoundry Invalid Fixture" not in serialized_state
    assert "deterministic forgeunit skillfoundry transcript" not in serialized_state
    assert "raw_prompt" not in serialized_state
    assert "raw_transcript" not in serialized_state
    assert "package_content" not in serialized_state
