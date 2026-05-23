import json

import skillfoundry
from skillfoundry import (
    SkillFoundryContextAdapter,
    Verifier,
    audit_report_to_json,
    initialize_job_workspace,
)
from skillfoundry.worker import WorkerAdapter, WorkerExecutionOutcome


VALID_SKILL_MD = """---
name: context-fixture-skill
description: Deterministic WP5 context fixture.
---

# Context Fixture Skill

## Overview

This fixture gives the verifier a complete local package.

## When To Use

- Use when WP5 needs a verified worker boundary fixture.

## When Not To Use

- Do not use for real Codex Worker integration.

## Inputs

- A locked SkillFoundry build contract and worker input manifest.

## Outputs

- A local Codex Skill package candidate.

## Workflow

1. Read the locked inputs.
2. Produce deterministic package files.
3. Wait for the independent verifier.

## Safety

- Do not treat worker self-report as acceptance evidence.
"""


FORBIDDEN_OVERCLAIMS = [
    "controls Codex internal prompt/tool loop/cache/cost",
    "external worker internals count as owned LLM replay",
    "Codex Worker tool loop belongs to ContextForge",
    "fake cost",
]


class ContextFixtureWorker:
    @property
    def worker_type(self):
        return "test:context-fixture"

    def run(self, context):
        context.write_text("package/SKILL.md", VALID_SKILL_MD)
        return WorkerExecutionOutcome(
            status="completed",
            exit_status="success",
            summary="Fixture worker wrote a package; verifier remains the acceptance gate.",
            artifacts=["package/SKILL.md"],
            transcript_lines=["wrote package/SKILL.md"],
            usage_unavailable_reason="Context fixture worker does not call model providers.",
            simulated_duration_ms=123,
        )


def make_verified_workspace(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "context-001")
    worker_result = WorkerAdapter(ContextFixtureWorker()).invoke(workspace, "001")
    verification_result = Verifier().verify(workspace)
    assert verification_result.passed is True
    return workspace, worker_result, verification_result


def test_context_api_is_exported():
    assert skillfoundry.SkillFoundryContextAdapter is SkillFoundryContextAdapter
    assert skillfoundry.CONTEXT_ADAPTER_VERSION == "skillfoundry.context.wp5.v1"


def test_owned_llm_call_goes_through_contextforge_and_replay_is_locatable(tmp_path):
    workspace = initialize_job_workspace(tmp_path / "runs", "owned-001")
    adapter = SkillFoundryContextAdapter.for_workspace(workspace)

    result = adapter.call_owned_llm(
        node_id="clarify",
        intent="clarify requirement",
        input_text="Build a pytest helper skill.",
        output_contract="Return a short clarification summary.",
    )

    assert result.context_request.__class__.__name__ == "ContextRequest"
    assert result.prompt_view.__class__.__name__ == "PromptView"
    assert result.envelope.__class__.__name__ == "ModelCallEnvelope"
    assert result.record.__class__.__name__ == "ModelCallRecord"
    assert result.record.response is not None
    assert result.record.error is None
    assert result.record.usage_id is None
    assert result.record.usage_unavailable_reason == "usage draft unavailable"
    assert result.usage_available is False
    assert result.usage_unavailable_reason == "usage draft unavailable"
    assert result.replay_artifact_ref.startswith("artifact:")
    assert result.replay_artifact_path.is_file()

    replay = json.loads(result.replay_artifact_path.read_text(encoding="utf-8"))
    assert replay["prompt_view"]["id"] == result.prompt_view.id
    assert replay["model_call_ref"] == result.record.id
    assert replay["model_call_snapshot"]["usage_unavailable_reason"] == "usage draft unavailable"

    model_calls = adapter.ledger.query_model_calls(run_id=workspace.job_id)
    prompt_views = adapter.ledger.query_prompt_views(run_id=workspace.job_id)
    assert [call.id for call in model_calls] == [result.record.id]
    assert [view.id for view in prompt_views] == [result.prompt_view.id]


def test_owned_llm_call_records_model_error_and_replay(tmp_path):
    class RaisingClient:
        def invoke(self, messages, model, params, tools=None):
            raise RuntimeError("deterministic provider failure")

    workspace = initialize_job_workspace(tmp_path / "runs", "owned-error-001")
    adapter = SkillFoundryContextAdapter.for_workspace(workspace)

    result = adapter.call_owned_llm(
        node_id="repair_plan",
        intent="plan repair after failure",
        input_text="The package is missing a Safety section.",
        client=RaisingClient(),
    )

    assert result.record.response is None
    assert result.record.error is not None
    assert result.record.error.error_type == "RuntimeError"
    assert result.record.usage_id is None
    assert result.record.usage_unavailable_reason == "usage draft unavailable"
    assert result.replay_artifact_path.is_file()
    replay = json.loads(result.replay_artifact_path.read_text(encoding="utf-8"))
    assert replay["model_call_snapshot"]["error"]["message"] == "deterministic provider failure"


