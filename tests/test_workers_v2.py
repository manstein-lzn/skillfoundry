from __future__ import annotations

from pathlib import Path

from contextforge import AgentNodeContract, ContextKernel, ContextLedger, WorkerRunRequest, with_computed_hash

import skillfoundry
from skillfoundry import (
    GOAL_RUNTIME_LEDGER_REF,
    WORKERS_V2_VERSION,
    CodexThreadSkillBuilderWorker,
    ExternalAgentSkillBuilderWorker,
    FakeSkillBuilderWorker,
    seed_goal_harness_context,
    write_contextforge_contract_artifacts,
)
from skillfoundry.workspace import JobWorkspace, initialize_job_workspace


CREATED_AT = "2026-05-22T00:00:00Z"


def _worker_request(workspace: JobWorkspace) -> tuple[WorkerRunRequest, ContextLedger]:
    contracts = write_contextforge_contract_artifacts(workspace, created_at=CREATED_AT)
    ledger = ContextLedger.connect(workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF))
    ledger.initialize()
    seed_goal_harness_context(
        workspace,
        ledger,
        contracts,
        run_id=f"{workspace.job_id}-run",
        created_at=CREATED_AT,
    )
    compiled = ContextKernel(ledger).prepare_goal_context(
        contracts.goal_contract,
        contracts.build_node_contract,
        graph_id="skillfoundry-v2",
        run_id=f"{workspace.job_id}-run",
        task_id="build_skill",
        created_at=CREATED_AT,
        metadata={"skillfoundry_job_id": workspace.job_id},
    )
    return (
        WorkerRunRequest(
            goal_run_id=f"{workspace.job_id}-goal-run",
            goal_contract=contracts.goal_contract,
            node_contract=contracts.build_node_contract,
            context_view=compiled.context_view,
            prompt_view=compiled.prompt_view,
            prompt_blocks=compiled.prompt_blocks,
            cache_plan=compiled.cache_plan,
            metadata={"skillfoundry_job_id": workspace.job_id},
        ),
        ledger,
    )


def _request_with_allowed_write_paths(request: WorkerRunRequest, allowed_paths: list[str]) -> WorkerRunRequest:
    node_payload = request.node_contract.to_dict()
    node_payload["write_scope"]["allowed_paths"] = allowed_paths
    node_payload = with_computed_hash(node_payload, "contract_hash")
    return WorkerRunRequest(
        goal_run_id=request.goal_run_id,
        goal_contract=request.goal_contract,
        node_contract=AgentNodeContract.from_dict(node_payload),
        context_view=request.context_view,
        prompt_view=request.prompt_view,
        prompt_blocks=request.prompt_blocks,
        cache_plan=request.cache_plan,
        metadata=dict(request.metadata),
    )


def test_workers_v2_api_is_exported() -> None:
    assert skillfoundry.WORKERS_V2_VERSION == WORKERS_V2_VERSION
    assert skillfoundry.FakeSkillBuilderWorker is FakeSkillBuilderWorker
    assert skillfoundry.CodexThreadSkillBuilderWorker is CodexThreadSkillBuilderWorker
    assert skillfoundry.ExternalAgentSkillBuilderWorker is ExternalAgentSkillBuilderWorker


