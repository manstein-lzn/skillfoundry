from __future__ import annotations

import json

import pytest

import skillfoundry
from contextforge.schema import ModelError, ModelResponse
from skillfoundry import (
    ACCEPTANCE_COVERAGE_RESULT_REF,
    APPROVAL_APPROVED,
    AcceptanceCoverageEvaluator,
    AcceptanceCriteriaPlanner,
    AcceptanceCriteriaSet,
    AcceptanceCriterion,
    BuildContract,
    LLM_SKILL_BUILDER_OUTPUT_SCHEMA_VERSION,
    LLM_SKILL_BUILDER_STATUS_FAIL_CLOSED,
    LLMSkillBuilderWorker,
    LocalSkillRegistry,
    QALab,
    RegistryGateError,
    SkillSpec,
    Verifier,
    WorkerAdapter,
    initialize_job_workspace,
    sha256_file,
)


FROZEN_INPUT_REFS = (
    "build_contract.yaml",
    "skill_spec.yaml",
    "acceptance_criteria.yaml",
    "verification_spec.yaml",
    "worker_input.md",
)

GOOD_SKILL_MD = """---
name: llm-builder-pilot-skill
description: Deterministic LLM builder pilot fixture.
references:
  - references/guide.md
scripts:
  - scripts/helper.py
---

# LLM Builder Pilot Skill

## Overview

This package gives deterministic pytest failure triage using only local repository evidence.

## When To Use

- Use when a developer asks for deterministic pytest failure triage in a local repository.

## When Not To Use

- Do not use when the request requires deployment, live providers, or network debugging.

## Inputs

- A pytest failure log, repository path, and locked SkillFoundry worker input manifest.

## Outputs

- A concise repair plan, changed-file summary, and verification command list.

## Workflow

1. Read the pytest failure log and repository path from the locked input manifest.
2. Compare the failing assertion with nearby source code and tests.
3. Return a repair plan with exact verification commands.

## Safety

- Do not run network commands or live providers during triage.
- Keep helper scripts under package/scripts.
"""


class ScriptedLLMClient:
    def __init__(
        self,
        response_text: str | None = None,
        *,
        error: ModelError | None = None,
        exception: BaseException | None = None,
    ) -> None:
        self.response_text = response_text if response_text is not None else builder_json()
        self.error = error
        self.exception = exception
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
        if self.exception is not None:
            raise self.exception
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
            None,
        )

    def prompt_text(self) -> str:
        assert self.calls, "scripted client was not invoked"
        messages = self.calls[0]["messages"]
        return "\n".join(getattr(message, "content", str(message)) for message in messages)


def skill_spec(job_id: str) -> SkillSpec:
    return SkillSpec(
        skill_id=f"{job_id}-skill",
        title="Deterministic pytest repair triage",
        description="LLM builder pilot SkillSpec.",
        trigger_scenarios=["A developer asks for deterministic pytest failure triage."],
        non_trigger_scenarios=["The request requires deployment, live providers, or network debugging."],
        required_inputs=["A pytest failure log and repository path."],
        expected_outputs=["A concise repair plan and verification command list."],
        constraints=["No network calls.", "No live provider calls."],
        acceptance_criteria=["Report concrete workflow, safety, and IO contract evidence."],
        reference_materials=[],
        security_notes=["Helper scripts must remain under package/scripts."],
    )


def criterion(criterion_id: str, **overrides) -> AcceptanceCriterion:
    payload = {
        "id": criterion_id,
        "description": f"{criterion_id} is deterministically covered.",
        "source_requirement": "Build a deterministic local skill.",
        "source_turn_ids": ["turn-001"],
        "requirement_id": f"REQ-{criterion_id}",
        "test_method": "static",
        "pass_condition": "The mapped deterministic evidence passes.",
        "failure_examples": ["Evidence is missing."],
        "required_evidence": [],
        "evidence_kind": "verifier_check",
        "priority": "must",
        "risk_tags": [],
        "data_sensitivity": "internal",
        "coverage_status": "planned",
        "verifier_check_id": "package_skill_md_present",
    }
    payload.update(overrides)
    return AcceptanceCriterion(**payload)