def test_worker_boundary_evidence_is_not_owned_llm_replay(tmp_path):
    workspace, worker_result, verification_result = make_verified_workspace(tmp_path)
    adapter = SkillFoundryContextAdapter.for_workspace(workspace)

    boundary = adapter.record_worker_boundary(worker_result, verification_result=verification_result)

    assert boundary.artifact_path.is_file()
    assert boundary.payload["evidence_kind"] == "external worker boundary evidence only"
    assert boundary.payload["owned_llm_replay"] is False
    assert boundary.payload["external_worker_internal_replay"] is False
    assert boundary.payload["transcript_ref"] == worker_result.invocation.transcript_ref
    assert boundary.payload["diff_ref"] == worker_result.invocation.diff_ref
    assert boundary.payload["execution_report_ref"] == worker_result.invocation.execution_report_ref
    assert boundary.payload["verifier_result_ref"] == "verifier/verification_result.json"
    assert boundary.payload["verification_status"] == "passed"
    assert boundary.payload["usage_available"] is False
    assert boundary.payload["usage_unavailable_reason"] == (
        "Context fixture worker does not call model providers."
    )

    assert adapter.ledger.query_model_calls(run_id=workspace.job_id) == []
    audit = adapter.audit_report()
    assert audit.owned_llm_calls == []
    assert len(audit.external_worker_boundaries) == 1
    assert audit.metrics.replay_coverage.external_worker_boundary_count == 1
    assert audit.metrics.replay_coverage.external_worker_internal_replay_count == 0


def test_verifier_log_governance_is_bounded_and_prompt_safe(tmp_path):
    workspace, _worker_result, verification_result = make_verified_workspace(tmp_path)
    raw_marker = "RAW_VERIFIER_LOG_SENTINEL_SHOULD_NOT_ENTER_PROMPT"
    sandbox_log = workspace.resolve_path("verifier/sandbox.log", must_exist=True)
    sandbox_log.write_text(
        sandbox_log.read_text(encoding="utf-8")
        + "\n"
        + "\n".join(f"{raw_marker}_{index}" for index in range(80))
        + "\n",
        encoding="utf-8",
    )
    adapter = SkillFoundryContextAdapter.for_workspace(workspace)

    evidence = adapter.record_verifier_prompt_evidence(
        verification_result,
        raw_log_refs=("verifier/sandbox.log", "verifier/static_report.json"),
        max_context_bytes=500,
    )

    assert evidence.raw_bytes > evidence.context_bytes
    assert evidence.context_bytes <= 500
    assert evidence.truncated is True
    assert evidence.summarized is True
    assert raw_marker not in evidence.governed_content
    assert evidence.raw_log_refs[0]["ref"] == "verifier/sandbox.log"

    owned = adapter.call_owned_llm(
        node_id="report_summary",
        intent="summarize verifier result",
        context_needs=["tool_diagnostics"],
        required_types=["tool_output"],
        output_contract="Return a bounded verifier summary.",
    )
    prompt_text = "\n".join(message.content for message in owned.prompt_view.messages)
    assert "Governed tool output" in prompt_text
    assert raw_marker not in prompt_text


def test_metrics_include_attempt_status_duration_and_usage_unavailable_reason(tmp_path):
    workspace, worker_result, verification_result = make_verified_workspace(tmp_path)
    adapter = SkillFoundryContextAdapter.for_workspace(workspace)
    adapter.call_owned_llm(
        node_id="route",
        intent="route verified package",
        input_text="Choose the next route after verification.",
    )
    adapter.record_worker_boundary(worker_result, verification_result=verification_result)

    metrics = adapter.metrics()

    assert metrics.attempt_count == 1
    assert metrics.verification_status == "passed"
    assert metrics.worker_duration_ms == 123
    assert metrics.worker_usage_available is False
    assert metrics.worker_usage_unavailable_reason == (
        "Context fixture worker does not call model providers."
    )
    assert metrics.owned_llm_call_count == 1
    assert metrics.owned_llm_usage_available is False
    assert metrics.owned_llm_usage_unavailable_reasons == ["usage draft unavailable"]
    assert metrics.external_worker_boundary_count == 1


def test_audit_and_replay_coverage_separate_owned_calls_from_worker_boundaries(tmp_path):
    workspace, worker_result, verification_result = make_verified_workspace(tmp_path)
    adapter = SkillFoundryContextAdapter.for_workspace(workspace)
    owned = adapter.call_owned_llm(
        node_id="failure_analysis",
        intent="analyze verification outcome",
        input_text="Summarize the verified build.",
    )
    adapter.record_worker_boundary(worker_result, verification_result=verification_result)

    coverage = adapter.replay_coverage()
    assert coverage.owned_llm_call_count == 1
    assert coverage.owned_llm_replay_artifact_count == 1
    assert coverage.owned_llm_replay_coverage == 1.0
    assert coverage.external_worker_boundary_count == 1
    assert coverage.external_worker_internal_replay_count == 0
    assert coverage.external_worker_internal_replay_coverage == 0.0
    assert owned.replay_artifact_path.is_file()

    audit = adapter.audit_report()
    audit_json = audit_report_to_json(audit)
    assert len(audit.owned_llm_calls) == 1
    assert len(audit.external_worker_boundaries) == 1
    assert audit.owned_llm_calls[0]["kind"] == "owned_llm_call"
    assert audit.external_worker_boundaries[0]["evidence_kind"] == "external worker boundary evidence only"
    for forbidden in FORBIDDEN_OVERCLAIMS:
        assert forbidden not in audit_json