def test_v2_fake_worker_success_records_boundary_artifacts_and_metadata(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-fake")
    request, ledger = _worker_request(workspace)
    try:
        result = FakeSkillBuilderWorker(workspace).run(request)
    finally:
        ledger.close()

    assert result.status == "completed"
    assert result.final_output_ref == "package/SKILL.md"
    assert result.failure_class is None
    assert workspace.resolve_path("package/SKILL.md", must_exist=True).is_file()
    assert workspace.resolve_path("attempts/fake_worker_report.json", must_exist=True).is_file()
    assert workspace.resolve_path("attempts/fake_worker_transcript.log", must_exist=True).is_file()
    assert result.artifact_ids == [
        "workers-v2-fake:package/SKILL.md",
        "workers-v2-fake:attempts/fake_worker_report.json",
        "workers-v2-fake:attempts/fake_worker_transcript.log",
    ]
    assert result.metadata["workers_v2"] == WORKERS_V2_VERSION
    assert result.metadata["worker_self_report_is_not_acceptance"] is True
    assert result.metadata["changed_files"] == [
        "package/SKILL.md",
        "attempts/fake_worker_report.json",
        "attempts/fake_worker_transcript.log",
    ]
    assert result.usage_summary["usage_unavailable_reason"] == "offline_fake_worker"


def test_v2_fake_worker_write_scope_violation_fails_closed_without_outside_write(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-escape")
    request, ledger = _worker_request(workspace)
    outside = workspace.root.parent / "outside.txt"
    try:
        result = FakeSkillBuilderWorker(workspace, extra_changed_files=("../outside.txt",)).run(request)
    finally:
        ledger.close()

    assert result.status == "failed"
    assert result.failure_class == "write_scope_violation"
    assert result.final_output_ref == "attempts/fake_worker_report.json"
    assert not outside.exists()
    assert not workspace.resolve_path("package/SKILL.md").exists()
    assert workspace.resolve_path("attempts/fake_worker_report.json", must_exist=True).is_file()
    assert "../outside.txt" in result.metadata["attempted_changed_files"]
    assert "policy_error" in result.metadata
    assert result.metadata["worker_self_report_is_not_acceptance"] is True


def test_v2_fake_worker_does_not_write_diagnostics_when_attempts_scope_is_denied(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-narrow-scope")
    request, ledger = _worker_request(workspace)
    narrowed_request = _request_with_allowed_write_paths(request, ["package"])
    try:
        result = FakeSkillBuilderWorker(workspace).run(narrowed_request)
    finally:
        ledger.close()

    assert result.status == "failed"
    assert result.failure_class == "write_scope_violation"
    assert result.final_output_ref is None
    assert result.artifact_ids == []
    assert result.metadata["changed_files"] == []
    assert result.metadata["attempted_changed_files"] == [
        "package/SKILL.md",
        "attempts/fake_worker_report.json",
        "attempts/fake_worker_transcript.log",
    ]
    assert "attempts/fake_worker_report.json" in result.metadata["diagnostic_policy_error"]
    assert not workspace.resolve_path("package/SKILL.md").exists()
    assert not workspace.resolve_path("attempts/fake_worker_report.json").exists()
    assert not workspace.resolve_path("attempts/fake_worker_transcript.log").exists()


def test_v2_codex_thread_worker_records_black_box_boundary_only(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-codex")
    request, ledger = _worker_request(workspace)
    try:
        result = CodexThreadSkillBuilderWorker(
            workspace,
            thread_id="thread-001",
            transcript_ref="attempts/codex_thread_transcript.log",
            diff_refs=("attempts/codex_thread.diff",),
            artifact_refs=("package/SKILL.md",),
            changed_files=("package/SKILL.md", "attempts/codex_thread_transcript.log"),
        ).run(request)
    finally:
        ledger.close()

    assert result.status == "completed"
    assert result.failure_class is None
    assert result.metadata["black_box_worker"] is True
    assert result.metadata["thread_id"] == "thread-001"
    assert result.metadata["internal_prompt_replay_available"] is False
    assert result.metadata["internal_tool_loop_replay_available"] is False
    assert result.metadata["contextforge_controls_internal_codex_loop"] is False
    assert result.metadata["worker_self_report_is_not_acceptance"] is True
    assert result.usage_summary["usage_unavailable_reason"] == (
        "codex_thread_boundary_does_not_report_provider_usage"
    )
    assert "package/SKILL.md" in result.metadata["changed_files"]


def test_v2_codex_thread_worker_enforces_declared_write_scope(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-codex-scope")
    request, ledger = _worker_request(workspace)
    try:
        result = CodexThreadSkillBuilderWorker(
            workspace,
            thread_id="thread-escape",
            transcript_ref="attempts/codex_thread_transcript.log",
            artifact_refs=("package/SKILL.md",),
            changed_files=("skill_spec.yaml",),
        ).run(request)
    finally:
        ledger.close()

    assert result.status == "failed"
    assert result.failure_class == "write_scope_violation"
    assert "path is forbidden by write scope" in result.metadata["policy_error"]
    assert result.metadata["worker_self_report_is_not_acceptance"] is True


def test_v2_external_agent_worker_requires_boundary_evidence(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-external")
    request, ledger = _worker_request(workspace)
    try:
        missing = ExternalAgentSkillBuilderWorker(workspace, name="external-missing").run(request)
        missing_evidence = ExternalAgentSkillBuilderWorker(
            workspace,
            name="external-missing-evidence",
            artifact_refs=("package/SKILL.md",),
        ).run(request)
        complete = ExternalAgentSkillBuilderWorker(
            workspace,
            name="external-complete",
            artifact_refs=("package/SKILL.md",),
            evidence_refs=("attempts/external_agent_report.json",),
            changed_files=("package/SKILL.md", "attempts/external_agent_report.json"),
        ).run(request)
    finally:
        ledger.close()

    assert missing.status == "failed"
    assert missing.failure_class == "missing_boundary_artifacts"
    assert missing.metadata["worker_self_report_is_not_acceptance"] is True
    assert missing_evidence.status == "failed"
    assert missing_evidence.failure_class == "missing_boundary_evidence"
    assert missing_evidence.metadata["worker_self_report_is_not_acceptance"] is True
    assert complete.status == "completed"
    assert complete.failure_class is None
    assert complete.metadata["evidence_refs"] == ["attempts/external_agent_report.json"]
    assert complete.usage_summary["usage_unavailable_reason"] == (
        "external_agent_boundary_does_not_report_provider_usage"
    )
