from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from forgeunit_skillfoundry import (
    EVIDENCE_SUMMARY_SCHEMA_VERSION,
    FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF,
    ForgeUnitSkillFoundryError,
    prepare_skill_factory_workspace,
    read_evidence_summary,
    run_existing_workspace_skill_factory,
    run_frozen_frontdesk_skill_factory,
)
from forgeunit_skillfoundry.adapters import FRONTDESK_STATE_REF
from forgeunit_skillfoundry.testing import (
    INVALID_CODEX_SKILL,
    VALID_CODEX_SKILL,
    write_fake_codex_exec_command,
)
from skillfoundry.forgeunit_adapter import FORGEUNIT_REPAIR_PACKET_REF
from skillfoundry.frontdesk_schema import (
    AcceptanceCriteriaSet,
    AcceptanceCriterion,
    FreezeManifest,
    FrontDeskState,
)
from skillfoundry.graph_v2 import V2Stage, V2Status, validate_v2_graph_state
from skillfoundry.registry import LocalSkillRegistry
from skillfoundry.schema import sha256_file
from skillfoundry.workspace import JobWorkspace


def test_existing_workspace_adapter_happy_path_registers_offline_refs_only(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    worker_input = "private existing workspace adapter request must stay file-only"
    workspace = prepare_skill_factory_workspace(runs_root, "adapter-workspace-001", worker_input=worker_input)
    script = write_fake_codex_exec_command(workspace.root)
    command = f"{sys.executable} {script.name}"

    result = run_existing_workspace_skill_factory(
        workspace,
        registry_path=registry_path,
        command=command,
        version="adapter-happy",
        created_at="2026-05-23T00:00:00Z",
    )

    summary = read_evidence_summary(workspace)
    serialized = json.dumps(result.state, sort_keys=True) + json.dumps(summary, sort_keys=True)
    entry = LocalSkillRegistry(registry_path).get("adapter-workspace-001-skill", "adapter-happy")
    registry_report = LocalSkillRegistry(registry_path).verify_entry(entry)

    validate_v2_graph_state(result.state)
    assert result.workspace_root == workspace.root
    assert result.mode == "command_bridge"
    assert result.state["stage"] == V2Stage.EMIT_REPORT.value
    assert result.state["status"] == V2Status.REPORT_EMITTED.value
    assert result.refs["forgeunit_skillfoundry_summary"] == FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF
    assert summary["schema_version"] == EVIDENCE_SUMMARY_SCHEMA_VERSION
    assert summary["mode"] == "command_bridge"
    assert summary["verification"]["passed"] is True
    assert summary["registry"]["approved"] is True
    assert summary["trust_boundaries"]["command_string_included"] is False
    assert registry_report.valid is True
    assert worker_input not in serialized
    assert command not in serialized
    assert script.name not in serialized
    assert "ForgeUnit SkillFoundry Composition Skill" not in serialized
    assert "deterministic forgeunit skillfoundry transcript" not in serialized


def test_existing_workspace_adapter_repair_path_registers_offline_refs_only(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    worker_input = "private existing workspace adapter repair request must stay file-only"
    workspace = prepare_skill_factory_workspace(runs_root, "adapter-workspace-002", worker_input=worker_input)
    bad_script = write_fake_codex_exec_command(
        workspace.root,
        skill_text=INVALID_CODEX_SKILL,
        script_name="fake_adapter_bad_codex_exec.py",
    )
    repair_script = write_fake_codex_exec_command(
        workspace.root,
        skill_text=VALID_CODEX_SKILL,
        script_name="fake_adapter_repair_codex_exec.py",
    )
    bad_command = f"{sys.executable} {bad_script.name}"
    repair_command = f"{sys.executable} {repair_script.name}"

    result = run_existing_workspace_skill_factory(
        workspace,
        registry_path=registry_path,
        command=bad_command,
        repair_command=repair_command,
        version="adapter-repair",
        created_at="2026-05-23T00:00:00Z",
    )

    summary = read_evidence_summary(workspace)
    serialized = json.dumps(result.state, sort_keys=True) + json.dumps(summary, sort_keys=True)
    repair_packet = json.loads(workspace.resolve_path(FORGEUNIT_REPAIR_PACKET_REF, must_exist=True).read_text())
    entry = LocalSkillRegistry(registry_path).get("adapter-workspace-002-skill", "adapter-repair")
    registry_report = LocalSkillRegistry(registry_path).verify_entry(entry)

    validate_v2_graph_state(result.state)
    assert result.mode == "repair_command_bridge"
    assert result.refs["forgeunit_repair_packet"] == FORGEUNIT_REPAIR_PACKET_REF
    assert summary["mode"] == "repair_command_bridge"
    assert summary["verification"]["passed"] is True
    assert summary["registry"]["approved"] is True
    assert summary["refs"]["forgeunit_repair_packet"] == FORGEUNIT_REPAIR_PACKET_REF
    assert summary["attempts"][0]["attempt_id"] == "001"
    assert summary["attempts"][1]["attempt_id"] == "002"
    assert repair_packet["failed_attempt_id"] == "001"
    assert repair_packet["repair_attempt_id"] == "002"
    assert registry_report.valid is True
    assert worker_input not in serialized
    assert bad_command not in serialized
    assert repair_command not in serialized
    assert bad_script.name not in serialized
    assert repair_script.name not in serialized
    assert "ForgeUnit SkillFoundry Invalid Fixture" not in serialized
    assert "ForgeUnit SkillFoundry Composition Skill" not in serialized


def test_frozen_frontdesk_adapter_routes_existing_workspace_through_vnext(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry_path = tmp_path / "registry.json"
    worker_input = "private frozen frontdesk adapter request must stay file-only"
    workspace = prepare_skill_factory_workspace(runs_root, "adapter-frontdesk-001", worker_input=worker_input)
    _write_frozen_frontdesk_boundary(workspace)
    script = write_fake_codex_exec_command(workspace.root)
    command = f"{sys.executable} {script.name}"

    result = run_frozen_frontdesk_skill_factory(
        workspace,
        registry_path=registry_path,
        command=command,
        version="adapter-frontdesk",
        created_at="2026-05-23T00:00:00Z",
    )

    summary = read_evidence_summary(workspace)
    serialized = json.dumps(result.state, sort_keys=True) + json.dumps(summary, sort_keys=True)
    entry = LocalSkillRegistry(registry_path).get("adapter-frontdesk-001-skill", "adapter-frontdesk")
    registry_report = LocalSkillRegistry(registry_path).verify_entry(entry)

    validate_v2_graph_state(result.state)
    assert result.mode == "command_bridge"
    assert summary["mode"] == "command_bridge"
    assert summary["verification"]["passed"] is True
    assert summary["registry"]["approved"] is True
    assert summary["refs"]["acceptance_coverage_result"] == "qa/acceptance_coverage_result.json"
    assert registry_report.valid is True
    assert worker_input not in serialized
    assert command not in serialized
    assert script.name not in serialized
    assert "frontdesk frozen state raw conversation" not in serialized


@pytest.mark.parametrize(
    ("readiness", "next_action"),
    [
        ("awaiting_plan_review", "await_user_plan_review"),
        ("frozen", "freeze_spec"),
        ("plan_approved", "route_to_build"),
    ],
)
def test_frozen_frontdesk_adapter_refuses_non_frozen_route_to_build_state(
    tmp_path: Path,
    readiness: str,
    next_action: str,
) -> None:
    workspace = prepare_skill_factory_workspace(tmp_path / "runs", "adapter-frontdesk-gate-001")
    _write_frontdesk_state(
        workspace,
        readiness=readiness,
        next_action=next_action,
        freeze_manifest_ref=None,
    )

    with pytest.raises(ForgeUnitSkillFoundryError, match="frozen"):
        run_frozen_frontdesk_skill_factory(
            workspace,
            registry_path=tmp_path / "registry.json",
            command="explicit command should not run",
        )

    assert not (workspace.root / FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF).exists()


def test_frozen_frontdesk_adapter_refuses_tampered_freeze_manifest_hash(tmp_path: Path) -> None:
    workspace = prepare_skill_factory_workspace(tmp_path / "runs", "adapter-frontdesk-tamper-001")
    _write_frozen_frontdesk_boundary(workspace)
    workspace.resolve_path("acceptance_criteria.yaml", must_exist=True).write_text(
        "tampered: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ForgeUnitSkillFoundryError, match="hash mismatch"):
        run_frozen_frontdesk_skill_factory(
            workspace,
            registry_path=tmp_path / "registry.json",
            command="explicit command should not run",
        )

    assert not (workspace.root / FORGEUNIT_SKILLFOUNDRY_SUMMARY_REF).exists()


def _write_frontdesk_state(
    workspace: JobWorkspace,
    *,
    readiness: str,
    next_action: str,
    freeze_manifest_ref: str | None,
) -> None:
    workspace.resolve_path("frontdesk").mkdir(parents=True, exist_ok=True)
    state_path = workspace.resolve_path(FRONTDESK_STATE_REF)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    FrontDeskState(
        job_id=workspace.job_id,
        readiness=readiness,
        next_action=next_action,
        freeze_manifest_ref=freeze_manifest_ref,
        skill_spec_ref="skill_spec.yaml",
        verification_spec_ref="verification_spec.yaml",
    ).write_json_file(state_path)


def _write_frozen_frontdesk_boundary(workspace: JobWorkspace) -> None:
    workspace.resolve_path("frontdesk").mkdir(parents=True, exist_ok=True)
    for ref, body in {
        "frontdesk/elicitation_report_001.json": '{"schema_version":"test.elicitation"}\n',
        "frontdesk/spec_audit_report_001.json": '{"schema_version":"test.audit"}\n',
        "frontdesk/freeze_gate_result.json": '{"decision":"freeze","frozen":true}\n',
    }.items():
        path = workspace.resolve_path(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    AcceptanceCriteriaSet(
        job_id=workspace.job_id,
        criteria=[
            AcceptanceCriterion(
                id="AC-001",
                description="The package must contain a readable package/SKILL.md file.",
                test_method="static",
                evidence_kind="verifier_check",
                required_evidence=["package_skill_md_present"],
                verifier_check_id="package_skill_md_present",
                priority="must",
                coverage_status="planned",
            )
        ],
    ).write_yaml_file(workspace.resolve_path("acceptance_criteria.yaml"))

    artifact_refs = (
        "frontdesk/elicitation_report_001.json",
        "frontdesk/spec_audit_report_001.json",
        "frontdesk/freeze_gate_result.json",
        "skill_spec.yaml",
        "acceptance_criteria.yaml",
        "verification_spec.yaml",
        "worker_input.md",
        "build_contract.yaml",
    )
    freeze_manifest = FreezeManifest(
        conversation_summary_hash="0" * 64,
        conversation_turn_range=[1, 1],
        elicitation_report_ref="frontdesk/elicitation_report_001.json",
        spec_audit_report_ref="frontdesk/spec_audit_report_001.json",
        skill_spec_ref="skill_spec.yaml",
        acceptance_criteria_ref="acceptance_criteria.yaml",
        verification_spec_ref="verification_spec.yaml",
        worker_input_ref="worker_input.md",
        build_contract_ref="build_contract.yaml",
        artifact_hashes={ref: sha256_file(workspace.resolve_path(ref, must_exist=True)) for ref in artifact_refs},
        freeze_gate_result_ref="frontdesk/freeze_gate_result.json",
        created_at="2026-05-23T00:00:00Z",
    )
    freeze_manifest_path = workspace.resolve_path("frontdesk/freeze_manifest.json")
    freeze_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    freeze_manifest.write_json_file(freeze_manifest_path)
    _write_frontdesk_state(
        workspace,
        readiness="frozen",
        next_action="route_to_build",
        freeze_manifest_ref="frontdesk/freeze_manifest.json",
    )
