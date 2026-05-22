from __future__ import annotations

from pathlib import Path
import json
import shutil

from contextforge import (
    AgentNodeContract,
    ContextKernel,
    ContextLedger,
    ModelError,
    ModelResponse,
    UsageDraft,
    WorkerRunRequest,
    with_computed_hash,
)

import skillfoundry
from skillfoundry import (
    GOAL_RUNTIME_LEDGER_REF,
    OWNED_LLM_WORKER_OUTPUT_SCHEMA_VERSION,
    WORKERS_V2_VERSION,
    CodexThreadSkillBuilderWorker,
    ExternalAgentSkillBuilderWorker,
    FakeSkillBuilderWorker,
    OwnedLLMSkillBuilderWorker,
    seed_goal_harness_context,
    write_contextforge_contract_artifacts,
)
from skillfoundry.workspace import JobWorkspace, initialize_job_workspace


CREATED_AT = "2026-05-22T00:00:00Z"

GOOD_OWNED_LLM_SKILL = """---
name: owned-llm-v2-skill
description: Deterministic owned LLM v2 worker fixture.
---

# Owned LLM V2 Skill

## Overview

This package is generated through the ContextForge Goal Harness owned LLM worker boundary.

## When To Use

- Use when a deterministic local fixture needs a valid Skill package.

## When Not To Use

- Do not use as registry approval evidence.

## Inputs

- Frozen SkillFoundry build inputs.

## Outputs

- A candidate package under package/.

## Workflow

- Read frozen inputs.
- Produce package artifacts only.
- Let verifier, coverage, and registry decide acceptance.

## Safety

- Do not self-approve or claim registry promotion.
"""


class ScriptedModelClient:
    def __init__(
        self,
        response_text: str | None = None,
        *,
        error: ModelError | None = None,
        usage: UsageDraft | None = None,
    ) -> None:
        self.response_text = response_text if response_text is not None else owned_llm_json()
        self.error = error
        self.usage = usage
        self.calls: list[dict[str, object]] = []

    def invoke(self, messages, model, params, tools=None):
        self.calls.append(
            {
                "messages": list(messages),
                "model": model,
                "params": dict(params),
                "tools": tools,
            }
        )
        if self.error is not None:
            return None, self.error, None
        return (
            ModelResponse(
                text=self.response_text,
                raw_response_artifact_ref=None,
                finish_reason="stop",
                metadata={"scripted": True},
            ),
            None,
            self.usage,
        )


def owned_llm_json(
    *,
    skill_markdown: str = GOOD_OWNED_LLM_SKILL,
    reference_files: list[dict[str, str]] | None = None,
    schema_version: str = OWNED_LLM_WORKER_OUTPUT_SCHEMA_VERSION,
) -> str:
    payload = {
        "schema_version": schema_version,
        "skill_markdown": skill_markdown,
        "reference_files": reference_files
        if reference_files is not None
        else [{"path": "references/guide.md", "content": "# Guide\n\nOwned LLM v2 guide.\n"}],
        "script_files": [{"path": "scripts/helper.py", "content": "def helper():\n    return 'ok'\n"}],
        "test_files": [{"path": "tests/fixture.md", "content": "# Fixture\n\nNo execution required.\n"}],
    }
    return json.dumps(payload, sort_keys=True)


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
    assert skillfoundry.OwnedLLMSkillBuilderWorker is OwnedLLMSkillBuilderWorker
    assert skillfoundry.OWNED_LLM_WORKER_OUTPUT_SCHEMA_VERSION == OWNED_LLM_WORKER_OUTPUT_SCHEMA_VERSION
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