def make_frozen_workspace(tmp_path, *, job_id: str = "llm-builder-001"):
    workspace = initialize_job_workspace(
        tmp_path / "runs",
        job_id,
        skill_spec=skill_spec(job_id),
        worker_input=(
            "# Worker Input\n\n"
            "Build the Codex Skill described by the frozen root specs. "
            "Use local deterministic evidence only.\n"
        ),
    )
    AcceptanceCriteriaSet(
        criteria=[
            criterion("AC-VERIFIER", verifier_check_id="package_skill_md_present"),
            criterion(
                "AC-QA-WORKFLOW",
                evidence_kind="qa_report",
                verifier_check_id=None,
                required_evidence=["workflow_actionability"],
            ),
        ],
        job_id=workspace.job_id,
    ).write_yaml_file(workspace.resolve_path("acceptance_criteria.yaml"))

    locked_hashes = {
        ref: sha256_file(workspace.resolve_path(ref, must_exist=True))
        for ref in ("skill_spec.yaml", "acceptance_criteria.yaml", "verification_spec.yaml", "worker_input.md")
    }
    BuildContract(
        job_id=workspace.job_id,
        skill_spec_ref="skill_spec.yaml",
        verification_spec_ref="verification_spec.yaml",
        workspace_root=str(workspace.root),
        allowed_write_paths=["package", "attempts"],
        blocked_paths=[".."],
        timeout_seconds=5,
        attempt_limit=2,
        required_artifacts=list(FROZEN_INPUT_REFS),
        locked_input_hashes=locked_hashes,
    ).write_yaml_file(workspace.resolve_path("build_contract.yaml", must_exist=True))

    manifest = workspace.read_manifest()
    unlocked = [record for record in manifest.artifacts if record.path not in FROZEN_INPUT_REFS]
    manifest.artifacts = [workspace.record_artifact(ref, locked=True) for ref in FROZEN_INPUT_REFS] + unlocked
    workspace.write_manifest(manifest)
    workspace.check_locked_inputs()
    return workspace


def builder_json(
    *,
    skill_markdown: str = GOOD_SKILL_MD,
    reference_files: list[dict[str, str]] | None = None,
    script_files: list[dict[str, str]] | None = None,
    test_files: list[dict[str, str]] | None = None,
    schema_version: str = LLM_SKILL_BUILDER_OUTPUT_SCHEMA_VERSION,
) -> str:
    payload = {
        "schema_version": schema_version,
        "skill_markdown": skill_markdown,
        "reference_files": reference_files
        if reference_files is not None
        else [{"path": "references/guide.md", "content": "# Guide\n\nLocal deterministic guide.\n"}],
        "script_files": script_files
        if script_files is not None
        else [{"path": "scripts/helper.py", "content": "def helper() -> str:\n    return 'ok'\n"}],
        "test_files": test_files
        if test_files is not None
        else [{"path": "tests/fixture.md", "content": "# Fixture\n\nNo executable smoke failure.\n"}],
        "summary": "Scripted LLM builder wrote a package candidate; final gates remain external.",
        "warnings": [],
    }
    return json.dumps(payload, sort_keys=True)


def frozen_hashes(workspace) -> dict[str, str]:
    return {ref: sha256_file(workspace.resolve_path(ref, must_exist=True)) for ref in FROZEN_INPUT_REFS}


def test_llm_builder_api_is_exported():
    assert skillfoundry.LLMSkillBuilderWorker is LLMSkillBuilderWorker
    assert skillfoundry.LLM_SKILL_BUILDER_OUTPUT_SCHEMA_VERSION == LLM_SKILL_BUILDER_OUTPUT_SCHEMA_VERSION
    assert skillfoundry.LLM_SKILL_BUILDER_STATUS_FAIL_CLOSED == "fail_closed"
    assert skillfoundry.LLM_SKILL_BUILDER_AGENT_ROLE == "llm_skill_builder"


def test_builder_prompt_uses_frozen_refs_and_excludes_raw_frontdesk_conversation(tmp_path):
    workspace = make_frozen_workspace(tmp_path, job_id="llm-builder-prompt")
    frontdesk_dir = workspace.root / "frontdesk"
    frontdesk_dir.mkdir()
    (frontdesk_dir / "conversation.jsonl").write_text("FRONTDESK_SENTINEL_SHOULD_NOT_ENTER_PROMPT\n", encoding="utf-8")
    client = ScriptedLLMClient()

    WorkerAdapter(LLMSkillBuilderWorker(client=client)).invoke(workspace, "001")

    prompt = client.prompt_text()
    for ref in (
        "skill_spec.yaml",
        "acceptance_criteria.yaml",
        "verification_spec.yaml",
        "build_contract.yaml",
        "worker_input.md",
        "attempts/001/input_manifest.json",
    ):
        assert ref in prompt
    assert "Use only the frozen inputs" in prompt
    assert "Write only under package/" in prompt
    assert "do not self-approve" in prompt.lower()
    assert "Verifier, QA Lab, Acceptance Coverage, and Registry" in prompt
    assert "frontdesk/conversation.jsonl" not in prompt
    assert "FRONTDESK_SENTINEL_SHOULD_NOT_ENTER_PROMPT" not in prompt


def test_scripted_llm_output_writes_skill_and_optional_package_files(tmp_path):
    workspace = make_frozen_workspace(tmp_path, job_id="llm-builder-writes")

    result = WorkerAdapter(LLMSkillBuilderWorker(client=ScriptedLLMClient())).invoke(workspace, "001")

    assert result.ready_for_verifier is True
    assert result.accepted is False
    assert result.report.status == "completed"
    assert result.report.exit_status == "success"
    assert result.report.artifacts == [
        "package/SKILL.md",
        "package/references/guide.md",
        "package/scripts/helper.py",
        "package/tests/fixture.md",
    ]
    assert "LLM Builder Pilot Skill" in workspace.resolve_path("package/SKILL.md", must_exist=True).read_text(
        encoding="utf-8"
    )
    assert workspace.resolve_path("package/references/guide.md", must_exist=True).is_file()
    assert workspace.resolve_path("package/scripts/helper.py", must_exist=True).is_file()
    assert workspace.resolve_path("package/tests/fixture.md", must_exist=True).is_file()


