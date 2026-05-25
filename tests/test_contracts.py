from __future__ import annotations

import json
from pathlib import Path

import pytest
from contextforge import AgentNodeContract, GoalContract, VerificationGate

from skillfoundry.contracts import (
    BUILD_NODE_CONTRACT_REF,
    CONTRACT_MANIFEST_REF,
    GOAL_CONTRACT_REF,
    VERIFICATION_GATE_REF,
    build_agent_node_contract,
    build_goal_contract,
    build_verification_gate,
    write_contextforge_contract_artifacts,
)
from skillfoundry.schema import BuildContract, SchemaValidationError, SkillSpec, VerificationSpec, sha256_file
from skillfoundry.workspace import JobWorkspace, initialize_job_workspace


CREATED_AT = "2026-05-22T00:00:00Z"


def _skill_spec(*, title: str = "Review Assistant Skill", acceptance: list[str] | None = None) -> SkillSpec:
    return SkillSpec(
        skill_id="review-assistant",
        title=title,
        description="Build a Codex skill that reviews pull requests against local project rules.",
        trigger_scenarios=["The user asks for pull request review assistance."],
        non_trigger_scenarios=["The user asks for unrelated product planning."],
        required_inputs=["Repository path", "Review target"],
        expected_outputs=["Findings with file and line references", "Residual risk summary"],
        constraints=["Use repository-local evidence only."],
        acceptance_criteria=acceptance
        if acceptance is not None
        else [
            "Reports correctness risks before summaries.",
            "References concrete files and lines for every finding.",
        ],
        reference_materials=["README.md"],
        security_notes=["Do not read secrets or raw frontdesk conversation."],
    )


def _verification_spec(*, acceptance: list[str] | None = None) -> VerificationSpec:
    return VerificationSpec(
        spec_id="review-assistant-verification",
        job_id="demo-001",
        required_checks=["schema_round_trip", "locked_input_hash_match", "path_confinement"],
        artifact_requirements=["package/SKILL.md"],
        path_policies=["reject_absolute_paths", "reject_parent_traversal"],
        acceptance_criteria=acceptance
        if acceptance is not None
        else ["All package files pass static verification."],
        verifier_version="test-verifier-v1",
    )


def _workspace(tmp_path: Path, *, skill_spec: SkillSpec | None = None) -> JobWorkspace:
    return initialize_job_workspace(
        tmp_path / "runs",
        "demo-001",
        skill_spec=skill_spec or _skill_spec(),
        verification_spec=_verification_spec(),
        overwrite=True,
    )