def test_v2_owned_llm_worker_invokes_contextforge_model_boundary_and_writes_package(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-owned")
    request, ledger = _worker_request(workspace)
    ledger.close()
    client = ScriptedModelClient()

    result = OwnedLLMSkillBuilderWorker(workspace, client=client).run(request)

    assert result.status == "completed"
    assert result.failure_class is None
    assert result.final_output_ref == "package/SKILL.md"
    assert result.model_call_ids
    assert result.prompt_view_ids[0] == request.prompt_view.id
    assert result.metadata["owned_llm_worker"] is True
    assert result.metadata["contextforge_invoke_model_used"] is True
    assert result.metadata["worker_self_report_is_not_acceptance"] is True
    assert result.usage_summary["provider"] == "fake"
    assert result.usage_summary["model"] == "skillfoundry-owned-llm-fake-model"
    assert result.usage_summary["expected_cacheable_tokens"] == request.cache_plan.expected_cacheable_tokens
    assert workspace.resolve_path("package/SKILL.md", must_exist=True).is_file()
    assert workspace.resolve_path("package/references/guide.md", must_exist=True).is_file()
    assert workspace.resolve_path("attempts/001/owned_llm_worker_report.json", must_exist=True).is_file()
    assert workspace.resolve_path("attempts/001/owned_llm_worker_transcript.log", must_exist=True).is_file()
    assert "Owned LLM V2 Skill" in workspace.resolve_path("package/SKILL.md", must_exist=True).read_text()

    ledger = ContextLedger.connect(workspace.resolve_path(GOAL_RUNTIME_LEDGER_REF, must_exist=True))
    try:
        record = ledger.get_model_call(result.model_call_ids[0])
        assert record.id == result.model_call_ids[0]
        assert record.prompt_view_id in result.prompt_view_ids
        assert record.replay_bundle_ref == result.metadata["replay_bundle_ref"]
        replay_artifact = ledger.get_artifact(record.replay_bundle_ref.removeprefix("artifact:"))
        assert replay_artifact.relative_path.endswith(f"{record.id}.json")
        prompt_view, _blocks = ledger.get_prompt_view(record.prompt_view_id)
        rendered = "\n".join(message.content for message in prompt_view.messages)
        assert "Generated Review Assistant" not in rendered
        assert "SkillFoundry WP1 placeholder skill" in rendered
    finally:
        ledger.close()

    assert client.calls


def test_v2_owned_llm_worker_usage_summary_does_not_mark_available_usage_unavailable(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-owned-usage")
    request, ledger = _worker_request(workspace)
    ledger.close()
    client = ScriptedModelClient(
        usage=UsageDraft(
            input_tokens=100,
            cached_input_tokens=80,
            cache_telemetry_status="reported",
            output_tokens=20,
            cost_usd=0.01,
            latency_ms=1200,
            provider_payload={"fixture": True},
        )
    )

    result = OwnedLLMSkillBuilderWorker(workspace, client=client).run(request)

    assert result.status == "completed"
    assert result.usage_summary["usage_available"] is True
    assert result.usage_summary["usage_id"]
    assert "usage_unavailable_reason" not in result.usage_summary


def test_v2_owned_llm_worker_provider_error_fails_closed_without_package(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-owned-error")
    request, ledger = _worker_request(workspace)
    ledger.close()
    client = ScriptedModelClient(
        error=ModelError(
            error_type="ScriptedProviderError",
            message="deterministic provider failure",
            retryable=False,
            raw_error_artifact_ref=None,
            metadata={},
        )
    )

    result = OwnedLLMSkillBuilderWorker(workspace, client=client).run(request)

    assert result.status == "failed"
    assert result.failure_class == "provider_error"
    assert result.model_call_ids
    assert result.metadata["worker_self_report_is_not_acceptance"] is True
    assert not workspace.resolve_path("package/SKILL.md").exists()
    assert workspace.resolve_path("attempts/001/owned_llm_worker_report.json", must_exist=True).is_file()


def test_v2_owned_llm_worker_invalid_output_fails_closed_without_package(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-owned-invalid")
    request, ledger = _worker_request(workspace)
    ledger.close()

    result = OwnedLLMSkillBuilderWorker(workspace, client=ScriptedModelClient("```json\n{}\n```")).run(request)

    assert result.status == "failed"
    assert result.failure_class == "model_output_invalid"
    assert result.model_call_ids
    assert not workspace.resolve_path("package/SKILL.md").exists()
    assert "owned LLM output is not valid JSON" in result.summary


def test_v2_owned_llm_worker_unsafe_path_and_denied_scope_fail_closed(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-owned-scope")
    request, ledger = _worker_request(workspace)
    ledger.close()
    unsafe = OwnedLLMSkillBuilderWorker(
        workspace,
        client=ScriptedModelClient(owned_llm_json(reference_files=[{"path": "../escape.md", "content": "x\n"}])),
    ).run(request)
    assert unsafe.status == "failed"
    assert unsafe.failure_class == "model_output_invalid"
    assert not (workspace.root.parent / "escape.md").exists()
    assert not workspace.resolve_path("package/SKILL.md").exists()

    workspace2 = initialize_job_workspace(tmp_path / "runs", "workers-v2-owned-denied")
    request2, ledger2 = _worker_request(workspace2)
    ledger2.close()
    narrowed = _request_with_allowed_write_paths(request2, ["attempts"])
    denied = OwnedLLMSkillBuilderWorker(workspace2, client=ScriptedModelClient()).run(narrowed)
    assert denied.status == "failed"
    assert denied.failure_class == "write_scope_violation"
    assert not workspace2.resolve_path("package/SKILL.md").exists()
    assert "package/SKILL.md" in denied.metadata["attempted_changed_files"]


def test_v2_owned_llm_worker_package_symlink_fails_closed_without_outside_write(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-owned-package-symlink")
    request, ledger = _worker_request(workspace)
    ledger.close()
    outside = tmp_path / "outside-package"
    outside.mkdir()
    shutil.rmtree(workspace.root / "package")
    (workspace.root / "package").symlink_to(outside, target_is_directory=True)

    result = OwnedLLMSkillBuilderWorker(workspace, client=ScriptedModelClient()).run(request)

    assert result.status == "failed"
    assert result.failure_class == "path_security_violation"
    assert result.final_output_ref == "attempts/001/owned_llm_worker_report.json"
    assert not (outside / "SKILL.md").exists()
    assert workspace.resolve_path("attempts/001/owned_llm_worker_report.json", must_exist=True).is_file()
    assert result.metadata["diagnostic_write_error"] is None
    assert "symlink components are not allowed" in result.metadata["policy_error"]


def test_v2_owned_llm_worker_attempts_symlink_returns_failed_without_diagnostics(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-owned-attempts-symlink")
    request, ledger = _worker_request(workspace)
    ledger.close()
    outside = tmp_path / "outside-attempts"
    outside.mkdir()
    shutil.rmtree(workspace.root / "attempts")
    (workspace.root / "attempts").symlink_to(outside, target_is_directory=True)

    result = OwnedLLMSkillBuilderWorker(workspace, client=ScriptedModelClient()).run(request)

    assert result.status == "failed"
    assert result.failure_class == "path_security_violation"
    assert result.final_output_ref is None
    assert result.artifact_ids == []
    assert result.metadata["changed_files"] == []
    assert not workspace.resolve_path("package/SKILL.md").exists()
    assert not (outside / "001" / "owned_llm_worker_report.json").exists()
    assert "symlink components are not allowed" in result.metadata["diagnostic_write_error"]
    assert "attempts/001/owned_llm_worker_report.json" in result.metadata["attempted_changed_files"]


def test_v2_owned_llm_worker_diagnostic_target_directory_prevents_unreported_report(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-owned-diagnostic-directory")
    request, ledger = _worker_request(workspace)
    ledger.close()
    transcript_target = workspace.root / "attempts" / "001" / "owned_llm_worker_transcript.log"
    transcript_target.mkdir(parents=True)

    result = OwnedLLMSkillBuilderWorker(workspace, client=ScriptedModelClient()).run(request)

    assert result.status == "failed"
    assert result.failure_class == "path_security_violation"
    assert result.final_output_ref is None
    assert result.artifact_ids == []
    assert result.metadata["changed_files"] == []
    assert "target path is not a regular file" in result.metadata["diagnostic_write_error"]
    assert not workspace.resolve_path("package/SKILL.md").exists()
    assert not (workspace.root / "attempts" / "001" / "owned_llm_worker_report.json").exists()
    assert transcript_target.is_dir()


def test_v2_owned_llm_worker_parent_file_preflight_prevents_partial_package(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-owned-parent-file")
    request, ledger = _worker_request(workspace)
    ledger.close()
    shutil.rmtree(workspace.root / "package" / "references")
    (workspace.root / "package" / "references").write_text("not a directory\n", encoding="utf-8")

    result = OwnedLLMSkillBuilderWorker(workspace, client=ScriptedModelClient()).run(request)

    assert result.status == "failed"
    assert result.failure_class == "path_security_violation"
    assert result.final_output_ref == "attempts/001/owned_llm_worker_report.json"
    assert "parent path is not a directory" in result.metadata["policy_error"]
    assert not workspace.resolve_path("package/SKILL.md").exists()
    assert workspace.resolve_path("attempts/001/owned_llm_worker_report.json", must_exist=True).is_file()
    assert result.metadata["changed_files"] == [
        "attempts/001/owned_llm_worker_report.json",
        "attempts/001/owned_llm_worker_transcript.log",
    ]
    assert result.artifact_ids == [
        "workers-v2-owned-parent-file:attempts/001/owned_llm_worker_report.json",
        "workers-v2-owned-parent-file:attempts/001/owned_llm_worker_transcript.log",
    ]


def test_v2_owned_llm_worker_final_target_directory_preflight_prevents_partial_package(tmp_path: Path) -> None:
    workspace = initialize_job_workspace(tmp_path / "runs", "workers-v2-owned-target-directory")
    request, ledger = _worker_request(workspace)
    ledger.close()
    (workspace.root / "package" / "references" / "guide.md").mkdir()

    result = OwnedLLMSkillBuilderWorker(workspace, client=ScriptedModelClient()).run(request)

    assert result.status == "failed"
    assert result.failure_class == "path_security_violation"
    assert "target path is not a regular file" in result.metadata["policy_error"]
    assert not workspace.resolve_path("package/SKILL.md").exists()
    assert workspace.resolve_path("attempts/001/owned_llm_worker_report.json", must_exist=True).is_file()


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