@pytest.mark.parametrize(
    ("job_id", "response_text", "failure_fragment"),
    [
        ("llm-builder-invalid-json", "```json\n{}\n```", "invalid_json"),
        (
            "llm-builder-invalid-schema",
            builder_json(schema_version="wrong.schema"),
            "schema_validation_failed",
        ),
        (
            "llm-builder-unsafe-path",
            builder_json(reference_files=[{"path": "../escape.md", "content": "escape\n"}]),
            "unsafe_path",
        ),
    ],
)
def test_invalid_json_schema_or_path_fails_closed_without_acceptance(tmp_path, job_id, response_text, failure_fragment):
    workspace = make_frozen_workspace(tmp_path, job_id=job_id)

    result = WorkerAdapter(LLMSkillBuilderWorker(client=ScriptedLLMClient(response_text))).invoke(workspace, "001")

    assert result.report.status == "failed"
    assert result.report.exit_status == LLM_SKILL_BUILDER_STATUS_FAIL_CLOSED
    assert result.failure_class == LLM_SKILL_BUILDER_STATUS_FAIL_CLOSED
    assert result.ready_for_verifier is False
    assert result.accepted is False
    assert failure_fragment in result.report.failures[0]
    assert not workspace.resolve_path("package/SKILL.md").exists()

    verification = Verifier().verify(workspace, attempt_id="001")
    assert verification.passed is False
    with pytest.raises(RegistryGateError):
        LocalSkillRegistry(tmp_path / f"{job_id}-registry.json").add_verified(workspace, version="1.0.0")


def test_provider_error_fails_closed_without_package(tmp_path):
    workspace = make_frozen_workspace(tmp_path, job_id="llm-builder-provider-error")
    client = ScriptedLLMClient(
        error=ModelError(
            error_type="ScriptedProviderError",
            message="deterministic provider failure",
            retryable=False,
            raw_error_artifact_ref=None,
            metadata={},
        )
    )

    result = WorkerAdapter(LLMSkillBuilderWorker(client=client)).invoke(workspace, "001")

    assert result.report.status == "failed"
    assert result.report.exit_status == LLM_SKILL_BUILDER_STATUS_FAIL_CLOSED
    assert result.ready_for_verifier is False
    assert "provider_error" in result.report.failures[0]
    assert not workspace.resolve_path("package/SKILL.md").exists()


def test_builder_cannot_modify_locked_inputs_through_worker_adapter(tmp_path):
    workspace = make_frozen_workspace(tmp_path, job_id="llm-builder-locked-inputs")
    before = frozen_hashes(workspace)
    malicious_output = builder_json(
        reference_files=[{"path": "package/../build_contract.yaml", "content": "tampered\n"}]
    )

    result = WorkerAdapter(LLMSkillBuilderWorker(client=ScriptedLLMClient(malicious_output))).invoke(workspace, "001")

    assert result.report.status == "failed"
    assert result.report.exit_status == LLM_SKILL_BUILDER_STATUS_FAIL_CLOSED
    assert result.accepted is False
    assert frozen_hashes(workspace) == before
    workspace.check_locked_inputs()


def test_full_pipeline_with_scripted_llm_builder_registers_coverage_provenance(tmp_path):
    workspace = make_frozen_workspace(tmp_path, job_id="llm-builder-pipeline")
    worker_result = WorkerAdapter(LLMSkillBuilderWorker(client=ScriptedLLMClient())).invoke(workspace, "001")

    assert worker_result.ready_for_verifier is True
    assert worker_result.accepted is False

    verification = Verifier().verify(workspace, attempt_id="001")
    assert verification.passed is True

    qa_result = QALab().evaluate(workspace)
    assert qa_result.passed is True

    plan = AcceptanceCriteriaPlanner().plan(workspace)
    coverage = AcceptanceCoverageEvaluator().evaluate(workspace, plan=plan)
    assert coverage.passed is True
    assert workspace.resolve_path(ACCEPTANCE_COVERAGE_RESULT_REF, must_exist=True).is_file()

    registry = LocalSkillRegistry(tmp_path / "llm-builder-registry.json")
    entry = registry.add_verified(workspace, version="1.0.0", review_status="wp17_test")
    coverage_provenance = entry.provenance["acceptance_coverage_result"]

    assert entry.approval_status == APPROVAL_APPROVED
    assert entry.worker_invocation_id == worker_result.invocation.invocation_id
    assert coverage_provenance["ref"] == ACCEPTANCE_COVERAGE_RESULT_REF
    assert coverage_provenance["result_id"] == coverage.result_id
    assert coverage_provenance["passed"] is True
    assert coverage_provenance["provenance"]["coverage_plan"]["plan_id"] == plan.plan_id
    assert registry.verify_entry(entry).valid is True