def test_build_goal_contract_from_workspace_round_trips(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    goal = build_goal_contract(workspace, created_at=CREATED_AT)

    assert isinstance(goal, GoalContract)
    assert "Review Assistant Skill" in goal.objective
    assert "reviews pull requests" in goal.objective
    assert goal.success_criteria == _skill_spec().acceptance_criteria
    assert goal.verification_gate_id == "vg-demo-001"
    assert GoalContract.from_dict(goal.to_dict()) == goal
    assert goal.contract_hash.startswith("sha256:")


def test_build_agent_node_contract_has_visibility_policy_write_scope_and_cache_epoch(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    goal = build_goal_contract(workspace, created_at=CREATED_AT)
    gate = build_verification_gate(workspace, goal.goal_id)

    node = build_agent_node_contract(workspace, goal, gate)
    second = build_agent_node_contract(workspace, goal, gate)

    selector_types = {
        selector.value.get("metadata.skillfoundry_context_type")
        for selector in node.visible_context
        if isinstance(selector.value, dict)
    }
    forbidden_tags = {selector.value for selector in node.forbidden_context}

    assert isinstance(node, AgentNodeContract)
    assert {"skill_spec", "acceptance_criteria", "verification_gate", "build_contract"}.issubset(
        selector_types
    )
    assert {"raw_frontdesk_conversation", "secret"}.issubset(forbidden_tags)
    assert node.write_scope.allowed_paths == ["package", "attempts"]
    assert ".." not in node.write_scope.forbidden_paths
    assert ".env" in node.write_scope.forbidden_paths
    assert "skill_spec.yaml" in node.write_scope.forbidden_paths
    assert "frontdesk" in node.write_scope.forbidden_paths
    assert all(tool.network_policy == "disabled" for tool in node.allowed_tools)
    assert any(tool.tool_name == "network" and tool.allowed is False for tool in node.allowed_tools)
    assert node.cache_policy.mode == "stable_prefix"
    assert node.cache_policy.cache_epoch_id == second.cache_policy.cache_epoch_id
    assert AgentNodeContract.from_dict(node.to_dict()) == node


def test_build_verification_gate_maps_required_evidence_hashes_and_forbidden_claims(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    goal = build_goal_contract(workspace, created_at=CREATED_AT)

    gate = build_verification_gate(workspace, goal.goal_id)

    assert isinstance(gate, VerificationGate)
    assert {
        "package/SKILL.md",
        "artifact_manifest.json",
        "verifier/verification_result.json",
        "qa/acceptance_coverage_result.json",
    }.issubset(set(gate.required_evidence))
    assert {item.path for item in gate.artifact_hashes}.issuperset(
        {
            "skill_spec.yaml",
            "verification_spec.yaml",
            "worker_input.md",
            "build_contract.yaml",
        }
    )
    assert "artifact_manifest.json" not in {item.path for item in gate.artifact_hashes}
    assert all(item.sha256.startswith("sha256:") for item in gate.artifact_hashes)
    assert "self-approved" in gate.forbidden_claims
    assert ".." not in gate.forbidden_paths
    assert ".." in gate.metadata["rejected_forbidden_path_policies"]
    assert gate.metadata["gate_stage"] == "post_build_verification_promotion"
    assert VerificationGate.from_dict(gate.to_dict()) == gate


def test_verification_gate_requires_but_does_not_hash_pin_mutable_artifact_manifest(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    goal = build_goal_contract(workspace, created_at=CREATED_AT)

    gate = build_verification_gate(workspace, goal.goal_id)

    assert "artifact_manifest.json" in gate.required_evidence
    assert "artifact_manifest.json" not in {item.path for item in gate.artifact_hashes}


def test_write_contextforge_contract_artifacts_writes_manifest_and_json(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    artifacts = write_contextforge_contract_artifacts(workspace, created_at=CREATED_AT)

    for ref in [GOAL_CONTRACT_REF, BUILD_NODE_CONTRACT_REF, VERIFICATION_GATE_REF, CONTRACT_MANIFEST_REF]:
        assert workspace.resolve_path(ref, must_exist=True).is_file()

    goal_payload = json.loads(workspace.resolve_path(GOAL_CONTRACT_REF, must_exist=True).read_text())
    node_payload = json.loads(workspace.resolve_path(BUILD_NODE_CONTRACT_REF, must_exist=True).read_text())
    gate_payload = json.loads(workspace.resolve_path(VERIFICATION_GATE_REF, must_exist=True).read_text())
    manifest = json.loads(workspace.resolve_path(CONTRACT_MANIFEST_REF, must_exist=True).read_text())

    assert GoalContract.from_dict(goal_payload) == artifacts.goal_contract
    assert AgentNodeContract.from_dict(node_payload) == artifacts.build_node_contract
    assert VerificationGate.from_dict(gate_payload) == artifacts.verification_gate
    assert manifest["goal_contract_hash"] == sha256_file(workspace.resolve_path(GOAL_CONTRACT_REF, must_exist=True))
    assert manifest["build_node_contract_hash"] == sha256_file(
        workspace.resolve_path(BUILD_NODE_CONTRACT_REF, must_exist=True)
    )
    assert manifest["verification_gate_hash"] == sha256_file(
        workspace.resolve_path(VERIFICATION_GATE_REF, must_exist=True)
    )
    assert manifest["excluded_artifacts"] == ["frontdesk/conversation.jsonl"]


def test_write_contextforge_contract_artifacts_can_reuse_frozen_artifacts(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    first = write_contextforge_contract_artifacts(workspace, created_at=CREATED_AT)
    hashes = {
        ref: sha256_file(workspace.resolve_path(ref, must_exist=True))
        for ref in [GOAL_CONTRACT_REF, BUILD_NODE_CONTRACT_REF, VERIFICATION_GATE_REF, CONTRACT_MANIFEST_REF]
    }

    second = write_contextforge_contract_artifacts(
        workspace,
        created_at="2026-05-22T00:05:00Z",
        overwrite=False,
    )

    assert second == first
    assert {
        ref: sha256_file(workspace.resolve_path(ref, must_exist=True))
        for ref in [GOAL_CONTRACT_REF, BUILD_NODE_CONTRACT_REF, VERIFICATION_GATE_REF, CONTRACT_MANIFEST_REF]
    } == hashes


def test_raw_conversation_is_never_used_in_goal_or_visible_context(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    frontdesk_dir = workspace.root / "frontdesk"
    frontdesk_dir.mkdir()
    marker = "RAW_CONVERSATION_SHOULD_NOT_APPEAR"
    (frontdesk_dir / "conversation.jsonl").write_text(marker, encoding="utf-8")

    goal = build_goal_contract(workspace, created_at=CREATED_AT)
    gate = build_verification_gate(workspace, goal.goal_id)
    node = build_agent_node_contract(workspace, goal, gate)

    assert marker not in json.dumps(goal.to_dict(), sort_keys=True)
    assert marker not in json.dumps(node.to_dict(), sort_keys=True)
    assert all(selector.value != "raw_frontdesk_conversation" for selector in node.visible_context)
    assert "raw_frontdesk_conversation" in {selector.value for selector in node.forbidden_context}
    assert "frontdesk/conversation.jsonl" in {selector.value for selector in node.forbidden_context}


def test_contract_generation_fails_closed_without_success_criteria(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, skill_spec=_skill_spec(acceptance=[]))
    verification_spec = _verification_spec(acceptance=[])

    with pytest.raises(SchemaValidationError, match="success_criteria"):
        build_goal_contract(workspace, verification_spec=verification_spec, created_at=CREATED_AT)


def test_contract_hash_and_cache_epoch_change_when_frozen_spec_changes(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    base_goal = build_goal_contract(workspace, created_at=CREATED_AT)
    base_gate = build_verification_gate(workspace, base_goal.goal_id)
    base_node = build_agent_node_contract(workspace, base_goal, base_gate)
    changed_spec = _skill_spec(title="Changed Review Assistant Skill")

    changed_goal = build_goal_contract(workspace, skill_spec=changed_spec, created_at=CREATED_AT)
    changed_node = build_agent_node_contract(workspace, changed_goal, base_gate)

    assert changed_goal.contract_hash != base_goal.contract_hash
    assert changed_node.cache_policy.cache_epoch_id != base_node.cache_policy.cache_epoch_id


def test_agent_node_contract_rejects_unsafe_allowed_write_scope(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    goal = build_goal_contract(workspace, created_at=CREATED_AT)
    gate = build_verification_gate(workspace, goal.goal_id)
    build_contract = BuildContract.read_yaml_file(workspace.resolve_path("build_contract.yaml", must_exist=True))
    unsafe = BuildContract(
        job_id=build_contract.job_id,
        skill_spec_ref=build_contract.skill_spec_ref,
        verification_spec_ref=build_contract.verification_spec_ref,
        workspace_root=build_contract.workspace_root,
        allowed_write_paths=["../outside"],
        blocked_paths=build_contract.blocked_paths,
        timeout_seconds=build_contract.timeout_seconds,
        attempt_limit=build_contract.attempt_limit,
        required_artifacts=build_contract.required_artifacts,
        locked_input_hashes=build_contract.locked_input_hashes,
    )

    with pytest.raises(SchemaValidationError, match="allowed_write_paths"):
        build_agent_node_contract(workspace, goal, gate, build_contract=unsafe)


def test_codex_worker_contract_declares_boundary_not_internal_control(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    goal = build_goal_contract(workspace, created_at=CREATED_AT)
    gate = build_verification_gate(workspace, goal.goal_id)

    node = build_agent_node_contract(
        workspace,
        goal,
        gate,
        worker_kind="codex_sdk_thread",
        worker_name="codex-sdk-thread",
    )

    assert node.worker.kind == "codex_sdk_thread"
    assert node.worker.metadata["internal_prompt_replay_available"] is False
    assert node.worker.metadata["internal_tool_loop_control_available"] is False
    assert node.worker.metadata["boundary_enforcement"] == "input_contract_and_post_run_diff"
    assert node.metadata["codex_internal_prompt_cache_tool_loop_controlled"] is False
